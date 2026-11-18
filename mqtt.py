"""MQTT transport (paho-mqtt 2.x, MQTT 3.1.1) through a broker such as Mosquitto.

Robot and operator never connect to each other; both connect to the broker
and exchange messages through topics (publish / subscribe):

    teleop/<robot_id>/cmd        operator -> robot   commands and heartbeats
    teleop/<robot_id>/telem      robot -> operator   telemetry (10 Hz)
    teleop/<robot_id>/event      robot -> operator   ack, pong, result
    teleop/<robot_id>/status     robot "online"/"offline"   (retained, Last Will)
    teleop/<robot_id>/operator   operator "online"/"offline" (retained, Last Will)

Quality of Service (QoS):
    QoS 0  "at most once"  - sent once, no acknowledgement; lost if the
                             connection is down.  Lowest overhead.
    QoS 1  "at least once" - receiver must answer PUBACK; unacknowledged
                             messages are resent after a reconnect, and the
                             broker stores messages for a disconnected
                             subscriber that has a persistent session
                             (clean_session = False).  Duplicates are possible.

Last Will and Testament (LWT): each side registers an "offline" message with
the broker when it connects.  If the side disappears without saying goodbye,
the broker publishes it.  The robot listens for the operator's will and stops
at once - a second safety net next to the watchdog.
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Optional

import paho.mqtt.client as mqtt

from ..protocol import ProtocolError, decode, encode
from .base import ClientTransport, Message, OnMessage, ServerTransport

log = logging.getLogger(__name__)


def topics(robot_id: str) -> dict:
    base = f"teleop/{robot_id}"
    return {"cmd": base + "/cmd", "telem": base + "/telem", "event": base + "/event",
            "status": base + "/status", "operator": base + "/operator"}


class _MqttBase:
    """Shared paho set-up for both sides."""

    def __init__(self, role: str, host: str, port: int, robot_id: str, qos: int,
                 keepalive: int, client_id: Optional[str], nodelay: bool = True):
        if qos not in (0, 1):
            raise ValueError("qos must be 0 or 1")
        self.host, self.port, self.qos, self.keepalive = host, port, qos, keepalive
        self.nodelay = nodelay
        self.t = topics(robot_id)
        self.role = role
        # Persistent session only for QoS 1, so the broker queues messages while we are away.
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=client_id or f"{role}-{robot_id}",
                                  clean_session=(qos == 0),
                                  protocol=mqtt.MQTTv311)
        self.client.reconnect_delay_set(min_delay=0.2, max_delay=1)
        self.client.max_queued_messages_set(1000)
        self._connected = threading.Event()
        self.reconnects = -1     # first connect is not a reconnect
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_mqtt_message

    def _start(self, timeout: float) -> None:
        try:
            self.client.connect(self.host, self.port, keepalive=self.keepalive)
        except OSError as exc:
            raise ConnectionError(f"cannot reach MQTT broker at {self.host}:{self.port}: {exc}") from None
        self.client.loop_start()
        if not self._connected.wait(timeout):
            self.client.loop_stop()
            raise ConnectionError(f"MQTT broker at {self.host}:{self.port} did not accept the connection")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("MQTT connect refused: %s", reason_code)
            return
        self.reconnects += 1
        if self.nodelay:
            # paho does not switch off Nagle's algorithm.  With Nagle on, a QoS 1
            # PUBLISH waiting behind an un-ACKed packet is held back ~40 ms by the
            # peer's delayed-ACK timer (measured in docs/MQTT_SETUP.md).
            sock = client.socket()
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._subscribe()
        self._connected.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._connected.clear()
        log.info("MQTT %s disconnected (%s)", self.role, reason_code)

    def _on_mqtt_message(self, client, userdata, msg):
        raise NotImplementedError

    def _publish(self, topic: str, msg: Message) -> bool:
        info = self.client.publish(topic, encode(msg), qos=self.qos)
        # QoS 1 messages are kept by paho and resent after reconnect, so they
        # count as "queued" even when the link is down.  QoS 0 is simply lost.
        return self.qos == 1 or info.rc == mqtt.MQTT_ERR_SUCCESS

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def close(self) -> None:
        try:
            self._say_goodbye()
            self.client.disconnect()
        finally:
            self.client.loop_stop()

    def _say_goodbye(self) -> None:
        pass


class MqttServer(_MqttBase, ServerTransport):
    """Robot side."""

    name = "mqtt"

    def __init__(self, host: str = "127.0.0.1", port: int = 1883, robot_id: str = "p3dx",
                 qos: int = 1, keepalive: int = 5, client_id: Optional[str] = None,
                 nodelay: bool = True):
        super().__init__("robot", host, port, robot_id, qos, keepalive, client_id, nodelay)
        self.client.will_set(self.t["status"], b"offline", qos=1, retain=True)

    def start(self, on_message: OnMessage, timeout: float = 5.0) -> None:
        self._on_message = on_message
        self._start(timeout)

    def _subscribe(self) -> None:
        self.client.subscribe([(self.t["cmd"], self.qos), (self.t["operator"], 1)])
        self.client.publish(self.t["status"], b"online", qos=1, retain=True)

    def _on_mqtt_message(self, client, userdata, msg):
        if msg.topic == self.t["operator"]:
            # Operator's Last Will (or its "online" note) -> pseudo-message for the server.
            self._on_message({"type": "operator_status", "online": msg.payload == b"online"})
            return
        try:
            self._on_message(decode(msg.payload))
        except ProtocolError as exc:
            log.warning("bad message ignored: %s", exc)

    def send(self, msg: Message) -> bool:
        topic = self.t["telem"] if msg.get("type") == "telem" else self.t["event"]
        return self._publish(topic, msg)

    def _say_goodbye(self) -> None:
        self.client.publish(self.t["status"], b"offline", qos=1, retain=True)


class MqttClient(_MqttBase, ClientTransport):
    """Operator side."""

    name = "mqtt"

    def __init__(self, host: str = "127.0.0.1", port: int = 1883, robot_id: str = "p3dx",
                 qos: int = 1, keepalive: int = 5, client_id: Optional[str] = None,
                 nodelay: bool = True):
        super().__init__("operator", host, port, robot_id, qos, keepalive, client_id, nodelay)
        self.client.will_set(self.t["operator"], b"offline", qos=1, retain=True)
        self.robot_online: Optional[bool] = None

    def connect(self, on_message: OnMessage, timeout: float = 5.0) -> None:
        self._on_message = on_message
        self._start(timeout)

    def _subscribe(self) -> None:
        self.client.subscribe([(self.t["telem"], self.qos), (self.t["event"], self.qos),
                               (self.t["status"], 1)])
        self.client.publish(self.t["operator"], b"online", qos=1, retain=True)

    def _on_mqtt_message(self, client, userdata, msg):
        if msg.topic == self.t["status"]:
            self.robot_online = msg.payload == b"online"
            return
        try:
            self._on_message(decode(msg.payload))
        except ProtocolError as exc:
            log.warning("bad message ignored: %s", exc)

    def send(self, msg: Message) -> bool:
        return self._publish(self.t["cmd"], msg)

    def _say_goodbye(self) -> None:
        self.client.publish(self.t["operator"], b"offline", qos=1, retain=True)
