"""Minimal asyncio client for the Tuya local protocol (3.3 and 3.4).

Own implementation, written from the protocol details documented by tinytuya
(https://github.com/jasonacox/tinytuya) and LocalTuya
(https://github.com/rospogrigio/localtuya).
"""

from __future__ import annotations

import asyncio
import binascii
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import os
import struct
import time
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

PORT = 6668
PREFIX = 0x000055AA
SUFFIX = 0x0000AA55
HEADER_FMT = ">4I"
HEADER_LEN = 16

CMD_SESS_KEY_NEG_START = 0x03
CMD_SESS_KEY_NEG_RESP = 0x04
CMD_SESS_KEY_NEG_FINISH = 0x05
CMD_CONTROL = 0x07
CMD_STATUS = 0x08
CMD_HEART_BEAT = 0x09
CMD_DP_QUERY = 0x0A
CMD_CONTROL_NEW = 0x0D
CMD_DP_QUERY_NEW = 0x10
CMD_UPDATEDPS = 0x12

# Commands whose payload is sent without the "3.x" version header
NO_VERSION_HEADER = {
    CMD_DP_QUERY,
    CMD_DP_QUERY_NEW,
    CMD_HEART_BEAT,
    CMD_UPDATEDPS,
    CMD_SESS_KEY_NEG_START,
    CMD_SESS_KEY_NEG_RESP,
    CMD_SESS_KEY_NEG_FINISH,
}

CONNECT_TIMEOUT = 5
RESPONSE_TIMEOUT = 5
HEARTBEAT_INTERVAL = 10


class TuyaError(Exception):
    """Base error of the local client."""


class TuyaConnectionError(TuyaError):
    """The device could not be reached or the connection dropped."""


class TuyaAuthError(TuyaError):
    """The device rejected the local key."""


@dataclass(slots=True)
class Frame:
    """A decoded protocol frame."""

    seq: int
    cmd: int
    payload: bytes


class AESCipher:
    """AES-128-ECB with PKCS#7 padding, as used by Tuya."""

    def __init__(self, key: bytes) -> None:
        """Initialize with a 16 byte key."""
        self._cipher = Cipher(algorithms.AES(key), modes.ECB())

    def encrypt(self, data: bytes, pad: bool = True) -> bytes:
        """Encrypt data."""
        if pad:
            n = 16 - len(data) % 16
            data += bytes([n]) * n
        enc = self._cipher.encryptor()
        return enc.update(data) + enc.finalize()

    def decrypt(self, data: bytes, unpad: bool = True) -> bytes:
        """Decrypt data."""
        dec = self._cipher.decryptor()
        raw = dec.update(data) + dec.finalize()
        if unpad and raw:
            n = raw[-1]
            if 0 < n <= 16 and raw.endswith(bytes([n]) * n):
                raw = raw[:-n]
        return raw


def pack_frame(seq: int, cmd: int, payload: bytes, hmac_key: bytes | None) -> bytes:
    """Build a 0x55AA frame, signed with HMAC (3.4) or CRC32 (3.3)."""
    tail_len = 36 if hmac_key else 8
    header = struct.pack(HEADER_FMT, PREFIX, seq, cmd, len(payload) + tail_len)
    if hmac_key:
        check = hmac.new(hmac_key, header + payload, hashlib.sha256).digest()
    else:
        check = struct.pack(">I", binascii.crc32(header + payload) & 0xFFFFFFFF)
    return header + payload + check + struct.pack(">I", SUFFIX)


def unpack_frames(buffer: bytearray, hmac_key: bytes | None) -> list[Frame]:
    """Consume all complete frames from ``buffer``."""
    frames = []
    tail_len = 36 if hmac_key else 8
    prefix = struct.pack(">I", PREFIX)
    while True:
        start = buffer.find(prefix)
        if start < 0:
            # Keep a few bytes, the prefix could be split across reads
            del buffer[: max(0, len(buffer) - 3)]
            return frames
        if start:
            del buffer[:start]
        if len(buffer) < HEADER_LEN:
            return frames
        _, seq, cmd, length = struct.unpack(HEADER_FMT, buffer[:HEADER_LEN])
        if length > 0x10000:
            del buffer[:4]
            continue
        if len(buffer) < HEADER_LEN + length:
            return frames
        raw = bytes(buffer[: HEADER_LEN + length])
        del buffer[: HEADER_LEN + length]
        if length < tail_len:
            continue
        payload = raw[HEADER_LEN : HEADER_LEN + length - tail_len]
        if hmac_key:
            expected = hmac.new(hmac_key, raw[:-tail_len], hashlib.sha256).digest()
            if not hmac.compare_digest(expected, raw[-tail_len:-4]):
                _LOGGER.debug("Dropping frame cmd=%s with invalid HMAC", cmd)
                continue
        frames.append(Frame(seq, cmd, payload))


