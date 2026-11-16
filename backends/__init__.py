"""Robot backends: `mock` (pure Python) and `coppelia` (CoppeliaSim ZMQ Remote API)."""

from .base import RobotBackend
from .mock import MockBackend, World


def make_backend(name: str, **kwargs) -> RobotBackend:
    """Factory used by the server's --backend option."""
    if name == "mock":
        return MockBackend(**kwargs)
    if name in ("coppelia", "coppeliasim"):
        from .coppelia import CoppeliaBackend  # imported lazily: needs the zmq client
        return CoppeliaBackend(**kwargs)
    raise ValueError(f"unknown backend {name!r} (use 'mock' or 'coppelia')")


__all__ = ["RobotBackend", "MockBackend", "World", "make_backend"]
