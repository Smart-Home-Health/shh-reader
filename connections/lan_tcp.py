from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from .base import BaseConnection

log = logging.getLogger(__name__)


class LANTCPConnection(BaseConnection):

    def __init__(self, listen_port: int = 5001, listen_host: str = "0.0.0.0"):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self._server: asyncio.Server | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._stop = False
        self._client_connected = asyncio.Event()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        if self._writer is not None:
            log.info(
                "LAN: device reconnected from %s — replacing stale connection", peer
            )
            old_writer = self._writer
            try:
                old_writer.close()
                await old_writer.wait_closed()
            except Exception:
                pass
        else:
            log.info("LAN: device connected from %s", peer)
        self._reader = reader
        self._writer = writer
        self._client_connected.set()

    async def connect(self) -> None:
        self._stop = False
        self._client_connected.clear()
        self._server = await asyncio.start_server(
            self._handle_client, self.listen_host, self.listen_port
        )
        await self._server.start_serving()
        log.info("LAN: TCP server listening on %s:%s", self.listen_host, self.listen_port)

    async def disconnect(self) -> None:
        self._stop = True
        if self._writer:
            peer = self._writer.get_extra_info("peername")
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            log.info("LAN: closed connection to %s", peer)
        self._reader = None
        self._writer = None
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            log.info("LAN: TCP server stopped")

    async def read_lines(self) -> AsyncGenerator[str, None]:
        while not self._stop:
            self._client_connected.clear()
            if self._reader is None:
                log.info("LAN: waiting for device to connect…")
                try:
                    await self._client_connected.wait()
                except asyncio.CancelledError:
                    log.info("LAN: cancelled while waiting for device")
                    return

            assert self._reader is not None
            reader = self._reader          # local ref for this session
            log.info("LAN: reading data stream")
            buffer = ""
            while not self._stop:
                try:
                    data = await reader.read(4096)
                except asyncio.CancelledError:
                    log.info("LAN: read cancelled")
                    return
                except ConnectionError as e:
                    log.warning("LAN: connection error: %s", e)
                    break
                if not data:
                    log.info("LAN: device disconnected (EOF)")
                    break
                buffer += data.decode(errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    stripped = line.strip()
                    if stripped:
                        yield stripped

            # only clear state if no new connection has already replaced ours
            if self._reader is reader:
                self._reader = None
                self._writer = None
            log.info("LAN: waiting for device to reconnect…")
        log.info("LAN: read_lines loop ended")
