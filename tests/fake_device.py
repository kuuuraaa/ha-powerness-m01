"""A fake Tuya 3.4 battery speaking the device side of the protocol."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from typing import Any

from custom_components.powerness.protocol import AESCipher, Frame, pack_frame, unpack_frames

from .const import DC_DATA_CHARGING, LOCAL_KEY, STATUS_DPS

RETCODE = b"\x00\x00\x00\x00"


def _next_frame(buffer: bytearray, key: bytes) -> Frame | None:
    """Take one frame; the key can change between two frames of one read."""
    while len(buffer) >= 16:
        total = 16 + int.from_bytes(buffer[12:16])
        if len(buffer) < total:
            return None
        chunk = bytearray(buffer[:total])
        del buffer[:total]
        if frames := unpack_frames(chunk, key):
            return frames[0]
    return None


class FakeBattery:
    """Serves one client at a time on localhost."""

    def __init__(self, local_key: str = LOCAL_KEY) -> None:
        self.real_key = local_key.encode()
        # Like the real battery: the schedule is not part of the full query
        self.query_omit = {"103"}
        self.answer_updatedps = True
        self.dps: dict[str, Any] = dict(STATUS_DPS)
        self.received: list[dict[str, Any]] = []
        self.server: asyncio.Server | None = None
        self.port = 0
        self.writers: list[asyncio.StreamWriter] = []

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for writer in self.writers:
            writer.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.append(writer)
        key = self.real_key
        local_nonce = remote_nonce = b""
        buffer = bytearray()

        def send(cmd: int, payload: bytes, seq: int = 0) -> None:
            writer.write(pack_frame(seq, cmd, payload, key))

        def push(dps: dict[str, Any]) -> None:
            body = json.dumps({"protocol": 4, "t": 1, "data": {"dps": dps}}).encode()
            send(0x08, AESCipher(key).encrypt(b"3.4" + b"\x00" * 12 + body))

        try:
            while chunk := await reader.read(4096):
                buffer.extend(chunk)
                while (frame := _next_frame(buffer, key)) is not None:
                    payload = AESCipher(key).decrypt(frame.payload)
                    if frame.cmd == 0x03:
                        local_nonce = payload
                        remote_nonce = os.urandom(16)
                        sig = hmac.new(key, local_nonce, hashlib.sha256).digest()
                        send(0x04, RETCODE + AESCipher(key).encrypt(remote_nonce + sig), frame.seq)
                    elif frame.cmd == 0x05:
                        expected = hmac.new(key, remote_nonce, hashlib.sha256).digest()
                        assert payload == expected
                        xored = bytes(a ^ b for a, b in zip(local_nonce, remote_nonce, strict=True))
                        key = AESCipher(self.real_key).encrypt(xored, pad=False)
                    elif frame.cmd == 0x10:
                        dps = {k: v for k, v in self.dps.items() if k not in self.query_omit}
                        body = json.dumps({"dps": dps}).encode()
                        send(0x10, RETCODE + AESCipher(key).encrypt(body), frame.seq)
                    elif frame.cmd == 0x12:
                        wanted = json.loads(payload)["dpId"]
                        self.received.append({"updatedps": wanted})
                        if self.answer_updatedps:
                            push(
                                {str(dp): self.dps[str(dp)] for dp in wanted if str(dp) in self.dps}
                            )
                    elif frame.cmd == 0x09:
                        send(0x09, RETCODE, frame.seq)
                    elif frame.cmd == 0x0D:
                        assert payload[:3] == b"3.4"
                        msg = json.loads(payload[15:])
                        dps = msg["data"]["dps"]
                        self.received.append(dps)
                        send(0x0D, RETCODE, frame.seq)
                        if "1" in dps:
                            dps = {"10": DC_DATA_CHARGING}
                        self.dps.update(dps)
                        push(dps)
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