class TuyaDevice:
    """Persistent local connection to a single Tuya device."""

    def __init__(
        self,
        host: str,
        device_id: str,
        local_key: str,
        version: str = "3.4",
        on_status: Callable[[dict[str, Any]], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        port: int = PORT,
    ) -> None:
        """Initialize the client."""
        self.host = host
        self.port = port
        self.device_id = device_id
        self.version = version
        self._real_key = local_key.encode("latin1")
        self._key = self._real_key
        self._on_status = on_status
        self._on_disconnect = on_disconnect
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._tasks: list[asyncio.Task] = []
        self._waiters: dict[int, asyncio.Future[Frame]] = {}
        self._seq = 0
        self._buffer = bytearray()

    @property
    def is_v34(self) -> bool:
        """Return True when the 3.4 protocol is used."""
        return self.version == "3.4"

    @property
    def connected(self) -> bool:
        """Return True while the TCP connection is up."""
        return self._writer is not None and not self._writer.is_closing()

    @property
    def _hmac_key(self) -> bytes | None:
        return self._key if self.is_v34 else None

    async def connect(self) -> None:
        """Open the connection and negotiate the session key."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
            )
        except (OSError, TimeoutError) as err:
            raise TuyaConnectionError(f"Cannot connect to {self.host}: {err}") from err
        self._key = self._real_key
        self._buffer.clear()
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._read_loop())]
        try:
            if self.is_v34:
                await self._negotiate_session_key()
        except BaseException:
            await self.close()
            raise
        self._tasks.append(loop.create_task(self._heartbeat_loop()))

    async def close(self) -> None:
        """Close the connection."""
        current = asyncio.current_task()
        for task in self._tasks:
            if task is not current:
                task.cancel()
        self._tasks = []
        for fut in self._waiters.values():
            if not fut.done():
                fut.set_exception(TuyaConnectionError("Connection closed"))
        self._waiters.clear()
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()
        self._writer = None
        self._reader = None

    async def query(self) -> dict[str, Any]:
        """Request all data points."""
        cmd = CMD_DP_QUERY_NEW if self.is_v34 else CMD_DP_QUERY
        now = str(int(time.time()))
        payload = {"gwId": self.device_id, "devId": self.device_id, "uid": self.device_id, "t": now}
        frame = await self._request(cmd, payload, (cmd, CMD_STATUS))
        data = self._decode(frame.payload)
        return _extract_dps(data)

    async def set_dps(self, dps: dict[str, Any]) -> None:
        """Write data points."""
        if self.is_v34:
            payload: dict[str, Any] = {
                "protocol": 5,
                "t": int(time.time()),
                "data": {"dps": dps},
            }
            cmd = CMD_CONTROL_NEW
        else:
            payload = {
                "devId": self.device_id,
                "uid": self.device_id,
                "t": str(int(time.time())),
                "dps": dps,
            }
            cmd = CMD_CONTROL
        await self._request(cmd, payload, (cmd,))

    async def request_dps(self, dps: list[int]) -> None:
        """Ask the device to report data points the full query leaves out.

        The answer arrives as normal status pushes, so nothing is awaited.
        """
        await self._send(CMD_UPDATEDPS, self._encode(CMD_UPDATEDPS, {"dpId": dps}))

    async def heartbeat(self) -> None:
        """Send a heartbeat and wait for the answer."""
        payload = {} if self.is_v34 else {"gwId": self.device_id, "devId": self.device_id}
        await self._request(CMD_HEART_BEAT, payload, (CMD_HEART_BEAT,))

    async def _negotiate_session_key(self) -> None:
        local_nonce = os.urandom(16)
        cipher = AESCipher(self._real_key)
        try:
            frame = await self._request_raw(
                CMD_SESS_KEY_NEG_START,
                cipher.encrypt(local_nonce),
                (CMD_SESS_KEY_NEG_RESP,),
            )
        except TuyaConnectionError as err:
            # Devices silently drop handshakes signed with a wrong key
            raise TuyaAuthError(
                "No handshake answer, check local key and protocol version"
            ) from err
        payload = _strip_retcode(frame.payload)
        resp = cipher.decrypt(payload)
        if len(resp) < 48:
            raise TuyaAuthError("Invalid session key response")
        remote_nonce, remote_hmac = resp[:16], resp[16:48]
        expected = hmac.new(self._real_key, local_nonce, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, remote_hmac):
            raise TuyaAuthError("Local key rejected by device")
        finish = hmac.new(self._real_key, remote_nonce, hashlib.sha256).digest()
        await self._send(CMD_SESS_KEY_NEG_FINISH, cipher.encrypt(finish))
        xored = bytes(a ^ b for a, b in zip(local_nonce, remote_nonce, strict=True))
        self._key = cipher.encrypt(xored, pad=False)

    async def _request(self, cmd: int, payload: dict[str, Any], expect: tuple[int, ...]) -> Frame:
        return await self._request_raw(cmd, self._encode(cmd, payload), expect)

    async def _request_raw(self, cmd: int, payload: bytes, expect: tuple[int, ...]) -> Frame:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Frame] = loop.create_future()
        for code in expect:
            self._waiters[code] = fut
        try:
            await self._send(cmd, payload)
            return await asyncio.wait_for(fut, RESPONSE_TIMEOUT)
        except TimeoutError as err:
            raise TuyaConnectionError(f"No answer to command {cmd:#x}") from err
        finally:
            for code in expect:
                if self._waiters.get(code) is fut:
                    del self._waiters[code]

    async def _send(self, cmd: int, payload: bytes) -> None:
        if not self.connected:
            raise TuyaConnectionError("Not connected")
        assert self._writer is not None
        self._seq += 1
        self._writer.write(pack_frame(self._seq, cmd, payload, self._hmac_key))
        try:
            await self._writer.drain()
        except OSError as err:
            raise TuyaConnectionError(str(err)) from err

    def _encode(self, cmd: int, payload: dict[str, Any]) -> bytes:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        header = self.version.encode() + b"\x00" * 12
        cipher = AESCipher(self._key)
        if self.is_v34:
            if cmd not in NO_VERSION_HEADER:
                raw = header + raw
            return cipher.encrypt(raw)
        enc = cipher.encrypt(raw)
        return enc if cmd in NO_VERSION_HEADER else header + enc

    def _decode(self, payload: bytes) -> Any:
        payload = _strip_retcode(payload)
        if payload[:3] == self.version.encode():
            payload = payload[15:]
        if payload and len(payload) % 16 == 0:
            payload = AESCipher(self._key).decrypt(payload)
            if payload[:3] == self.version.encode():
                payload = payload[15:]
        if not payload:
            return None
        try:
            return json.loads(payload.decode())
        except (UnicodeDecodeError, ValueError):
            _LOGGER.debug("Undecodable payload: %s", payload)
            return None

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                chunk = await self._reader.read(4096)
                if not chunk:
                    raise TuyaConnectionError("Connection closed by device")
                self._buffer.extend(chunk)
                for frame in unpack_frames(self._buffer, self._hmac_key):
                    self._handle_frame(frame)
        except asyncio.CancelledError:
            raise
        except (OSError, TuyaError) as err:
            _LOGGER.debug("Connection to %s lost: %s", self.host, err)
        await self.close()
        if self._on_disconnect:
            self._on_disconnect()

    def _handle_frame(self, frame: Frame) -> None:
        fut = self._waiters.get(frame.cmd)
        if frame.cmd in (CMD_SESS_KEY_NEG_RESP, CMD_HEART_BEAT):
            if fut and not fut.done():
                fut.set_result(frame)
            return
        if fut and not fut.done():
            # The requester decodes the answer itself
            fut.set_result(frame)
            return
        dps = _extract_dps(self._decode(frame.payload))
        if dps and self._on_status:
            self._on_status(dps)

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await self.heartbeat()
            except TuyaError as err:
                _LOGGER.debug("Heartbeat to %s failed: %s", self.host, err)
                await self.close()
                if self._on_disconnect:
                    self._on_disconnect()
                return


def _strip_retcode(payload: bytes) -> bytes:
    """Remove the 4 byte return code the device puts in front of answers."""
    if len(payload) >= 4 and payload[:3] == b"\x00\x00\x00" and len(payload) % 16 in (3, 4):
        return payload[4:]
    return payload


def _extract_dps(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("dps"), dict):
        return data["dps"]
    inner = data.get("data")
    if isinstance(inner, dict) and isinstance(inner.get("dps"), dict):
        return inner["dps"]
    return {}
