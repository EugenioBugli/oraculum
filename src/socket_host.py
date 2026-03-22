"""UDP socket host — serialises and sends GameStateMsg packets.

Counterpart to socket_client.py (receiver).

Usage::

    host = UDPSender("127.0.0.1", 10006)
    host.send(msg)          # fire-and-forget, non-blocking
    host.close()

Or as a context manager::

    with UDPSender("127.0.0.1", 10006) as host:
        host.send(msg)
"""

import json
import socket

from .socket_client import GameStateMsg


class UDPSender:
    def __init__(self, host: str, port: int) -> None:
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, msg: GameStateMsg) -> None:
        """Serialise *msg* to JSON and send it as a single UDP datagram."""
        data = json.dumps(msg.to_dict()).encode()
        self._sock.sendto(data, self._addr)

    def close(self) -> None:
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
