"""Network impairment proxy: adds delay, jitter, loss and outages to a TCP link.

Operator  --->  [ ImpairmentProxy ]  --->  robot server (TCP) or MQTT broker
          <---                       <---

Both transports in this project run over TCP (MQTT is itself carried on TCP),
so the proxy sits on the operator's TCP connection and treats both the same.
Linux `tc netem` would do this in the kernel but needs root; this proxy runs
anywhere (Windows/macOS/Linux) and is reproducible with a seed.

Model, applied separately to each direction:

* delay + jitter: every chunk of bytes is held for  max(0, N(delay, jitter))
  seconds.  TCP never reorders bytes, so a chunk is never released before
  the chunk in front of it (head-of-line blocking, just like real TCP).
* loss: real TCP does not lose data - it retransmits it.  So a "lost"
  segment here is delivered late by one retransmission timeout
  (RTO = max(200 ms, 2*delay + 4*jitter); 200 ms is Linux's minimum RTO),
  and the RTO doubles for each further loss of the same segment.
* outage(seconds): everything sent during the outage is discarded and at the
  end every connection through the proxy is reset - the same as a Wi-Fi
  drop long enough for the TCP connection to fail.  Clients must reconnect.

Limits (stated in the report): chunk = whatever one recv() returned, not a real
IP packet; no bandwidth limit; no congestion-window effects.

Command line:
    python -m teleop.netem --listen 9001 --target 127.0.0.1:9000 --delay 100 --jitter 20 --loss 0.01
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import logging
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

log = logging.getLogger("teleop.netem")


@dataclass
class Impairment:
    delay_ms: float = 0.0      # one-way mean delay added in EACH direction
    jitter_ms: float = 0.0     # standard deviation of the delay
    loss: float = 0.0          # probability that a chunk needs a retransmission

    @property
    def label(self) -> str:
        return f"{self.delay_ms:g}ms+-{self.jitter_ms:g} loss {self.loss * 100:g}%"

    def rto(self) -> float:
        return max(0.200, (2 * self.delay_ms + 4 * self.jitter_ms) / 1000.0)


class _Pipe:
    """One direction of one connection: src socket -> delay queue -> dst socket."""

    def __init__(self, proxy: "ImpairmentProxy", src: socket.socket, dst: socket.socket, name: str):
        self.proxy, self.src, self.dst, self.name = proxy, src, dst, name
        self.queue: List[Tuple[float, int, bytes]] = []
        self.cv = threading.Condition()
        self.last_release = 0.0
        self.closed = False
        self._order = itertools.count()
        threading.Thread(target=self._read, daemon=True, name=f"netem-r-{name}").start()
        threading.Thread(target=self._write, daemon=True, name=f"netem-w-{name}").start()

    def _read(self) -> None:
        imp, rng = self.proxy.impairment, self.proxy.rng
        while True:
            try:
                data = self.src.recv(65536)
            except OSError:
                data = b""
            if not data:
                break
            now = time.monotonic()
            self.proxy.bytes[self.name] += len(data)
            if self.proxy.in_outage():
                self.proxy.dropped_bytes += len(data)
                continue
            with self.proxy.rng_lock:
                delay = max(0.0, rng.gauss(imp.delay_ms, imp.jitter_ms) / 1000.0) if imp.jitter_ms else imp.delay_ms / 1000.0
                rto, extra = imp.rto(), 0.0
                while imp.loss > 0 and rng.random() < imp.loss:
                    extra += rto              # lost: wait one retransmission timeout ...
                    rto *= 2                  # ... and back off if it is lost again
                    self.proxy.retransmissions += 1
            release = max(now + delay + extra, self.last_release)   # keep byte order
            self.last_release = release
            with self.cv:
                heapq.heappush(self.queue, (release, next(self._order), data))
                self.cv.notify()
        self.close()

    def _write(self) -> None:
        while True:
            with self.cv:
                while not self.queue and not self.closed:
                    self.cv.wait()
                if self.closed and not self.queue:
                    return
                release, _, data = self.queue[0]
                wait = release - time.monotonic()
                if wait > 0:
                    self.cv.wait(wait)
                    continue
                heapq.heappop(self.queue)
            try:
                self.dst.sendall(data)
            except OSError:
                self.close()
                return

    def close(self) -> None:
        with self.cv:
            if self.closed:
                return
            self.closed = True
            self.queue.clear()
            self.cv.notify_all()
        for s in (self.src, self.dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


class ImpairmentProxy:
    def __init__(self, listen_port: int, target_host: str, target_port: int,
                 impairment: Optional[Impairment] = None, seed: Optional[int] = None,
                 listen_host: str = "127.0.0.1"):
        self.listen = (listen_host, listen_port)
        self.target = (target_host, target_port)
        self.impairment = impairment or Impairment()
        self.rng = random.Random(seed)
        self.rng_lock = threading.Lock()
        self._outage_until = 0.0
        self._pipes: List[_Pipe] = []
        self._lock = threading.Lock()
        self.retransmissions = 0
        self.dropped_bytes = 0
        self.bytes = {"up": 0, "down": 0}     # operator->robot and robot->operator
        self.connections = 0
        self._sock: Optional[socket.socket] = None

    def start(self) -> "ImpairmentProxy":
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(self.listen)
        self.listen = self._sock.getsockname()
        self._sock.listen(8)
        threading.Thread(target=self._accept, daemon=True, name="netem-accept").start()
        return self

    @property
    def port(self) -> int:
        return self.listen[1]

    def _accept(self) -> None:
        while True:
            try:
                client, _ = self._sock.accept()  # type: ignore[union-attr]
            except OSError:
                return
            if self.in_outage():                 # link is down: refuse new connections too
                client.close()
                continue
            try:
                upstream = socket.create_connection(self.target, timeout=3.0)
                upstream.settimeout(None)
            except OSError as exc:
                log.warning("cannot reach target %s:%s: %s", *self.target, exc)
                client.close()
                continue
            for s in (client, upstream):
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.connections += 1
            with self._lock:
                self._pipes = [p for p in self._pipes if not p.closed]
                self._pipes.append(_Pipe(self, client, upstream, "up"))
                self._pipes.append(_Pipe(self, upstream, client, "down"))

    def in_outage(self) -> bool:
        return time.monotonic() < self._outage_until

    def outage(self, seconds: float, reset: bool = True) -> None:
        """Start a link outage now.  If reset, connections are dropped when it ends."""
        self._outage_until = time.monotonic() + seconds
        if reset:
            threading.Timer(seconds, self.reset_connections).start()

    def reset_connections(self) -> None:
        with self._lock:
            pipes, self._pipes = self._pipes, []
        for p in pipes:
            p.close()

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
        self.reset_connections()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="TCP impairment proxy (delay, jitter, loss)")
    ap.add_argument("--listen", type=int, required=True, help="local port the operator connects to")
    ap.add_argument("--target", required=True, help="host:port of the robot server or MQTT broker")
    ap.add_argument("--delay", type=float, default=0.0, help="one-way delay per direction, ms")
    ap.add_argument("--jitter", type=float, default=0.0, help="delay standard deviation, ms")
    ap.add_argument("--loss", type=float, default=0.0, help="segment loss probability, 0..1")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args(argv)
    host, port = a.target.rsplit(":", 1)
    imp = Impairment(a.delay, a.jitter, a.loss)
    proxy = ImpairmentProxy(a.listen, host, int(port), imp, seed=a.seed).start()
    print(f"Impairment proxy 127.0.0.1:{proxy.port} -> {a.target}  [{imp.label}]  Ctrl+C to stop",
          flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        proxy.close()


if __name__ == "__main__":
    main()
