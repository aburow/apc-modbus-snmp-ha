# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""On-demand diagnostics collector for APC devices."""

from __future__ import annotations

import asyncio
import json
import re
import socket
import struct
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .device_types import classify_device_type
from .snmp_helper import (
    async_get_snmp_value,
    detect_external_probe_oids_sync,
    get_external_probe_data_detected_sync,
)

MBAP_HEADER_LENGTH = 7
MIN_MODBUS_RESPONSE_LENGTH = 9
MODBUS_EXCEPTION_FLAG = 0x80
INT16_SIGN_BIT = 0x8000
INT16_MODULUS = 0x10000
ASCII_PRINTABLE_START = 32
ASCII_PRINTABLE_END = 126
FREQUENCY_TENTHS_THRESHOLD = 400
IDLE_PROBE_ADDRESS = 0x0000
IDLE_PROBE_COUNT = 1
SHORT_IDLE_PROBE_SECONDS = 3

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
    "apc_input_frequency": "1.3.6.1.4.1.318.1.1.1.3.2.4.0",
    "upsmib_input_frequency_line1": "1.3.6.1.2.1.33.1.3.3.1.2.1",
}

MODBUS_BLOCKS: list[tuple[int, int]] = [
    (0x0000, 0x0016 - 0x0000 + 1),
    (0x0080, 0x0099 - 0x0080 + 1),
    (0x0021, 0x002A - 0x0021 + 1),
    (0x009E, 0x00A2 - 0x009E + 1),
    (0x00CF, 0x00D4 - 0x00CF + 1),
    (0x023C, 0x0250 - 0x023C + 1),
]

