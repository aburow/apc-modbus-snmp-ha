# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apc_modbus"
    / "external_probe_entities.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "apc_external_probe_entities", MODULE_PATH
)
assert MODULE_SPEC and MODULE_SPEC.loader
EXTERNAL_PROBES = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(EXTERNAL_PROBES)


def test_detected_external_probe_available_without_current_value() -> None:
    assert (
        EXTERNAL_PROBES.is_external_probe_entity_available(
            "snmp_external_temp_1",
            {},
            {"temp_1_oid": "1.3.6.1.4.1.318.1.1.25.1.2.1.6.1.1"},
        )
        is True
    )


def test_external_probe_available_when_current_value_exists() -> None:
    assert (
        EXTERNAL_PROBES.is_external_probe_entity_available(
            "snmp_external_temp_1",
            {"snmp_external_temp_1": 24.0},
            {},
        )
        is True
    )


def test_undetected_external_probe_hidden_without_current_value() -> None:
    assert (
        EXTERNAL_PROBES.is_external_probe_entity_available(
            "snmp_external_temp_1",
            {},
            {"temp_1_oid": None},
        )
        is False
    )


def test_non_external_probe_keys_are_always_available() -> None:
    assert (
        EXTERNAL_PROBES.is_external_probe_entity_available(
            "battery_state_of_charge",
            {},
            None,
        )
        is True
    )


def test_filter_available_external_probe_keys_uses_detection_map() -> None:
    keys = {
        "battery_state_of_charge",
        "snmp_external_temp_1",
        "snmp_external_humidity_1",
        "snmp_external_temp_2",
    }

    assert EXTERNAL_PROBES.filter_available_external_probe_keys(
        keys,
        {},
        {
            "temp_1_oid": "1.3.6.1.4.1.318.1.1.25.1.2.1.6.1.1",
            "humidity_1_oid": None,
            "temp_2_oid": None,
        },
    ) == {"battery_state_of_charge", "snmp_external_temp_1"}


def test_all_external_probe_keys_map_to_their_detection_oids() -> None:
    assert EXTERNAL_PROBES.filter_available_external_probe_keys(
        {
            "snmp_external_temp_1",
            "snmp_external_humidity_1",
            "snmp_external_temp_2",
            "snmp_external_humidity_2",
        },
        {},
        {
            "temp_1_oid": "temp-1",
            "humidity_1_oid": "humidity-1",
            "temp_2_oid": "temp-2",
            "humidity_2_oid": "humidity-2",
        },
    ) == {
        "snmp_external_temp_1",
        "snmp_external_humidity_1",
        "snmp_external_temp_2",
        "snmp_external_humidity_2",
    }


def test_frequency_only_detection_does_not_create_probe_entities() -> None:
    assert EXTERNAL_PROBES.filter_available_external_probe_keys(
        {
            "input_frequency",
            "snmp_external_temp_1",
            "snmp_external_humidity_1",
        },
        {},
        {
            "frequency_oid": "1.3.6.1.4.1.318.1.1.1.3.2.4.0",
            "temp_1_oid": None,
            "humidity_1_oid": None,
        },
    ) == {"input_frequency"}
