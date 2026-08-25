# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read-only Modbus TCP frame helpers shared by runtime diagnostics."""

from __future__ import annotations

import socket
import struct

MBAP_HEADER_LENGTH = 7


def read_holding_registers(
    host: str, port: int, unit_id: int, address: int, count: int, timeout: int = 5
) -> bytes:
    """Read one holding-register response on a fresh Modbus TCP connection."""
    with socket.create_connection((host, port), timeout=timeout) as connection:
        return read_holding_registers_on_connection(connection, unit_id, address, count)


def read_holding_registers_on_connection(
    connection: socket.socket, unit_id: int, address: int, count: int
) -> bytes:
    """Send one read-only request and return its complete TCP frame."""
    request = struct.pack(">HHHBBHH", 1, 0, 6, unit_id, 3, address, count)
    connection.sendall(request)
    header = recv_exact(connection, MBAP_HEADER_LENGTH)
    _, _, response_length, _ = struct.unpack(">HHHB", header)
    if response_length < 2:
        raise RuntimeError("Invalid MBAP length")
    return header + recv_exact(connection, response_length - 1)


def recv_exact(connection: socket.socket, size: int) -> bytes:
    """Read exactly one Modbus TCP frame segment from a stream socket."""
    chunks: list[bytes] = []
    while size:
        chunk = connection.recv(size)
        if not chunk:
            raise RuntimeError("Short Modbus TCP response")
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)
