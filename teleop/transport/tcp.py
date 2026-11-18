"""TCP socket transport (newline-delimited JSON).

Robot = server: it listens on a port (default 9000) and gives control to ONE
operator at a time (exclusive control lock).  A second operator is refused
with an error message while the current one is active; it may take over only
after the current one has been silent for `takeover_after` seconds (by then
the robot's watchdog has already stopped the robot).
Operator = client: connects to host:port and reconnects automatically if the
connection drops (for example after a Wi-Fi outage).

Two details that matter for teleoperation:
* TCP_NODELAY switches off Nagle's algorithm.  Without it the OS may hold a
  small command for up to ~40 ms hoping to merge it with the next one.
* TCP is a byte stream, so every JSON message ends with '\\n' and the receiver
  splits on it (protocol.LineBuffer).
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Optional

from ..protocol import LineBuffer, ProtocolError, decode, encode
from .base import ClientTransport, Message, OnMessage, ServerTransport

log = logging.getLogger(__name__)


def _tune(sock: socket.socket) -> None:
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def _reader(sock: socket.socket, on_message: OnMessage) -> None:
    """Read lines from the socket until it closes; decode and hand them on."""
    buf = LineBuffer()
    while True:
        try:
            data = sock.recv(65536)
        except OSError:
            return
        if not data:
            return
        try:
            lines = buf.feed(data)
        except ProtocolError as exc:
            log.warning("dropping bad stream data: %s", exc)
            continue
        for line in lines:
            try:
                on_message(decode(line))
            except ProtocolError as exc:
                log.warning("bad message ignored: %s", exc)


class TcpServer(ServerTransport):
    name = "tcp"

    def __init__(self, host: str = "0.0.0.0", port: int = 9000, takeover_after: float = 1.0):
        self.host, self.port = host, port
        self.takeover_after = takeover_after
        self._client: Optional[socket.socket] = None
        self._client_rx = 0.0          # monotonic time of the last data from the operator
        self.refused = 0
        self._lock = threading.Lock()
        self._listener: Optional[socket.socket] = None
        self._running = False

    def start(self, on_message: OnMessage) -> None:
        self._on_message = on_message
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))
        self.port = self._listener.getsockname()[1]   # useful when port=0
        self._listener.listen(1)
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True, name="tcp-accept").start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                sock, addr = self._listener.accept()  # type: ignore[union-attr]
            except OSError:
                return
            _tune(sock)
            with self._lock:
                if self._client is not None:
                    if time.monotonic() - self._client_rx < self.takeover_after:
                        # Someone is actively driving: refuse the newcomer.
                        self.refused += 1
                        try:
                            sock.sendall(encode({"type": "error", "err": "robot busy: another "
                                                 "operator has control"}) + b"\n")
                            sock.close()
                        except OSError:
                            pass
                        log.info("refused second operator from %s:%s", *addr)
                        continue
                    try:                          # old operator went silent: take over
                        self._client.close()
                    except OSError:
                        pass
                self._client = sock
                self._client_rx = time.monotonic()
            log.info("operator connected from %s:%s", *addr)
            threading.Thread(target=self._serve, args=(sock,), daemon=True, name="tcp-read").start()

    def _serve(self, sock: socket.socket) -> None:
        def on_message(msg: Message) -> None:
            self._client_rx = time.monotonic()
            self._on_message(msg)
        _reader(sock, on_message)
        with self._lock:
            if self._client is sock:
                self._client = None
        log.info("operator disconnected")

    def send(self, msg: Message) -> bool:
        data = encode(msg) + b"\n"
        with self._lock:
            sock = self._client
            if sock is None:
                return False
            try:
                sock.sendall(data)
                return True
            except OSError:
                self._client = None
                return False

    @property
    def connected(self) -> bool:
        return self._client is not None

    def close(self) -> None:
        self._running = False
        for s in (self._listener, self._client):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


class TcpClient(ClientTransport):
    name = "tcp"

    def __init__(self, host: str = "127.0.0.1", port: int = 9000, auto_reconnect: bool = True,
                 reconnect_interval: float = 0.25):
        self.host, self.port = host, port
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._closed = False
        self.reconnects = 0

    def _open(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=3.0)
        sock.settimeout(None)
        _tune(sock)
        return sock

    def connect(self, on_message: OnMessage, timeout: float = 5.0) -> None:
        self._on_message = on_message
        deadline = time.monotonic() + timeout
        while True:
            try:
                sock = self._open()
                break
            except OSError as exc:
                if time.monotonic() > deadline:
                    raise ConnectionError(f"cannot connect to {self.host}:{self.port}: {exc}") from None
                time.sleep(0.1)
        self._sock = sock
        threading.Thread(target=self._read_loop, args=(sock,), daemon=True, name="tcp-client").start()

    def _read_loop(self, sock: socket.socket) -> None:
        _reader(sock, self._on_message)
        with self._lock:
            if self._sock is sock:
                self._sock = None
        # Connection lost: keep trying to come back (unless we closed on purpose).
        while self.auto_reconnect and not self._closed:
            time.sleep(self.reconnect_interval)
            try:
                new = self._open()
            except OSError:
                continue
            with self._lock:
                if self._closed:
                    new.close()
                    return
                self._sock = new
            self.reconnects += 1
            log.info("reconnected to %s:%s", self.host, self.port)
            threading.Thread(target=self._read_loop, args=(new,), daemon=True, name="tcp-client").start()
            return

    def send(self, msg: Message) -> bool:
        data = encode(msg) + b"\n"
        with self._lock:
            if self._sock is None:
                return False
            try:
                self._sock.sendall(data)
                return True
            except OSError:
                return False

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def close(self) -> None:
        self._closed = True
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._sock.close()
                self._sock = None
