"""Regression coverage for documented SMT battery-date entities."""

import ast
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTERS = (ROOT / "custom_components/apc_modbus/registers_smt_ups.py").read_text()
DATE_PLATFORM = (ROOT / "custom_components/apc_modbus/date.py").read_text()
DEFAULTS = (ROOT / "custom_components/apc_modbus/entity_defaults.py").read_text()


def test_smt_battery_dates_use_documented_addresses_and_epoch() -> None:
    assert "BATTERY_DATE_EPOCH = date(2000, 1, 1)" in REGISTERS
    assert '"key": "battery_replacement_date_days"' in REGISTERS
    assert '"address": 0x0085' in REGISTERS
    assert '"key": "battery_installation_date_days"' in REGISTERS
    assert '"address": 0x0253' in REGISTERS
    assert '"name": "battery_date_setting"' in REGISTERS
    assert 'key="battery_replacement_date"' in REGISTERS
    assert "device_class=SensorDeviceClass.DATE" in REGISTERS


def test_battery_date_zero_value_uses_the_documented_epoch() -> None:
    tree = ast.parse(REGISTERS)
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "BATTERY_DATE_EPOCH"
                for target in node.targets
            )
        )
        or isinstance(node, ast.FunctionDef)
        and node.name == "_battery_date"
    ]
    namespace = {"date": date, "timedelta": timedelta}
    exec(compile(ast.Module(nodes, type_ignores=[]), str(ROOT), "exec"), namespace)

    assert namespace["_battery_date"](0) == date(2000, 1, 1)
    assert namespace["_battery_date"](9071) == date(2024, 11, 1)


def test_installation_date_is_a_bounded_disabled_one_shot_setting() -> None:
    assert "APCDeviceType.SMARTCONNECT_UPS" in DATE_PLATFORM
    assert "_attr_entity_registry_enabled_default = False" in DATE_PLATFORM
    assert "if not 0 <= days <= 0xFFFF" in DATE_PLATFORM
    assert "_BATTERY_DATE_SETTING_ADDRESS = 0x0253" in DATE_PLATFORM
    assert "force_multiple=True" in DATE_PLATFORM
    assert "await self.coordinator.async_request_refresh()" in DATE_PLATFORM
    assert '"battery_installation_date"' in DEFAULTS
    assert '"date"' in DEFAULTS
