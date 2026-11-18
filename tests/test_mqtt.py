"""MQTT tests - skipped automatically when no broker is running.

Start one first:  mosquitto -c config/mosquitto.conf      (or tools/mosquitto/run_mosquitto.sh)
"""

import time
import uuid

import pytest

from teleop.backends import MockBackend
from teleop.client import OperatorClient
from teleop.config import ServerParams
from teleop.server import RobotServer
from teleop.transport.mqtt import MqttClient, MqttServer, topics

from .conftest import MQTT_HOST, MQTT_PORT, needs_broker

pytestmark = needs_broker


@pytest.fixture(params=[0, 1], ids=["qos0", "qos1"])
def mqtt_system(request):
    qos = request.param
    rid = "test-" + uuid.uuid4().hex[:8]
    server = RobotServer(MockBackend(), MqttServer(MQTT_HOST, MQTT_PORT, robot_id=rid, qos=qos),
                         ServerParams())
    server.start()
    server.run_in_thread()
    client = OperatorClient(MqttClient(MQTT_HOST, MQTT_PORT, robot_id=rid, qos=qos))
    client.connect()
    time.sleep(0.3)
    yield server, client, qos
    client.close()
    server.close()


def test_topics():
    t = topics("r1")
    assert t["cmd"] == "teleop/r1/cmd" and t["telem"] == "teleop/r1/telem"


def test_ping_over_mqtt(mqtt_system):
    _, client, _ = mqtt_system
    rtts = [client.ping() for _ in range(5)]
    assert all(r is not None and r < 0.2 for r in rtts)


def test_move_over_mqtt(mqtt_system):
    server, client, _ = mqtt_system
    p = client.send_line("move 0.4 0.4")
    assert client.wait_result(p, 15)
    assert p.result["outcome"] == "reached"
    assert client.telem_count > 3


def test_robot_status_retained(mqtt_system):
    _, client, _ = mqtt_system
    assert client.transport.robot_online is True


def test_operator_last_will_stops_robot(mqtt_system):
    """Kill the operator's connection without a goodbye: the broker publishes its
    Last Will, and the robot must stop at once (well before the 1 s watchdog
    would, because the socket close is seen by the broker immediately)."""
    server, client, _ = mqtt_system
    p = client.send_line("vel 0.2 0")
    assert client.wait_ack(p)
    client._stop.set()
    t0 = time.monotonic()
    client.transport.client._sock.close()      # abrupt: no DISCONNECT packet
    while server.state != "LINK_LOST" and time.monotonic() - t0 < 3:
        time.sleep(0.01)
    assert server.state == "LINK_LOST"
    assert any(e[1] == "link_lost" for e in server.events)
