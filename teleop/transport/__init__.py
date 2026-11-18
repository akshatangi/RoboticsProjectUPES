"""Transports.  `make_server` / `make_client` pick TCP or MQTT from a name."""

from __future__ import annotations

from .base import ClientTransport, ServerTransport


def make_server(kind: str, host: str, port: int, robot_id: str = "p3dx", qos: int = 1,
                keepalive: int = 5) -> ServerTransport:
    if kind == "tcp":
        from .tcp import TcpServer
        return TcpServer(host, port)
    if kind == "mqtt":
        from .mqtt import MqttServer
        return MqttServer(host, port, robot_id=robot_id, qos=qos, keepalive=keepalive)
    raise ValueError(f"unknown transport {kind!r} (use tcp or mqtt)")


def make_client(kind: str, host: str, port: int, robot_id: str = "p3dx", qos: int = 1,
                keepalive: int = 5) -> ClientTransport:
    if kind == "tcp":
        from .tcp import TcpClient
        return TcpClient(host, port)
    if kind == "mqtt":
        from .mqtt import MqttClient
        return MqttClient(host, port, robot_id=robot_id, qos=qos, keepalive=keepalive)
    raise ValueError(f"unknown transport {kind!r} (use tcp or mqtt)")


__all__ = ["ClientTransport", "ServerTransport", "make_server", "make_client"]
