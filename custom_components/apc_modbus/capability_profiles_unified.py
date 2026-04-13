# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow

"""Unified interop capability profiles for UPS Unified bridge consumers.

Dependency-free contract module for external runtime loading.
"""

from __future__ import annotations

from typing import Any

CONTRACT_VERSION = "2.0.0"

POLL_GROUPS_DEFAULT: dict[str, dict[str, int]] = {
    "fast": {"interval_s": 10},
    "slow": {"interval_s": 60},
}

SMARTUPS_METADATA_OIDS = {
    "model": {
        "oid": "1.3.6.1.4.1.318.1.1.1.1.1.1.0",
        "poll_group": "slow",
    },
    "serial_number": {
        "oid": "1.3.6.1.4.1.318.1.1.1.1.2.3.0",
        "poll_group": "slow",
    },
    "sw_version": {
        "oid": "1.3.6.1.4.1.318.1.1.1.1.2.1.0",
        "poll_group": "slow",
    },
    "hw_version": {
        "oid": "1.3.6.1.4.1.318.1.1.1.1.2.2.0",
        "poll_group": "slow",
    },
}

RACK_PDU_METADATA_OIDS = {
    "model": {
        "oid": "1.3.6.1.4.1.318.1.1.12.1.5.0",
        "poll_group": "slow",
    },
    "serial_number": {
        "oid": "1.3.6.1.4.1.318.1.1.12.1.6.0",
        "poll_group": "slow",
    },
    "sw_version": {
        "oid": "1.3.6.1.4.1.318.1.1.12.1.3.0",
        "poll_group": "slow",
    },
    "hw_version": {
        "oid": "1.3.6.1.4.1.318.1.1.12.1.4.0",
        "poll_group": "slow",
    },
}

PROFILES: tuple[dict[str, Any], ...] = (
    {
        "profile_id": "apc_modbus_smart",
        "protocol": "hybrid",
        "modbus": {
            "registers": [
                {
                    "key": "runtime_remaining",
                    "address": 0x0006,
                    "count": 1,
                    "type": "uint16",
                    "scale": 1,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "battery_state_of_charge",
                    "address": 0x0005,
                    "count": 1,
                    "type": "uint16",
                    "scale": 1,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "input_voltage",
                    "address": 0x0011,
                    "count": 1,
                    "type": "uint16",
                    "scale": 1,
                    "word_order": "big",
                },
                {
                    "key": "output_voltage",
                    "address": 0x000E,
                    "count": 1,
                    "type": "uint16",
                    "scale": 1,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "output_load_percent",
                    "address": 0x000C,
                    "count": 1,
                    "type": "uint16",
                    "scale": 1,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "input_frequency",
                    "address": 0x0012,
                    "count": 1,
                    "type": "uint16",
                    "scale": 1,
                    "word_order": "big",
                },
            ],
            "register_blocks": [
                {
                    "name": "core_fast",
                    "start_address": 0x0000,
                    "count": 24,
                    "poll_group": "fast",
                },
                {
                    "name": "identity_slow",
                    "start_address": 0x001A,
                    "count": 21,
                },
            ],
        },
        "snmp": {
            "oids": SMARTUPS_METADATA_OIDS,
            "snmp_blocks": [
                {
                    "name": "metadata",
                    "metrics": ["model", "serial_number", "sw_version", "hw_version"],
                    "poll_group": "slow",
                }
            ],
        },
        "poll_groups": POLL_GROUPS_DEFAULT,
        "key_precedence": {
            "model": "snmp",
            "serial_number": "snmp",
            "sw_version": "snmp",
            "hw_version": "snmp",
        },
    },
    {
        "profile_id": "apc_modbus_smt",
        "protocol": "hybrid",
        "modbus": {
            "registers": [
                {
                    "key": "runtime_remaining",
                    "address": 0x0080,
                    "count": 2,
                    "type": "uint32",
                    "scale": 1,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "battery_state_of_charge",
                    "address": 0x0082,
                    "count": 1,
                    "type": "uint16",
                    "scale": 512,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "input_voltage",
                    "address": 0x0097,
                    "count": 1,
                    "type": "uint16",
                    "scale": 64,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "output_voltage",
                    "address": 0x008E,
                    "count": 1,
                    "type": "uint16",
                    "scale": 64,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "output_load_percent",
                    "address": 0x0088,
                    "count": 1,
                    "type": "uint16",
                    "scale": 256,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "output_frequency",
                    "address": 0x0090,
                    "count": 1,
                    "type": "uint16",
                    "scale": 128,
                    "word_order": "big",
                    "poll_group": "fast",
                },
            ],
            "register_blocks": [
                {
                    "name": "status_slow",
                    "start_address": 0x0000,
                    "count": 23,
                },
                {
                    "name": "measurements_fast",
                    "start_address": 0x0080,
                    "count": 26,
                    "poll_group": "fast",
                },
            ],
        },
        "snmp": {
            "oids": SMARTUPS_METADATA_OIDS,
            "snmp_blocks": [
                {
                    "name": "metadata",
                    "metrics": ["model", "serial_number", "sw_version", "hw_version"],
                    "poll_group": "slow",
                }
            ],
        },
        "poll_groups": POLL_GROUPS_DEFAULT,
        "key_precedence": {
            "model": "snmp",
            "serial_number": "snmp",
            "sw_version": "snmp",
            "hw_version": "snmp",
        },
    },
    {
        "profile_id": "apc_modbus_rack_pdu",
        "protocol": "hybrid",
        "modbus": {
            "registers": [
                {
                    "key": "device_real_power",
                    "address": 0x00CF,
                    "count": 1,
                    "type": "int16",
                    "scale": 100,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "device_apparent_power",
                    "address": 0x00D0,
                    "count": 1,
                    "type": "int16",
                    "scale": 100,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "device_power_factor",
                    "address": 0x00D1,
                    "count": 1,
                    "type": "int16",
                    "scale": 100,
                    "word_order": "big",
                },
                {
                    "key": "device_energy",
                    "address": 0x00D2,
                    "count": 2,
                    "type": "uint32",
                    "scale": 10,
                    "word_order": "big",
                },
                {
                    "key": "phase_l1_current",
                    "address": 0x029B,
                    "count": 1,
                    "type": "int16",
                    "scale": 10,
                    "word_order": "big",
                    "poll_group": "fast",
                },
                {
                    "key": "phase_l1_voltage",
                    "address": 0x029C,
                    "count": 1,
                    "type": "uint16",
                    "scale": 1,
                    "word_order": "big",
                    "poll_group": "fast",
                },
            ],
            "register_blocks": [
                {
                    "name": "capabilities_slow",
                    "start_address": 0x009E,
                    "count": 5,
                },
                {
                    "name": "device_measurements_fast",
                    "start_address": 0x00CF,
                    "count": 7,
                    "poll_group": "fast",
                },
            ],
        },
        "snmp": {
            "oids": RACK_PDU_METADATA_OIDS,
            "snmp_blocks": [
                {
                    "name": "metadata",
                    "metrics": ["model", "serial_number", "sw_version", "hw_version"],
                    "poll_group": "slow",
                }
            ],
        },
        "poll_groups": POLL_GROUPS_DEFAULT,
        "key_precedence": {
            "model": "snmp",
            "serial_number": "snmp",
            "sw_version": "snmp",
            "hw_version": "snmp",
        },
    },
)


def get_profile(profile_id: str) -> dict[str, Any] | None:
    """Return an interop profile by id."""
    if not isinstance(profile_id, str):
        return None
    for profile in PROFILES:
        if profile.get("profile_id") == profile_id:
            return profile
    return None
