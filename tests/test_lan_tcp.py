from __future__ import annotations

import asyncio

import pytest

from connections import LANTCPConnection


async def _open_client(conn: LANTCPConnection):
    port = conn._server.sockets[0].getsockname()[1]
    return await asyncio.open_connection("127.0.0.1", port)


@pytest.fixture
async def conn():
    # Port 0: the OS picks a free port, so tests never collide with a
    # running reader (live one listens on 5001).
    c = LANTCPConnection(listen_port=0, listen_host="127.0.0.1")
    await c.connect()
    yield c
    await c.disconnect()


async def test_yields_stripped_lines(conn):
    _, writer = await _open_client(conn)
    gen = conn.read_lines()

    writer.write(b"  line one  \nline two\n")
    await writer.drain()

    assert await asyncio.wait_for(anext(gen), 2) == "line one"
    assert await asyncio.wait_for(anext(gen), 2) == "line two"
    writer.close()
    await writer.wait_closed()


async def test_buffers_partial_lines(conn):
    _, writer = await _open_client(conn)
    gen = conn.read_lines()

    writer.write(b"05-Jul-26 10:15:00  98  7")
    await writer.drain()
    await asyncio.sleep(0.05)  # let the fragment land without a newline
    writer.write(b"2  120\n")
    await writer.drain()

    line = await asyncio.wait_for(anext(gen), 2)
    assert line == "05-Jul-26 10:15:00  98  72  120"
    writer.close()
    await writer.wait_closed()


async def test_skips_blank_lines(conn):
    _, writer = await _open_client(conn)
    gen = conn.read_lines()

    writer.write(b"\n   \nreal\n")
    await writer.drain()

    assert await asyncio.wait_for(anext(gen), 2) == "real"
    writer.close()
    await writer.wait_closed()


async def test_survives_device_reconnect(conn):
    gen = conn.read_lines()

    _, w1 = await _open_client(conn)
    w1.write(b"first\n")
    await w1.drain()
    assert await asyncio.wait_for(anext(gen), 2) == "first"

    # Device drops (power cut) and comes back — same generator keeps going
    w1.close()
    await w1.wait_closed()
    await asyncio.sleep(0.1)

    _, w2 = await _open_client(conn)
    w2.write(b"second\n")
    await w2.drain()
    assert await asyncio.wait_for(anext(gen), 2) == "second"
    w2.close()
    await w2.wait_closed()


async def test_new_connection_replaces_stale(conn):
    # Device reboots and reconnects while the old socket is still "open"
    # from the server's point of view: the new connection must win.
    gen = conn.read_lines()

    _, w1 = await _open_client(conn)
    w1.write(b"old\n")
    await w1.drain()
    assert await asyncio.wait_for(anext(gen), 2) == "old"

    _, w2 = await _open_client(conn)
    await asyncio.sleep(0.1)  # server closes the stale socket
    w2.write(b"new\n")
    await w2.drain()
    assert await asyncio.wait_for(anext(gen), 2) == "new"
    w2.close()
    await w2.wait_closed()
