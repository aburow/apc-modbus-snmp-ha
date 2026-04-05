# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""On-demand diagnostics collector for APC devices."""

from __future__ import annotations

import asyncio
import re
import socket
import struct
from datetime import UTC, datetime
from typing import Any

from .snmp_helper import async_get_snmp_value

MBAP_HEADER_LENGTH = 7
MIN_MODBUS_RESPONSE_LENGTH = 9
MODBUS_EXCEPTION_FLAG = 0x80
INT16_SIGN_BIT = 0x8000
INT16_MODULUS = 0x10000
ASCII_PRINTABLE_START = 32
ASCII_PRINTABLE_END = 126

MODBUS_EXCEPTION_NAMES: dict[int, str] = {
    1: "Illegal Function",
    2: "Illegal Data Address",
    3: "Illegal Data Value",
    4: "Slave Device Failure",
    5: "Acknowledge",
    6: "Slave Device Busy",
    8: "Memory Parity Error",
    10: "Gateway Path Unavailable",
    11: "Gateway Target Device Failed to Respond",
}

SNMP_OIDS: dict[str, str] = {
    "sysName": "1.3.6.1.2.1.1.5.0",
    "sysDescr": "1.3.6.1.2.1.1.1.0",
    "apc_model_smartups": "1.3.6.1.4.1.318.1.1.1.1.1.1.0",
    "apc_model_rackpdu": "1.3.6.1.4.1.318.1.1.12.1.5.0",
    "apc_fw_smartups": "1.3.6.1.4.1.318.1.1.1.1.2.1.0",
    "apc_fw_rackpdu": "1.3.6.1.4.1.318.1.1.12.1.3.0",
    "apc_fw_date_smartups": "1.3.6.1.4.1.318.1.1.1.1.2.2.0",
    "apc_fw_date_rackpdu": "1.3.6.1.4.1.318.1.1.12.1.4.0",
}

MODBUS_BLOCKS: list[tuple[int, int]] = [
    (0x0000, 0x0016 - 0x0000 + 1),
    (0x0080, 0x0099 - 0x0080 + 1),
    (0x0021, 0x002A - 0x0021 + 1),
    (0x009E, 0x00A2 - 0x009E + 1),
    (0x00CF, 0x00D4 - 0x00CF + 1),
    (0x023C, 0x0250 - 0x023C + 1),
]

RUNTIME_BLOCK_KEY = "0x0080_count_26"
LEGACY_ID_BLOCK_KEY = "0x0021_count_10"
MODERN_ID_BLOCK_KEY = "0x023C_count_21"
REDACTED_IP = "[redacted-ip]"
REDACTED_COMMUNITY = "[redacted-community]"
REDACTED_SERIAL = "[redacted-serial]"
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
SERIAL_FIELD_RE = re.compile(
    r"(?i)\b(sn|serial(?:\s+number)?)\s*[:=]\s*([A-Za-z0-9._/-]+)"
)


def _modbus_read_holding_registers(
    host: str, port: int, unit_id: int, address: int, count: int, timeout: int = 5
) -> bytes:
    transaction_id = 1
    protocol_id = 0
    request_length = 6
    function_code = 3
    mbap_header = struct.pack(
        ">HHHB",
        transaction_id,
        protocol_id,
        request_length,
        unit_id,
    )
    pdu = struct.pack(">BHH", function_code, address, count)
    payload_request = mbap_header + pdu

    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.sendall(payload_request)
        header = connection.recv(MBAP_HEADER_LENGTH)
        if len(header) < MBAP_HEADER_LENGTH:
            raise RuntimeError("Short MBAP header")

        _, _, response_length, _ = struct.unpack(">HHHB", header)
        payload = connection.recv(response_length - 1)
        if len(payload) < (response_length - 1):
            raise RuntimeError("Short PDU")

        return header + payload


def _parse_modbus_response(response: bytes) -> dict[str, Any]:
    if len(response) < MIN_MODBUS_RESPONSE_LENGTH:
        return {
            "error": {
                "code": "modbus_response_too_short",
                "message": "response too short",
            }
        }

    _, _, _, unit_id = struct.unpack(">HHHB", response[:MBAP_HEADER_LENGTH])
    function_code = response[MBAP_HEADER_LENGTH]
    if function_code & MODBUS_EXCEPTION_FLAG:
        exception_code = response[MBAP_HEADER_LENGTH + 1]
        exception_name = MODBUS_EXCEPTION_NAMES.get(
            exception_code,
            "Unknown Modbus Exception",
        )
        return {
            "error": {
                "code": "modbus_exception",
                "message": f"Modbus exception {exception_code}: {exception_name}",
                "exception_code": exception_code,
                "exception_name": exception_name,
            }
        }

    byte_count = response[MBAP_HEADER_LENGTH + 1]
    data = response[
        MIN_MODBUS_RESPONSE_LENGTH : MIN_MODBUS_RESPONSE_LENGTH + byte_count
    ]
    registers = [
        struct.unpack(">H", data[index : index + 2])[0]
        for index in range(0, len(data), 2)
    ]
    return {"unit_id": unit_id, "registers": registers}


def _decode_uint32(registers: list[int], index: int) -> int | None:
    if index + 1 >= len(registers):
        return None
    return (registers[index] << 16) | registers[index + 1]


def _decode_int16(value: int) -> int:
    return value - INT16_MODULUS if value >= INT16_SIGN_BIT else value


