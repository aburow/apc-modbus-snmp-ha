"""Focused checks for V2 fixed physical-validation commands."""

import importlib.util
from pathlib import Path
import sys


MODULE = (
    Path(__file__).resolve().parents[1]
    / "custom_components/apc_modbus/modbus_commands.py"
)
SPEC = importlib.util.spec_from_file_location("modbus_commands", MODULE)
assert SPEC and SPEC.loader
commands = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = commands
SPEC.loader.exec_module(commands)


def test_documented_static_commands_include_bypass() -> None:
    assert set(commands.COMMANDS) == {
        "bypass_enter",
        "bypass_exit",
        "battery_test_start",
        "battery_test_abort",
        "calibration_start",
        "calibration_abort",
        "alarm_mute",
        "alarm_cancel_mute",
    }
    assert commands.COMMANDS["bypass_enter"].address == 0x0600
    assert commands.COMMANDS["bypass_enter"].words == (0, 0x0010)
    assert commands.COMMANDS["bypass_exit"].words == (0, 0x0020)


def test_outlet_command_is_fixed_to_a_documented_target_and_source() -> None:
    assert set(commands.OUTLET_ACTION_BITS) == {
        "outlet_cancel",
        "outlet_on",
        "outlet_off",
        "outlet_shutdown",
        "outlet_reboot",
    }
    assert set(commands.OUTLET_TARGET_BITS) == {
        "main_outlet_group",
        "switched_outlet_group_1",
        "switched_outlet_group_2",
        "switched_outlet_group_3",
    }
    command = commands.get_command("outlet_off", "switched_outlet_group_2")
    assert command.address == 0x0602
    assert command.words == (2, 0x0404)


def test_command_transport_response_record_excludes_raw_register_payload() -> None:
    transport_module = (
        Path(__file__).resolve().parents[1]
        / "custom_components/apc_modbus/modbus_transport.py"
    )
    source = transport_module.read_text()

    assert "response_type=%s" in source
    assert "exception_code=%s" in source
    assert "response.registers" not in source
    assert "plugin_version=%s" in (MODULE.parent / "button.py").read_text()


def test_command_writes_use_function_16_for_one_register_actions() -> None:
    transport_module = (
        Path(__file__).resolve().parents[1]
        / "custom_components/apc_modbus/modbus_transport.py"
    )
    source = transport_module.read_text()

    assert "force_multiple=True" in (MODULE.parent / "button.py").read_text()
    assert "force_multiple or len(words) > 1" in source
    assert '"write_registers"' in source
    assert "list(words) if force_multiple or len(words) > 1 else words[0]" in source
    assert 'getattr(response, "function_code", None) == 16' in source


def test_command_buttons_are_available_but_disabled_by_default() -> None:
    source = (MODULE.parent / "button.py").read_text()

    assert source.count("_attr_entity_registry_enabled_default = False") == 2
    assert "RegistryEntryDisabler.INTEGRATION" not in source


def test_reset_defaults_disables_current_and_retained_write_entities() -> None:
    source = (MODULE.parent / "entity_defaults.py").read_text()

    assert "set(COMMANDS)" in source
    assert "set(LEGACY_SNMP_COMMANDS)" in source
    assert 'entity_entry.domain in {"button", "switch"}' in source
    assert 'local_key.startswith("write_")' in source
    assert "should_enable = False" in source
