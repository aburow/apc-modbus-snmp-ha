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
    assert commands.COMMANDS["bypass_enter"].address == 0x0600
    assert commands.COMMANDS["bypass_enter"].words == (0, 0x0010)
    assert commands.COMMANDS["bypass_exit"].words == (0, 0x0020)


def test_outlet_command_is_fixed_to_a_documented_target_and_source() -> None:
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