def _decode_ascii_registers(registers: list[int]) -> str:
    chars: list[str] = []
    for register in registers:
        code_point = register & 0xFF
        if not code_point:
            continue
        if ASCII_PRINTABLE_START <= code_point <= ASCII_PRINTABLE_END:
            chars.append(chr(code_point))
    return "".join(chars).strip()


def _block_index(address: int) -> int:
    return address - 0x0080


def _scaled_register(
    registers: list[int], address: int, divisor: int, *, signed: bool = False
) -> float | None:
    index = _block_index(address)
    if len(registers) <= index:
        return None
    value = _decode_int16(registers[index]) if signed else registers[index]
    return value / divisor


def _build_quick_decode(registers: list[int]) -> dict[str, float | int | None]:
    return {
        "runtime_remaining": _decode_uint32(registers, _block_index(0x0080)),
        "soc_pct": _scaled_register(registers, 0x0082, 512),
        "batt_v_pos": _scaled_register(registers, 0x0083, 32, signed=True),
        "batt_v_neg": _scaled_register(registers, 0x0084, 32, signed=True),
        "batt_temp_c": _scaled_register(registers, 0x0087, 128, signed=True),
        "out_load_pct": _scaled_register(registers, 0x0088, 256),
        "out_current": _scaled_register(registers, 0x008C, 32),
        "out_voltage": _scaled_register(registers, 0x008E, 64),
        "out_freq": _scaled_register(registers, 0x0090, 128),
        "out_energy_wh": _decode_uint32(registers, _block_index(0x0091)),
        "in_voltage": _scaled_register(registers, 0x0097, 64),
    }


def _sanitize_text(value: str, host: str, community: str) -> str:
    """Redact sensitive strings in diagnostics output."""
    text = value
    if host:
        text = text.replace(host, REDACTED_IP)
    text = IPV4_RE.sub(REDACTED_IP, text)
    if community:
        text = text.replace(community, REDACTED_COMMUNITY)

    def _serial_replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}: {REDACTED_SERIAL}"

    return SERIAL_FIELD_RE.sub(_serial_replace, text)


def _sanitize_data(value: Any, host: str, community: str) -> Any:
    """Recursively sanitize sensitive values in diagnostics data."""
    if isinstance(value, dict):
        return {
            key: _sanitize_data(item, host, community) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_data(item, host, community) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value, host, community)
    return value


async def _collect_snmp_data(host: str, community: str) -> dict[str, Any]:
    values = await asyncio.gather(
        *(async_get_snmp_value(host, oid, community) for oid in SNMP_OIDS.values()),
        return_exceptions=True,
    )
    result: dict[str, Any] = {}
    for key, oid, value in zip(
        SNMP_OIDS.keys(), SNMP_OIDS.values(), values, strict=False
    ):
        if isinstance(value, Exception):
            result[key] = {
                "oid": oid,
                "error": {
                    "code": "snmp_exception",
                    "message": str(value),
                    "exception_type": type(value).__name__,
                },
            }
            continue
        if value is None:
            result[key] = {
                "oid": oid,
                "error": {"code": "snmp_missing", "message": "No value returned"},
            }
            continue
        result[key] = {"oid": oid, "value": value}
    return result


def _collect_modbus_block(
    host: str, port: int, unit_id: int, start: int, count: int
) -> dict[str, Any]:
    try:
        raw = _modbus_read_holding_registers(host, port, unit_id, start, count)
        parsed = _parse_modbus_response(raw)
    except (OSError, RuntimeError, struct.error) as err:
        return {
            "error": {
                "code": "modbus_block_read_failed",
                "message": str(err),
                "exception_type": type(err).__name__,
            }
        }

    return {
        "start": start,
        "count": count,
        "raw_hex": raw.hex(),
        "parsed": parsed,
    }


def _add_decodes(dump: dict[str, Any]) -> None:
    runtime_block = dump["modbus"].get(RUNTIME_BLOCK_KEY)
    if runtime_block and "parsed" in runtime_block:
        parsed = runtime_block["parsed"]
        registers = parsed.get("registers")
        if registers:
            runtime_block["quick_decode"] = _build_quick_decode(registers)

    legacy_block = dump["modbus"].get(LEGACY_ID_BLOCK_KEY)
    if legacy_block and "parsed" in legacy_block:
        registers = legacy_block["parsed"].get("registers")
        if registers:
            legacy_id = _decode_ascii_registers(registers[1:9])
            if legacy_id:
                legacy_block["identity_decode"] = {"legacy_ups_id": legacy_id}

    modern_block = dump["modbus"].get(MODERN_ID_BLOCK_KEY)
    if modern_block and "parsed" in modern_block:
        registers = modern_block["parsed"].get("registers")
        if registers:
            ascii_chunks = {
                f"0x{0x023C + index:04X}": decoded
                for index in range(0, len(registers), 8)
                if (decoded := _decode_ascii_registers(registers[index : index + 8]))
            }
            if ascii_chunks:
                modern_block["identity_decode"] = {"ascii_chunks": ascii_chunks}


def collect_diagnostic_dump(
    host: str, community: str, port: int, unit_id: int
) -> dict[str, Any]:
    """Collect SNMP and Modbus diagnostic data for one APC device."""
    dump: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "host": REDACTED_IP,
        "port": port,
        "unit_id": unit_id,
        "snmp": asyncio.run(_collect_snmp_data(host, community)),
        "modbus": {},
    }

    for start, count in MODBUS_BLOCKS:
        key = f"0x{start:04X}_count_{count}"
        dump["modbus"][key] = _collect_modbus_block(host, port, unit_id, start, count)

    _add_decodes(dump)
    return _sanitize_data(dump, host, community)
