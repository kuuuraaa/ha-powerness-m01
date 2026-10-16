"""Find Tuya devices on the LAN via their UDP broadcasts.

Broadcast format and key as documented by tinytuya
(https://github.com/jasonacox/tinytuya).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import socket
import struct
from typing import Any

from .protocol import HEADER_LEN, PREFIX, AESCipher

_LOGGER = logging.getLogger(__name__)

PORTS = (6666, 6667)
UDP_KEY = hashlib.md5(b"yGAdlopoPVldABfn").digest()
DISCOVERY_TIMEOUT = 12


def decode_broadcast(data: bytes) -> dict[str, Any] | None:
    """Decode a single 0x55AA broadcast datagram."""
    if len(data) < HEADER_LEN + 8 or struct.unpack(">I", data[:4])[0] != PREFIX:
        return None
    length = struct.unpack(">I", data[12:16])[0]
    payload = data[HEADER_LEN : HEADER_LEN + length - 8]
    if len(payload) % 16 == 4:
        payload = payload[4:]
    candidates = [payload]
    if payload and len(payload) % 16 == 0:
        candidates.insert(0, AESCipher(UDP_KEY).decrypt(payload))
    for raw in candidates:
        try:
            info = json.loads(raw.decode())
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(info, dict) and "gwId" in info:
            return info
    return None


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, found: dict[str, dict[str, Any]], wanted: str | None) -> None:
        self.found = found
        self.wanted = wanted
        self.done = asyncio.Event()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        info = decode_broadcast(data)
        if info is None:
            return
        info.setdefault("ip", addr[0])
        self.found[info["gwId"]] = info
        if self.wanted and info["gwId"] == self.wanted:
            self.done.set()


def _socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        # Other Tuya integrations may listen on the same ports
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", port))
        sock.setblocking(False)
    except OSError:
        sock.close()
        raise
    return sock


async def async_discover(
    device_id: str | None = None, timeout: float = DISCOVERY_TIMEOUT
) -> dict[str, dict[str, Any]]:
    """Listen for broadcasts; stop early once ``device_id`` was seen."""
    loop = asyncio.get_running_loop()
    found: dict[str, dict[str, Any]] = {}
    proto = _Protocol(found, device_id)
    transports = []
    for port in PORTS:
        try:
            transport, _ = await loop.create_datagram_endpoint(lambda: proto, sock=_socket(port))
        except OSError as err:
            _LOGGER.debug("Cannot listen on UDP %s: %s", port, err)
            continue
        transports.append(transport)
    try:
        if transports:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proto.done.wait(), timeout)
    finally:
        for transport in transports:
            transport.close()
    return found
