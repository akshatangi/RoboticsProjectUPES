"""Shared test fixtures.

MQTT tests need a broker.  They use MQTT_HOST / MQTT_PORT (default
127.0.0.1:1883) and are skipped automatically when nothing is listening.
"""

import os
import socket
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from teleop.backends import MockBackend  # noqa: E402
from teleop.client import OperatorClient  # noqa: E402
from teleop.config import ServerParams  # noqa: E402
from teleop.server import RobotServer  # noqa: E402
from teleop.transport.tcp import TcpClient, TcpServer  # noqa: E402

MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))


def broker_available() -> bool:
    try:
        with socket.create_connection((MQTT_HOST, MQTT_PORT), timeout=0.5):
            return True
    except OSError:
        return False


needs_broker = pytest.mark.skipif(not broker_available(),
                                  reason=f"no MQTT broker on {MQTT_HOST}:{MQTT_PORT}")


@pytest.fixture
def tcp_system():
    """A running mock robot server on a free TCP port plus a connected client."""
    params = ServerParams(record_trace=True)
    server = RobotServer(MockBackend(seed=1), TcpServer("127.0.0.1", 0), params)
    server.start()
    server.run_in_thread()
    client = OperatorClient(TcpClient("127.0.0.1", server.transport.port))
    client.connect()
    time.sleep(0.2)
    yield server, client
    client.close()
    server.close()
