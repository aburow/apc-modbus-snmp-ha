# SPDX-FileCopyrightText: 2026 github.com/aburow
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "apc_modbus"
        / "sensor_availability_unified.py"
    )
    spec = importlib.util.spec_from_file_location(
        "apc_modbus.sensor_availability_unified", module_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_rack_pdu_core_metrics_enabled_for_bridge_contract() -> None:
    mod = _load_module()

    required_enabled = [
        "device_real_power",
        "device_apparent_power",
        "device_power_factor",
        "device_energy",
        "phase_l1_current",
        "phase_l1_voltage",
    ]

    for key in required_enabled:
        assert mod.entity_enabled_default(key) is True, key


def test_rack_pdu_metadata_policy_is_explicit_and_stable() -> None:
    mod = _load_module()

    expected = False

    for key in ("model", "serial_number", "sw_version", "hw_version"):
        assert mod.entity_enabled_default(key) is expected, key


def test_rack_pdu_non_core_metrics_stay_disabled_by_default() -> None:
    mod = _load_module()

    for key in ("num_phases", "num_metered_outlets"):
        assert mod.entity_enabled_default(key) is False, key
