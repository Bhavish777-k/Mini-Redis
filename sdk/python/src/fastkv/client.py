"""Synchronous, dependency-free Fast-KV client for its v1 line protocol.

Each command uses one socket.  The server is the source of truth for routing,
replication, and expiration. No automatic retries on a failed/ambiguous write.
"""
from __future__ import annotations

import socket
from typing import Optional, Union

_MAX_LINE = 1024 * 1024


class FastKVError(Exception):
    """Base exception for Fast-KV client failures."""


class FastKVCommandError(FastKVError):
    """The router replied with ERR ..."""


class FastKVConnectionError(FastKVError):
    """Connection, timeout, or send/receive failed; write outcome may be unknown."""


class FastKVProtocolError(FastKVError):
    """The router reply did not follow the supported line protocol."""


def _token(value: Union[str, int], *, name: str) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise TypeError(f"{name} must be a string or integer")
    text = str(value)
    if not text or any(char.isspace() or char == "\x00" for char in text):
        raise ValueError(f"{name} must be a nonempty token without whitespace or NUL")
    return text


def _integer(reply: str, name: str) -> int:
    try:
        return int(reply)
    except ValueError as exc:
        raise FastKVProtocolError(f"Invalid {name} reply: {reply!r}") from exc


class FastKV:
    """Use one router endpoint; callers do not need to know shard ports.

    Example:
        db = FastKV("127.0.0.1", port=7001)
        db.set("session:1", "active", ttl=30)
        assert db.get("session:1") == "active"
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7001,
                 timeout: float = 3.0):
        if not isinstance(host, str) or not host:
            raise ValueError("host must be nonempty")
        if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
            raise ValueError("port must be between 1 and 65535")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self.host, self.port, self.timeout = host, port, float(timeout)

    def command(self, command: str) -> str:
        """Execute one raw router command; handles errors but not quoting.

        Do not pass untrusted strings here; prefer typed methods below.
        """
        if not isinstance(command, str) or not command or any(c in command for c in "\r\n\x00"):
            raise ValueError("command must be one nonempty line")
        payload = (command + "\n").encode("utf-8")
        if len(payload) > _MAX_LINE:
            raise ValueError("command exceeds router's 1 MiB request limit")
        try:
            with socket.create_connection((self.host, self.port), self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.sendall(payload)
                data = bytearray()
                while True:
                    chunk = sock.recv(8192)
                    if not chunk:
                        raise FastKVProtocolError("router closed connection before newline reply")
                    end = chunk.find(b"\n")
                    if end >= 0:
                        data.extend(chunk[:end])
                        break
                    data.extend(chunk)
                    if len(data) > _MAX_LINE:
                        raise FastKVProtocolError("router reply exceeds 1 MiB")
                if len(data) > _MAX_LINE:
                    raise FastKVProtocolError("router reply exceeds 1 MiB")
        except (OSError, TimeoutError) as exc:
            raise FastKVConnectionError(
                f"Cannot complete command at {self.host}:{self.port}: {exc}. "
                "If this was a write, its outcome is unknown; do not blindly retry."
            ) from exc
        try:
            answer = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FastKVProtocolError("router reply is not UTF-8") from exc
        if answer.startswith("ERR ") or answer == "ERR":
            raise FastKVCommandError(answer)
        return answer

    def ping(self) -> bool:
        response = self.command("PING")
        if response != "PONG":
            raise FastKVProtocolError(f"Expected PONG, got {response!r}")
        return True

    def set(self, key: Union[str, int], value: Union[str, int], *,
            ttl: Optional[int] = None) -> bool:
        k, v = _token(key, name="key"), _token(value, name="value")
        if ttl is not None and (not isinstance(ttl, int) or isinstance(ttl, bool)
                                or not 0 <= ttl <= 3153600000):
            raise ValueError("ttl must be an integer between 0 and 3153600000")
        response = self.command(f"SET {k} {v}")
        if response != "OK":
            raise FastKVProtocolError(f"Expected OK from SET, got {response!r}")
        if ttl is not None:
            # Not atomic in the current router protocol. If EXPIRE fails, SET may persist.
            if not self.expire(k, ttl):
                raise FastKVProtocolError("SET succeeded but EXPIRE did not set the TTL")
        return True

    def get(self, key: Union[str, int]) -> Optional[str]:
        result = self.command(f"GET {_token(key, name='key')}")
        return None if result == "(nil)" else result

    def delete(self, key: Union[str, int]) -> bool:
        return self._bool("DEL", key)

    def exists(self, key: Union[str, int]) -> bool:
        return self._bool("EXISTS", key)

    def expire(self, key: Union[str, int], seconds: int) -> bool:
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 0 <= seconds <= 3153600000:
            raise ValueError("seconds must be integer between 0 and 3153600000")
        return self._bool("EXPIRE", key, str(seconds))

    def persist(self, key: Union[str, int]) -> bool:
        return self._bool("PERSIST", key)

    def incr(self, key: Union[str, int]) -> int:
        return _integer(self.command(f"INCR {_token(key, name='key')}"), "INCR")

    def ttl(self, key: Union[str, int]) -> int:
        """Seconds remaining, -1 for no expiry, -2 for missing/expired key."""
        return _integer(self.command(f"TTL {_token(key, name='key')}"), "TTL")

    def where(self, key: Union[str, int]) -> Optional[int]:
        result = self.command(f"WHERE {_token(key, name='key')}")
        return None if result == "(nil)" else _integer(result, "WHERE")

    def count(self) -> int:
        return _integer(self.command("COUNT"), "COUNT")

    def cluster_status(self) -> str:
        return self.command("CLUSTER STATUS")

    def os_stats(self) -> str:
        return self.command("OSSTATS")

    def alloc_stats(self) -> str:
        return self.command("ALLOCSTATS")

    def _bool(self, op: str, key: Union[str, int], argument: Optional[str] = None) -> bool:
        cmd = f"{op} {_token(key, name='key')}"
        if argument is not None:
            cmd += f" {argument}"
        reply = self.command(cmd)
        if reply not in ("0", "1"):
            raise FastKVProtocolError(f"Expected 0 or 1 from {op}, got {reply!r}")
        return reply == "1"