MODBUS_PROBES: list[tuple[str, int, int]] = [
    ("rack_pdu_capabilities", 0x009E, 5),
    ("rack_pdu_measurements", 0x00CF, 6),
    ("legacy_ups_id", 0x0021, 1),
    ("smt_status", 0x0000, 23),
    ("smt_measurements", 0x0080, 26),
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


def _load_integration_version() -> str:
    """Return integration version from manifest.json when available."""
    manifest_path = Path(__file__).with_name("manifest.json")
    try:
        with manifest_path.open(encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
    except (OSError, ValueError, TypeError):
        return "unknown"

    version = manifest.get("version")
    return version if isinstance(version, str) and version else "unknown"


INTEGRATION_VERSION = _load_integration_version()


def _modbus_read_holding_registers(
    host: str, port: int, unit_id: int, address: int, count: int, timeout: int = 5
) -> bytes:
    with socket.create_connection((host, port), timeout=timeout) as connection:
        return _modbus_read_holding_registers_on_connection(
            connection,
            unit_id,
            address,
            count,
        )


def _modbus_read_holding_registers_on_connection(
    connection: socket.socket,
    unit_id: int,
    address: int,
    count: int,
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
    output_frequency = _scaled_register(registers, 0x0090, 128)
    return {
        "runtime_remaining": _decode_uint32(registers, _block_index(0x0080)),
        "soc_pct": _scaled_register(registers, 0x0082, 512),
        "batt_v_pos": _scaled_register(registers, 0x0083, 32, signed=True),
        "batt_v_neg": _scaled_register(registers, 0x0084, 32, signed=True),
        "batt_temp_c": _scaled_register(registers, 0x0087, 128, signed=True),
        "out_load_pct": _scaled_register(registers, 0x0088, 256),
        "out_current": _scaled_register(registers, 0x008C, 32),
        "out_voltage": _scaled_register(registers, 0x008E, 64),
        "out_freq": output_frequency,
        "in_freq": output_frequency,
        "out_energy_wh": _decode_uint32(registers, _block_index(0x0091)),
        "in_voltage": _scaled_register(registers, 0x0097, 64),
    }


def _parse_snmp_frequency_hz(value: str) -> float | None:
    try:
        raw = float(value.strip())
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    if raw > FREQUENCY_TENTHS_THRESHOLD:
        return raw / 10.0
    return raw


def _decode_snmp_input_frequency(snmp_data: dict[str, Any]) -> dict[str, Any] | None:
    for source_key in ("apc_input_frequency", "upsmib_input_frequency_line1"):
        source = snmp_data.get(source_key)
        if not isinstance(source, dict):
            continue
        value = source.get("value")
        if not isinstance(value, str):
            continue
        parsed_hz = _parse_snmp_frequency_hz(value)
        if parsed_hz is None:
            continue
        return {
            "input_frequency_hz": parsed_hz,
            "input_frequency_source": source_key,
        }
    return None


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
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            # Keep SNMP OIDs as-is for troubleshooting/reference readability.
            if key == "oid" or key.endswith("_oid"):
                sanitized[key] = item
                continue
            sanitized[key] = _sanitize_data(item, host, community)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_data(item, host, community) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value, host, community)
    return value


def _probe_block_ok(modbus_block: dict[str, Any] | None, count: int) -> bool:
    """Return True when a collected Modbus block contains a successful read."""
    if not modbus_block or "parsed" not in modbus_block:
        return False
    parsed = modbus_block["parsed"]
    registers = parsed.get("registers")
    return isinstance(registers, list) and len(registers) == count


def _build_detection_summary(modbus_probes: dict[str, Any]) -> dict[str, Any]:
    """Summarize exact runtime probe results using the same classifier as HA."""
    rack_pdu_capabilities_ok = _probe_block_ok(
        modbus_probes.get("rack_pdu_capabilities"), 5
    )
    rack_pdu_measurements_ok = _probe_block_ok(
        modbus_probes.get("rack_pdu_measurements"), 6
    )
    legacy_probe_ok = _probe_block_ok(modbus_probes.get("legacy_ups_id"), 1)
    smt_status_ok = _probe_block_ok(modbus_probes.get("smt_status"), 23)
    smt_measurements_ok = _probe_block_ok(modbus_probes.get("smt_measurements"), 26)

    detected = classify_device_type(
        rack_pdu_capabilities_ok=rack_pdu_capabilities_ok,
        rack_pdu_measurements_ok=rack_pdu_measurements_ok,
        legacy_probe_ok=legacy_probe_ok,
        smt_status_ok=smt_status_ok,
        smt_measurements_ok=smt_measurements_ok,
    )

    return {
        "detected_device_type": detected.value if detected else None,
        "probe_results": {
            "rack_pdu_capabilities_ok": rack_pdu_capabilities_ok,
            "rack_pdu_measurements_ok": rack_pdu_measurements_ok,
            "legacy_probe_ok": legacy_probe_ok,
            "smt_status_ok": smt_status_ok,
            "smt_measurements_ok": smt_measurements_ok,
        },
    }


async def _collect_snmp_data(
    host: str, community: str, snmp_port: int
) -> dict[str, Any]:
    values = await asyncio.gather(
        *(
            async_get_snmp_value(host, oid, community, snmp_port=snmp_port)
            for oid in SNMP_OIDS.values()
        ),
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


def _collect_external_probe_tests(
    host: str, community: str, snmp_port: int
) -> dict[str, Any]:
    """Collect explicit SNMP external probe detection and read tests."""
    tests: dict[str, Any] = {}

    try:
        detection = detect_external_probe_oids_sync(host, community, snmp_port)
        tests["detect"] = {"ok": True, "detection": detection}
    except (
        OSError,
        TimeoutError,
        RuntimeError,
        ValueError,
        asyncio.TimeoutError,
    ) as err:
        tests["detect"] = {
            "ok": False,
            "error": {
                "code": "snmp_external_probe_detection_failed",
                "message": str(err),
                "exception_type": type(err).__name__,
            },
        }
        return tests

    try:
        values = get_external_probe_data_detected_sync(
            host, community, detection, snmp_port
        )
        tests["read_detected"] = {
            "ok": True,
            "value_count": len(values),
            "values": values,
        }
    except (
        OSError,
        TimeoutError,
        RuntimeError,
        ValueError,
        asyncio.TimeoutError,
    ) as err:
        tests["read_detected"] = {
            "ok": False,
            "error": {
                "code": "snmp_external_probe_read_failed",
                "message": str(err),
                "exception_type": type(err).__name__,
            },
        }

    return tests


def _run_modbus_tcp_idle_probe_once(
    host: str,
    port: int,
    unit_id: int,
    idle_seconds: int | float | None,
) -> dict[str, Any]:
    """Test whether one Modbus TCP socket survives one idle interval."""
    result: dict[str, Any] = {
        "enabled": idle_seconds is not None,
        "idle_seconds_tested": idle_seconds,
        "address": IDLE_PROBE_ADDRESS,
        "count": IDLE_PROBE_COUNT,
    }
    if idle_seconds is None:
        result["skipped_reason"] = "no_idle_seconds_supplied"
        return result

    try:
        idle_seconds_float = float(idle_seconds)
    except (TypeError, ValueError):
        result["error"] = {
            "code": "invalid_idle_seconds",
            "message": f"Invalid idle seconds: {idle_seconds!r}",
        }
        return result

    if idle_seconds_float < 0:
        result["error"] = {
            "code": "invalid_idle_seconds",
            "message": "Idle seconds must not be negative",
        }
        return result

    try:
        with socket.create_connection((host, port), timeout=5) as connection:
            first_raw = _modbus_read_holding_registers_on_connection(
                connection,
                unit_id,
                IDLE_PROBE_ADDRESS,
                IDLE_PROBE_COUNT,
            )
            first_parsed = _parse_modbus_response(first_raw)
            result["first_read"] = {"ok": "error" not in first_parsed}

            time.sleep(idle_seconds_float)

            second_raw = _modbus_read_holding_registers_on_connection(
                connection,
                unit_id,
                IDLE_PROBE_ADDRESS,
                IDLE_PROBE_COUNT,
            )
            second_parsed = _parse_modbus_response(second_raw)
            result["second_read"] = {"ok": "error" not in second_parsed}
            result["socket_survived_idle"] = "error" not in second_parsed
    except (OSError, RuntimeError, struct.error) as err:
        result["socket_survived_idle"] = False
        result["second_read"] = {
            "ok": False,
            "error": {
                "code": "modbus_idle_reuse_failed",
                "message": str(err),
                "exception_type": type(err).__name__,
            },
        }

    return result


def _build_modbus_tcp_idle_probe(
    host: str,
    port: int,
    unit_id: int,
    idle_seconds: int | float | None,
    *,
    keep_connection_open: bool | None = None,
) -> dict[str, Any]:
    """Test whether Modbus TCP sockets survive short and configured idle intervals."""
    result: dict[str, Any] = {
        "enabled": idle_seconds is not None,
        "configured_idle_seconds_tested": idle_seconds,
        "short_idle_seconds_tested": SHORT_IDLE_PROBE_SECONDS,
        "keep_connection_open": keep_connection_open,
        "short_idle": _run_modbus_tcp_idle_probe_once(
            host,
            port,
            unit_id,
            SHORT_IDLE_PROBE_SECONDS,
        ),
    }
    if idle_seconds is None:
        result["configured_idle"] = {
            "enabled": False,
            "skipped_reason": "no_idle_seconds_supplied",
        }
        return result

    result["configured_idle"] = _run_modbus_tcp_idle_probe_once(
        host,
        port,
        unit_id,
        idle_seconds,
    )

    configured_survived = result["configured_idle"].get("socket_survived_idle")
    if keep_connection_open and configured_survived is False:
        result["risk"] = (
            "The UPS closed the Modbus TCP connection before the configured Home "
            "Assistant polling "
            "interval elapsed. If your UPS exposes a Modbus TCP Timeout setting, "
            "set it higher than the configured polling interval. Otherwise, disable "
            "Keep Connection Open for this device."
        )
    return result


def _add_decodes(dump: dict[str, Any]) -> None:
    snmp_decode = _decode_snmp_input_frequency(dump.get("snmp", {}))
    if snmp_decode:
        dump["snmp_decode"] = snmp_decode

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
    host: str,
    community: str,
    modbus_port: int,
    unit_id: int,
    idle_probe_seconds: int | float | None = None,
    keep_connection_open: bool | None = None,
    snmp_port: int = 161,
) -> dict[str, Any]:
    """Collect SNMP and Modbus diagnostic data for one APC device."""
    dump: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "integration_version": INTEGRATION_VERSION,
        "host": REDACTED_IP,
        "port": modbus_port,
        "snmp_port": snmp_port,
        "unit_id": unit_id,
        "snmp": asyncio.run(_collect_snmp_data(host, community, snmp_port)),
        "modbus": {},
        "modbus_probes": {},
        "modbus_tcp_idle_probe": _build_modbus_tcp_idle_probe(
            host,
            modbus_port,
            unit_id,
            idle_probe_seconds,
            keep_connection_open=keep_connection_open,
        ),
        "external_probe_tests": _collect_external_probe_tests(
            host, community, snmp_port
        ),
    }

    for start, count in MODBUS_BLOCKS:
        key = f"0x{start:04X}_count_{count}"
        dump["modbus"][key] = _collect_modbus_block(
            host, modbus_port, unit_id, start, count
        )

    for probe_name, start, count in MODBUS_PROBES:
        dump["modbus_probes"][probe_name] = _collect_modbus_block(
            host, modbus_port, unit_id, start, count
        )

    _add_decodes(dump)
    dump["detection"] = _build_detection_summary(dump["modbus_probes"])
    return _sanitize_data(dump, host, community)
