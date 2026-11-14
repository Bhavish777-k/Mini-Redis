"""Fast-KV client. Connect to the router (usually 127.0.0.1:7001)."""
from .client import (
    FastKV,
    FastKVError,
    FastKVCommandError,
    FastKVConnectionError,
    FastKVProtocolError,
)

__all__ = [
    "FastKV", "FastKVError", "FastKVCommandError", "FastKVConnectionError",
    "FastKVProtocolError",
]
