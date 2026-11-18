"""End-to-end tests over real TCP sockets (mock robot, localhost)."""

import io
import time

from teleop.cli import Shell
from teleop.netem import Impairment, ImpairmentProxy
from teleop.client import OperatorClient
from teleop.protocol import make_cmd
from teleop.transport.tcp import TcpClient


def test_ping_and_status(tcp_system):
    server, client = tcp_system
    rtt = client.ping()
    assert rtt is not None and rtt < 0.1
    p = client.send_line("status")
    assert client.wait_ack(p) and p.ok
    time.sleep(0.15)
    assert client.telemetry["state"] in ("IDLE", "MOVING")


def test_move_produces_result_and_telemetry(tcp_system):
    server, client = tcp_system
    p = client.send_line("move 0.5 0.5")
    assert client.wait_ack(p, 2) and p.ok
    assert client.wait_result(p, 15)
    assert p.result["outcome"] == "reached"
    assert abs(server.backend.get_pose()[0] - 0.5) < 0.05
    assert client.telem_count > 5


def test_bad_command_is_rejected_not_fatal(tcp_system):
    server, client = tcp_system
    client.transport.send({"type": "cmd", "seq": 99, "t": time.time(), "cmd": "goto", "args": {"x": 1}})
    client.transport.send({"type": "cmd", "seq": 100, "t": time.time(), "cmd": "explode", "args": {}})
    time.sleep(0.3)
    assert server.stats["rejected"] == 2
    assert client.ping() is not None             # server still alive


def test_stale_motion_command_is_rejected(tcp_system):
    server, client = tcp_system
    client.transport.send(make_cmd(500, "move", {"dist": 1.0, "speed": 0.3}, t=time.time() - 5))
    time.sleep(0.3)
    assert server.stats["stale"] == 1
    assert server.controller.mode == "idle"


def test_duplicate_command_is_executed_once(tcp_system):
    """MQTT QoS 1 may deliver a message twice; the robot must not run it twice."""
    server, client = tcp_system
    msg = make_cmd(900, "turn", {"angle": 10, "rate": 60}, sid=client.sid)
    client.transport.send(msg)
    client.transport.send(msg)
    time.sleep(0.3)
    assert server.stats["duplicates"] == 1
    assert sum(1 for e in server.events if e[1] == "start" and e[2] == 900) == 1
    # a new session may reuse the same seq number
    client.transport.send(make_cmd(900, "stop", sid="othersession"))
    time.sleep(0.2)
    assert server.stats["duplicates"] == 1


def test_watchdog_stops_robot_when_operator_goes_silent(tcp_system):
    server, client = tcp_system
    p = client.send_line("vel 0.2 0")
    assert client.wait_ack(p)
    client._stop.set()                           # stop heartbeats, keep the socket open
    t0 = time.monotonic()
    while server.state != "LINK_LOST" and time.monotonic() - t0 < 3:
        time.sleep(0.02)
    elapsed = time.monotonic() - t0
    assert server.state == "LINK_LOST"
    assert server.controller.mode == "idle"
    assert 0.9 < elapsed < 1.5                   # watchdog timeout is 1.0 s


def test_new_goal_preempts_running_goal(tcp_system):
    server, client = tcp_system
    p1 = client.send_line("move 2 0.2")
    client.wait_ack(p1)
    p2 = client.send_line("turn 30")
    assert client.wait_result(p1, 2)
    assert p1.result["outcome"] == "preempted"
    assert client.wait_result(p2, 10) and p2.result["outcome"] == "reached"


def test_second_operator_is_refused(tcp_system):
    server, client = tcp_system
    other = OperatorClient(TcpClient("127.0.0.1", server.transport.port, auto_reconnect=False))
    errors = []
    other.listeners.append(lambda m: errors.append(m) if m.get("type") == "error" else None)
    other.connect()
    time.sleep(0.3)
    assert errors and "busy" in errors[0]["err"]
    assert server.transport.refused == 1
    assert client.ping() is not None            # the first operator keeps control
    other.close()


def test_proxy_adds_delay(tcp_system):
    server, client = tcp_system
    client.close()                              # free the control lock for the proxied client
    time.sleep(0.1)
    proxy = ImpairmentProxy(0, "127.0.0.1", server.transport.port, Impairment(delay_ms=50)).start()
    try:
        c = OperatorClient(TcpClient("127.0.0.1", proxy.port))
        c.connect()
        time.sleep(0.2)
        rtts = [c.ping() for _ in range(5)]
        assert all(0.095 < r < 0.2 for r in rtts)  # 2 x 50 ms one-way
        c.close()
    finally:
        proxy.close()


def test_proxy_loss_is_retransmitted_not_dropped(tcp_system):
    server, client = tcp_system
    client.close()
    time.sleep(0.1)
    proxy = ImpairmentProxy(0, "127.0.0.1", server.transport.port,
                            Impairment(delay_ms=5, loss=0.3), seed=4).start()
    try:
        c = OperatorClient(TcpClient("127.0.0.1", proxy.port))
        c.connect()
        rtts = [c.ping(timeout=5) for _ in range(20)]
        assert all(r is not None for r in rtts)      # TCP: nothing is lost ...
        assert max(rtts) > 0.2                        # ... but some pings wait for an RTO
        assert proxy.retransmissions > 0
        c.close()
    finally:
        proxy.close()


def test_outage_resets_and_client_reconnects(tcp_system):
    server, client = tcp_system
    client.close()
    time.sleep(0.1)
    proxy = ImpairmentProxy(0, "127.0.0.1", server.transport.port).start()
    try:
        c = OperatorClient(TcpClient("127.0.0.1", proxy.port))
        c.connect()
        assert c.ping() is not None
        proxy.outage(0.5)
        assert c.ping(timeout=0.3) is None            # swallowed by the outage
        time.sleep(1.2)
        assert c.transport.reconnects >= 1
        assert c.ping() is not None
        c.close()
    finally:
        proxy.close()


def test_shell_script(tcp_system):
    server, client = tcp_system
    out = io.StringIO()
    sh = Shell(client, out=out, echo=True)
    for line in ["move 0.3 0.4", "wait", "status", "history", "fly", "rtt 3", "quit"]:
        if not sh.execute(line):
            break
    text = out.getvalue()
    assert "result #" in text and "reached" in text
    assert "pose x=" in text
    assert "unknown command 'fly'" in text
    assert "3/3 replies" in text


def test_shell_macro_and_log(tcp_system, tmp_path):
    server, client = tcp_system
    macro = tmp_path / "m.tlm"
    macro.write_text("# comment line\nturn 20\nwait\nstatus\n")
    log = tmp_path / "t.csv"
    out = io.StringIO()
    sh = Shell(client, out=out)
    sh.execute(f"log start {log}")
    sh.execute(f"macro {macro}")
    sh.execute("log stop")
    assert "teleop> turn 20" in out.getvalue()
    lines = log.read_text().splitlines()
    assert lines[0].startswith("t_recv,") and len(lines) > 3
