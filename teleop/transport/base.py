"""Transport interface: how messages get between operator and robot.

The rest of the code never imports socket or paho directly; it uses these two
small interfaces, so TCP and MQTT are interchangeable with one command-line
flag (--transport tcp|mqtt).
"""

from __future__ import annotations

import abc
from typing import Any, Callable, Dict

Message = Dict[str, Any]
OnMessage = Callable[[Message], None]


class ServerTransport(abc.ABC):
    """Robot side.  Receives commands, sends acks/results/telemetry."""

    name = "base"

    @abc.abstractmethod
    def start(self, on_message: OnMessage) -> None:
        """Start listening; on_message is called from a background thread."""

    @abc.abstractmethod
    def send(self, msg: Message) -> bool:
        """Send to the operator.  Returns False if it could not be sent/queued."""

    @abc.abstractmethod
    def close(self) -> None: ...

    @property
    @abc.abstractmethod
    def connected(self) -> bool: ...


class ClientTransport(abc.ABC):
    """Operator side.  Sends commands, receives everything else."""

    name = "base"

    @abc.abstractmethod
    def connect(self, on_message: OnMessage, timeout: float = 5.0) -> None:
        """Connect (blocking up to timeout).  Raises ConnectionError on failure."""

    @abc.abstractmethod
    def send(self, msg: Message) -> bool: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @property
    @abc.abstractmethod
    def connected(self) -> bool: ...
