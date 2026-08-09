"""Behavioral tests for write discovery and the no-replay transport boundary."""

from __future__ import annotations

import asyncio
from enum import StrEnum
import importlib
import importlib.util
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "custom_components/apc_modbus"


def _load_runtime(monkeypatch: pytest.MonkeyPatch):
    package = ModuleType("write_runtime")
    package.__path__ = [str(PACKAGE_PATH)]
    monkeypatch.setitem(sys.modules, "write_runtime", package)

    pymodbus = ModuleType("pymodbus")
    pymodbus_client = ModuleType("pymodbus.client")

    class RecreatedClient:
        created = []

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.retries = kwargs.get("retries")
            self.created.append(kwargs)

        def close(self):
            pass

        def connect(self):
            return True

        def read_holding_registers(self, address, *, count=1, device_id=1):
            return SimpleNamespace(registers=[0] * count)

        def write_register(
            self, address, value, *, device_id=1, no_response_expected=False
        ):
            return SimpleNamespace(address=address, registers=[value], retries=0)

        def write_registers(
            self, address, values, *, device_id=1, no_response_expected=False
        ):
            return SimpleNamespace(address=address, count=len(values), retries=0)

    pymodbus_client.ModbusTcpClient = RecreatedClient
    pymodbus_exceptions = ModuleType("pymodbus.exceptions")
    pymodbus_exceptions.ConnectionException = type(
        "ConnectionException", (Exception,), {}
    )
    pymodbus_exceptions.ModbusException = type("ModbusException", (Exception,), {})
    monkeypatch.setitem(sys.modules, "pymodbus", pymodbus)
    monkeypatch.setitem(sys.modules, "pymodbus.client", pymodbus_client)
    monkeypatch.setitem(sys.modules, "pymodbus.exceptions", pymodbus_exceptions)

    homeassistant = ModuleType("homeassistant")
    ha_const = ModuleType("homeassistant.const")
    ha_const.CONF_HOST = "host"
    ha_const.CONF_PORT = "port"
    ha_core = ModuleType("homeassistant.core")
    ha_core.HomeAssistant = object
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_coordinator = ModuleType("homeassistant.helpers.update_coordinator")

    class Coordinator:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, *args, **kwargs):
            self.hass = hass
            self.last_update_success = True

    ha_coordinator.DataUpdateCoordinator = Coordinator
    ha_coordinator.UpdateFailed = RuntimeError
    ha_storage = ModuleType("homeassistant.helpers.storage")

    class Store:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, *args):
            pass

    ha_storage.Store = Store
    ha_exceptions = ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        def __init__(self, **kwargs):
            self.translation_key = kwargs.get("translation_key")
            super().__init__(self.translation_key)

    class ServiceValidationError(HomeAssistantError):
        pass

    ha_exceptions.HomeAssistantError = HomeAssistantError
    ha_exceptions.ServiceValidationError = ServiceValidationError
    for name, module in (
        ("homeassistant", homeassistant),
        ("homeassistant.const", ha_const),
        ("homeassistant.core", ha_core),
        ("homeassistant.helpers", ha_helpers),
        ("homeassistant.helpers.update_coordinator", ha_coordinator),
        ("homeassistant.helpers.storage", ha_storage),
        ("homeassistant.exceptions", ha_exceptions),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    const = ModuleType("write_runtime.const")
    const.DEFAULT_IDLE_RECONNECT_SECONDS = 0
    const.DEFAULT_PORT = 502
    const.DEFAULT_SCAN_INTERVAL = 10
    const.DOMAIN = "apc_modbus"
    monkeypatch.setitem(sys.modules, "write_runtime.const", const)

    device_spec = importlib.util.spec_from_file_location(
        "write_runtime.device_types", PACKAGE_PATH / "device_types.py"
    )
    assert device_spec and device_spec.loader
    device_types = importlib.util.module_from_spec(device_spec)
    monkeypatch.setitem(sys.modules, device_spec.name, device_types)
    device_spec.loader.exec_module(device_types)

    registers = ModuleType("write_runtime.registers_smart_ups")
    registers.REGISTERS, registers.REGISTER_BLOCKS, registers.REGISTER_MAP = [], [], {}
    monkeypatch.setitem(sys.modules, "write_runtime.registers_smart_ups", registers)

    tracker = ModuleType("write_runtime.output_energy_tracker")

    class Tracker:
        @classmethod
        def from_storage(cls, *args):
            return cls()

    tracker.OutputEnergyTracker = Tracker
    monkeypatch.setitem(sys.modules, "write_runtime.output_energy_tracker", tracker)
    snmp = ModuleType("write_runtime.snmp_helper")
    for name in (
        "detect_external_probe_oids_sync",
        "get_device_metadata_sync",
        "get_external_probe_data_detected_sync",
        "get_self_test_data_sync",
    ):
        setattr(snmp, name, lambda *_: None)
    monkeypatch.setitem(sys.modules, "write_runtime.snmp_helper", snmp)
    snmp_state = ModuleType("write_runtime.snmp_state")
    snmp_state.has_usable_metadata = lambda *_: False
    monkeypatch.setitem(sys.modules, "write_runtime.snmp_state", snmp_state)

    spec = importlib.util.spec_from_file_location(
        "write_runtime.coordinator", PACKAGE_PATH / "coordinator.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module, device_types, ha_exceptions, RecreatedClient


class FakeEntries:
    def async_entries(self, domain):
        return [SimpleNamespace(data={"host": "ups", "port": 502})]


class FakeHass:
    def __init__(self):
        self.config_entries = FakeEntries()

    async def async_add_executor_job(self, request):
        return await asyncio.to_thread(request)


class FakeClient:
    def __init__(self, *, failure=None, response=None, connect=True):
        self.retries = 0
        self.failure = failure
        self.response = response
        self.connect_result = connect
        self.calls = 0
        self.closed = 0
        self.active = 0
        self.max_active = 0

    def connect(self):
        return self.connect_result

    def close(self):
        self.closed += 1

    def read_holding_registers(self, address, *, count=1, device_id=1):
        return SimpleNamespace(registers=[0] * count)

    def write_register(
        self, address, value, *, device_id=1, no_response_expected=False
    ):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        self.active -= 1
        if self.failure:
            raise self.failure
        return self.response or SimpleNamespace(
            address=address, registers=[value], retries=0
        )

    def write_registers(
        self, address, values, *, device_id=1, no_response_expected=False
    ):
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.response or SimpleNamespace(
            address=address, count=len(values), retries=0
        )


def _coordinator(runtime, device_types, client):
    coordinator = runtime.APCModbusCoordinator(
        FakeHass(),
        client,
        1,
        "UPS",
        "ups",
        502,
        "entry",
        5,
        asyncio.Lock(),
        "public",
        161,
    )
    coordinator.set_device_type(device_types.APCDeviceType.SMT_UPS)
    coordinator._post_connect_delay = 0
    coordinator._inter_block_delay = 0
    coordinator._write_reconcile_attempts = 1
    coordinator._write_reconcile_delay = 0
    return coordinator


async def _success_timeout_and_connect_failure_never_replay(monkeypatch):
    runtime, device_types, errors, _ = _load_runtime(monkeypatch)
    support = importlib.import_module("write_runtime.write_support")

    success_client = FakeClient()
    coordinator = _coordinator(runtime, device_types, success_client)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}
    refresh_lock_states = []

    async def refresh():
        refresh_lock_states.append(coordinator._io_lock.locked())
        coordinator.data["battery_test_status"] = 1

    coordinator.async_request_refresh = refresh
    await coordinator.async_execute_write(
        support.WriteOperation.BATTERY_TEST_START.value
    )
    assert success_client.calls == 1
    assert refresh_lock_states == [False]
    assert not coordinator._write_pending

    async def unchanged_refresh():
        pass

    timeout_client = FakeClient(failure=TimeoutError("lost response"))
    coordinator = _coordinator(runtime, device_types, timeout_client)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}
    coordinator.async_request_refresh = unchanged_refresh
    with pytest.raises(errors.HomeAssistantError) as caught:
        await coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        )
    assert caught.value.translation_key == "write_outcome_unknown"
    assert timeout_client.calls == 1

    unexpected = FakeClient(failure=RuntimeError("unexpected executor failure"))
    coordinator = _coordinator(runtime, device_types, unexpected)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}

    coordinator.async_request_refresh = unchanged_refresh
    with pytest.raises(errors.HomeAssistantError):
        await coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        )
    with pytest.raises(errors.ServiceValidationError) as caught:
        await coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        )
    assert caught.value.translation_key == "write_outcome_unresolved"
    assert unexpected.calls == 1

    for failure in (OSError("disconnect"), runtime.ModbusException("device error")):
        failed_client = FakeClient(failure=failure)
        coordinator = _coordinator(runtime, device_types, failed_client)
        coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
        coordinator.data = {"battery_test_status": 0}
        coordinator.async_request_refresh = unchanged_refresh
        with pytest.raises(errors.HomeAssistantError):
            await coordinator.async_execute_write(
                support.WriteOperation.BATTERY_TEST_START.value
            )
        assert failed_client.calls == 1

    reconciled_timeout = FakeClient(failure=TimeoutError("lost response"))
    coordinator = _coordinator(runtime, device_types, reconciled_timeout)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}

    async def transitioned_refresh():
        coordinator.data["battery_test_status"] = 1

    coordinator.async_request_refresh = transitioned_refresh
    await coordinator.async_execute_write(
        support.WriteOperation.BATTERY_TEST_START.value
    )
    assert reconciled_timeout.calls == 1
    assert not coordinator._write_outcomes_unknown

    not_connected = FakeClient(connect=False)
    coordinator = _coordinator(runtime, device_types, not_connected)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}
    with pytest.raises(errors.HomeAssistantError) as caught:
        await coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        )
    assert caught.value.translation_key == "write_not_sent"
    assert not_connected.calls == 0


async def _write_serialization_one_request_and_response_mismatch(monkeypatch):
    runtime, device_types, errors, _ = _load_runtime(monkeypatch)
    support = importlib.import_module("write_runtime.write_support")
    client = FakeClient()
    coordinator = _coordinator(runtime, device_types, client)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}
    assert coordinator.write_operation_available(
        support.WriteOperation.BATTERY_TEST_START.value
    )
    coordinator._write_pending.add("battery_test")
    assert not coordinator.write_operation_available(
        support.WriteOperation.BATTERY_TEST_START.value
    )
    coordinator._write_pending.clear()
    coordinator._write_outcomes_unknown["battery_test"] = (
        support.WriteOperation.BATTERY_TEST_START.value,
        None,
        0,
    )
    assert not coordinator.write_operation_available(
        support.WriteOperation.BATTERY_TEST_START.value
    )
    coordinator._write_outcomes_unknown.clear()

    async def refresh():
        await asyncio.sleep(0.02)
        coordinator.data["battery_test_status"] = 1

    coordinator.async_request_refresh = refresh
    results = await asyncio.gather(
        coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        ),
        coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        ),
        return_exceptions=True,
    )
    assert client.calls == 1 and client.max_active == 1
    assert sum(result is None for result in results) == 1
    assert (
        sum(isinstance(result, errors.ServiceValidationError) for result in results)
        == 1
    )

    client = FakeClient()
    coordinator = _coordinator(runtime, device_types, client)
    coordinator.transport_mode = "one_request_per_connection"
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}

    async def one_request_refresh():
        coordinator.data["battery_test_status"] = 1

    coordinator.async_request_refresh = one_request_refresh
    await coordinator.async_execute_write(
        support.WriteOperation.BATTERY_TEST_START.value
    )
    assert client.calls == 1 and client.closed == 1

    bad = FakeClient(response=SimpleNamespace(address=0x0605, registers=[2], retries=0))
    coordinator = _coordinator(runtime, device_types, bad)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}

    async def unchanged_refresh():
        pass

    coordinator.async_request_refresh = unchanged_refresh
    with pytest.raises(errors.HomeAssistantError) as caught:
        await coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        )
    assert caught.value.translation_key == "write_outcome_unknown"
    assert bad.calls == 1

    mismatched_but_reconciled = FakeClient(
        response=SimpleNamespace(address=0x0605, registers=[2], retries=0)
    )
    coordinator = _coordinator(runtime, device_types, mismatched_but_reconciled)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}

    async def mismatch_transition_refresh():
        coordinator.data["battery_test_status"] = 1

    coordinator.async_request_refresh = mismatch_transition_refresh
    await coordinator.async_execute_write(
        support.WriteOperation.BATTERY_TEST_START.value
    )
    assert mismatched_but_reconciled.calls == 1

    unchanged = FakeClient()
    coordinator = _coordinator(runtime, device_types, unchanged)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}
    coordinator.async_request_refresh = unchanged_refresh
    with pytest.raises(errors.HomeAssistantError) as caught:
        await coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        )
    assert caught.value.translation_key == "write_outcome_unknown"
    with pytest.raises(errors.ServiceValidationError) as caught:
        await coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        )
    assert caught.value.translation_key == "write_outcome_unresolved"
    assert unchanged.calls == 1
    coordinator._clear_reconciled_unknown_writes({"battery_test_status": 1})
    assert not coordinator._write_outcomes_unknown

    refresh_failure = FakeClient()
    coordinator = _coordinator(runtime, device_types, refresh_failure)
    coordinator.write_capabilities = {support.WriteCapability.BATTERY_TEST.value}
    coordinator.data = {"battery_test_status": 0}

    async def broken_refresh():
        raise RuntimeError("unexpected refresh failure")

    coordinator.async_request_refresh = broken_refresh
    with pytest.raises(errors.HomeAssistantError) as caught:
        await coordinator.async_execute_write(
            support.WriteOperation.BATTERY_TEST_START.value
        )
    assert caught.value.translation_key == "write_outcome_unknown"
    assert refresh_failure.calls == 1
    assert coordinator._write_outcomes_unknown


async def _discovery_is_per_feature_and_never_reads_command_region(monkeypatch):
    runtime, device_types, _, _ = _load_runtime(monkeypatch)
    support = importlib.import_module("write_runtime.write_support")
    device = sys.modules["write_runtime.device_types"]
    coordinator = _coordinator(runtime, device_types, FakeClient())
    coordinator.write_supported_models = frozenset({("SMT1500", (9, 0))})
    assert await coordinator.async_discover_write_capabilities() == set()
    assert coordinator.write_capability_unresolved == {
        capability.value for capability in support.WriteCapability
    }
    assert support.write_entity_unique_ids(
        "entry", coordinator.write_capability_unresolved
    )

    coordinator.raw_modbus_model = "SMT1500"
    coordinator.raw_modbus_firmware = "UPS 9.0"
    seen = []

    values = {
        0x0800: (0x4D41, 0x5031),
        **support.PROTOCOL_TESTS,
        0x024E: (0x000F,),
        0x0003: (0, 1),
        0x0006: (0, 2),
        0x0009: (0, 1),
        0x000C: (0, 2),
        0x0017: (0,),
        0x0018: (0,),
        0x001A: (0,),
        0x0405: (0, 0, 0, 8, 0),
        0x040A: (0, 0, 0, 8, 0),
        0x040F: (0, 0, 0, 8, 0),
        0x0414: (0, 0, 0, 8, 0),
    }

    async def probe(address, count, name):
        seen.append(address)
        registers = values[address]
        assert len(registers) == count
        return device.ProbeOutcome(device.ProbeKind.RESPONSE, registers)

    async def connected():
        return True

    coordinator._probe_write_evidence = probe
    coordinator._ensure_connection = connected
    capabilities = await coordinator.async_discover_write_capabilities()
    assert {capability.value for capability in support.WriteCapability} == capabilities
    assert not (set(seen) & support.COMMAND_ADDRESSES)
    assert coordinator.modbus_map_id == "MAP1"

    coordinator.set_device_type(device_types.APCDeviceType.SMARTCONNECT_UPS)
    assert await coordinator.async_discover_write_capabilities() == capabilities

    async def mixed_probe(address, count, name):
        seen.append(address)
        if address == 0x0017:
            return device.ProbeOutcome(
                device.ProbeKind.MODBUS_EXCEPTION, exception_code=2
            )
        if address == 0x0018:
            return device.ProbeOutcome(device.ProbeKind.TRANSPORT_FAILURE)
        return await probe(address, count, name)

    coordinator._probe_write_evidence = mixed_probe
    capabilities = await coordinator.async_discover_write_capabilities()
    assert support.WriteCapability.BATTERY_TEST.value not in capabilities
    assert support.WriteCapability.RUNTIME_CALIBRATION.value not in capabilities
    assert coordinator.write_capability_outcomes[
        support.WriteCapability.BATTERY_TEST.value
    ].unsupported
    assert (
        coordinator.write_capability_outcomes[
            support.WriteCapability.RUNTIME_CALIBRATION.value
        ].kind
        == device.ProbeKind.TRANSPORT_FAILURE
    )

    async def invalid_probe(address, count, name):
        seen.append(address)
        invalid = {
            0x024E: (0xFFFF,),
            0x0003: (0xFFFF, 0xFFFF),
            0x0017: (0xFFFF,),
            0x0405: (0xFFFF, 0, 0, 8, 0),
            0x040A: (0, 0, 0xFFFF, 0xFFFF, 0),
        }
        registers = invalid.get(address, values[address])
        return device.ProbeOutcome(device.ProbeKind.RESPONSE, registers)

    coordinator._probe_write_evidence = invalid_probe
    await coordinator.async_discover_write_capabilities()
    for capability in (
        support.WriteCapability.OUTLET_MOG,
        support.WriteCapability.BATTERY_TEST,
        support.WriteCapability.OUTLET_SETTINGS_MOG,
        support.WriteCapability.OUTLET_SETTINGS_SOG_0,
    ):
        assert capability.value in coordinator.write_capability_unresolved
        assert capability.value not in coordinator.write_capabilities
    preserved = support.write_entity_unique_ids(
        "entry", coordinator.write_capability_unresolved
    )
    assert "apc_modbus_entry_write_battery_test_start" in preserved
    assert "apc_modbus_entry_write_outlet_mog" in preserved

    coordinator.write_supported_models = frozenset()
    seen.clear()
    assert await coordinator.async_discover_write_capabilities() == set()
    assert seen == []


async def _initial_and_recreated_clients_have_zero_retries(monkeypatch):
    runtime, device_types, _, recreated = _load_runtime(monkeypatch)
    initial = runtime.create_modbus_client("ups", 502, 5)
    assert initial.host == "ups"
    assert initial.port == 502
    assert initial.timeout == 5
    assert initial.retries == 0
    coordinator = _coordinator(runtime, device_types, FakeClient())
    await coordinator._recreate_client()
    assert recreated.created[-1]["retries"] == 0


def test_success_timeout_and_connect_failure_never_replay(monkeypatch):
    asyncio.run(_success_timeout_and_connect_failure_never_replay(monkeypatch))


def test_write_serialization_one_request_and_response_mismatch(monkeypatch):
    asyncio.run(_write_serialization_one_request_and_response_mismatch(monkeypatch))


def test_discovery_is_per_feature_and_never_reads_command_region(monkeypatch):
    asyncio.run(_discovery_is_per_feature_and_never_reads_command_region(monkeypatch))


def test_initial_and_recreated_clients_have_zero_retries(monkeypatch):
    asyncio.run(_initial_and_recreated_clients_have_zero_retries(monkeypatch))


def test_reboot_reconciliation_requires_process_or_off_phase(monkeypatch):
    runtime, _, _, _ = _load_runtime(monkeypatch)
    support = importlib.import_module("write_runtime.write_support")
    operation = support.WriteOperation.OUTLET.value
    target = f"{support.OutletTarget.MOG.value}:{support.OutletAction.REBOOT.value}"
    assert not runtime.APCModbusCoordinator._write_status_reconciled(
        operation,
        target,
        1,
        {"outlet_status_mog": 1 | (1 << 14)},
    )
    assert runtime.APCModbusCoordinator._write_status_reconciled(
        operation, target, 1, {"outlet_status_mog": 1 | (1 << 2)}
    )
    assert runtime.APCModbusCoordinator._write_status_reconciled(
        operation, target, 1, {"outlet_status_mog": 2}
    )


def test_write_unit_id_signatures_are_resolved_independently(monkeypatch):
    runtime, device_types, _, _ = _load_runtime(monkeypatch)

    class SignatureClient(FakeClient):
        def write_register(
            self, address, value, *, slave=1, no_response_expected=False
        ):
            self.single_unit = slave
            return SimpleNamespace(address=address, registers=[value], retries=0)

        def write_registers(
            self, address, values, *, unit=1, no_response_expected=False
        ):
            self.multiple_unit = unit
            return SimpleNamespace(address=address, count=len(values), retries=0)

    client = SignatureClient()
    coordinator = _coordinator(runtime, device_types, client)
    assert coordinator._write_registers_compat(0x0605, (1,), [False]).address == 0x0605
    assert coordinator._write_registers_compat(0x0602, (2, 0x0102), [False]).count == 2
    assert client.single_unit == 1 and client.multiple_unit == 1
    assert coordinator._resolved_write_call == {
        "write_register": ("keyword", "slave"),
        "write_registers": ("keyword", "unit"),
    }

    class PositionalClient(FakeClient):
        def write_register(self, address, value, device_id, /):
            self.single_unit = device_id
            return SimpleNamespace(address=address, registers=[value], retries=0)

    client = PositionalClient()
    coordinator = _coordinator(runtime, device_types, client)
    coordinator._write_registers_compat(0x0605, (1,), [False])
    assert client.single_unit == 1
    assert coordinator._resolved_write_call["write_register"] == (
        "positional",
        None,
    )

    class NoUnitClient(FakeClient):
        def write_register(self, address, value):
            self.payload = (address, value)
            return SimpleNamespace(address=address, registers=[value], retries=0)

    client = NoUnitClient()
    coordinator = _coordinator(runtime, device_types, client)
    coordinator._write_registers_compat(0x0605, (1,), [False])
    assert client.payload == (0x0605, 1)
    assert coordinator._resolved_write_call["write_register"] == ("none", None)

    client = FakeClient()
    coordinator = _coordinator(runtime, device_types, client)
    coordinator._write_registers_compat(0x0605, (1,), [False])
    assert coordinator._resolved_write_call["write_register"] == (
        "keyword",
        "device_id",
    )


def test_register_factory_gates_smartconnect_write_companions(monkeypatch):
    package = ModuleType("factory_runtime")
    package.__path__ = [str(PACKAGE_PATH)]
    monkeypatch.setitem(sys.modules, "factory_runtime", package)
    device_spec = importlib.util.spec_from_file_location(
        "factory_runtime.device_types", PACKAGE_PATH / "device_types.py"
    )
    assert device_spec and device_spec.loader
    device_types = importlib.util.module_from_spec(device_spec)
    monkeypatch.setitem(sys.modules, device_spec.name, device_types)
    device_spec.loader.exec_module(device_types)
    legacy = ModuleType("factory_runtime.registers_smart_ups")
    legacy.REGISTERS, legacy.REGISTER_BLOCKS, legacy.REGISTER_MAP = (
        ["legacy"],
        ["legacy"],
        {1: "legacy"},
    )
    smt = ModuleType("factory_runtime.registers_smt_ups")
    smt.REGISTERS, smt.REGISTER_BLOCKS, smt.REGISTER_MAP = (
        ["read"],
        ["read"],
        {1: "read"},
    )
    smt.WRITABLE_REGISTERS = ["write"]
    smt.WRITABLE_REGISTER_BLOCKS = ["write"]
    smt.WRITABLE_REGISTER_MAP = {1: "write"}
    monkeypatch.setitem(sys.modules, "factory_runtime.registers_smart_ups", legacy)
    monkeypatch.setitem(sys.modules, "factory_runtime.registers_smt_ups", smt)
    spec = importlib.util.spec_from_file_location(
        "factory_runtime.register_factory", PACKAGE_PATH / "register_factory.py"
    )
    assert spec and spec.loader
    factory = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, factory)
    spec.loader.exec_module(factory)
    assert factory.get_registers_for_device(device_types.APCDeviceType.SMT_UPS)[0] == [
        "write"
    ]
    assert factory.get_registers_for_device(
        device_types.APCDeviceType.SMARTCONNECT_UPS
    )[0] == ["read"]
    assert factory.get_registers_for_device(
        device_types.APCDeviceType.SMARTCONNECT_UPS, write_companions=True
    )[0] == ["write"]
    assert factory.get_registers_for_device(device_types.APCDeviceType.SMART_UPS)[
        0
    ] == ["legacy"]


def test_real_profiles_isolate_writable_status_from_address_collisions(monkeypatch):
    package = ModuleType("profile_runtime")
    package.__path__ = [str(PACKAGE_PATH)]
    monkeypatch.setitem(sys.modules, "profile_runtime", package)

    homeassistant = ModuleType("homeassistant")
    components = ModuleType("homeassistant.components")
    binary_sensor = ModuleType("homeassistant.components.binary_sensor")
    binary_sensor.BinarySensorDeviceClass = SimpleNamespace(
        BATTERY="battery", POWER="power", PROBLEM="problem"
    )
    sensor = ModuleType("homeassistant.components.sensor")
    sensor.SensorDeviceClass = SimpleNamespace(
        BATTERY="battery",
        CURRENT="current",
        DURATION="duration",
        ENERGY="energy",
        ENUM="enum",
        FREQUENCY="frequency",
        TEMPERATURE="temperature",
        VOLTAGE="voltage",
    )
    sensor.SensorStateClass = SimpleNamespace(
        MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing"
    )
    ha_const = ModuleType("homeassistant.const")
    ha_const.EntityCategory = SimpleNamespace(DIAGNOSTIC="diagnostic")
    ha_const.PERCENTAGE = "%"
    for class_name, attributes in {
        "UnitOfElectricCurrent": {"AMPERE": "A"},
        "UnitOfElectricPotential": {"VOLT": "V"},
        "UnitOfEnergy": {"KILO_WATT_HOUR": "kWh"},
        "UnitOfFrequency": {"HERTZ": "Hz"},
        "UnitOfTemperature": {"CELSIUS": "C"},
        "UnitOfTime": {"MINUTES": "min", "SECONDS": "s"},
    }.items():
        setattr(ha_const, class_name, SimpleNamespace(**attributes))
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.binary_sensor", binary_sensor
    )
    monkeypatch.setitem(sys.modules, "homeassistant.components.sensor", sensor)
    monkeypatch.setitem(sys.modules, "homeassistant.const", ha_const)

    class Description:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    const = ModuleType("profile_runtime.const")
    const.APCModbusBinarySensorDescription = Description
    const.APCModbusSensorDescription = Description
    monkeypatch.setitem(sys.modules, "profile_runtime.const", const)

    modules = {}
    for name in ("registers_smart_ups", "registers_smt_ups"):
        spec = importlib.util.spec_from_file_location(
            f"profile_runtime.{name}", PACKAGE_PATH / f"{name}.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        modules[name] = module

    legacy = modules["registers_smart_ups"]
    smt = modules["registers_smt_ups"]
    write_addresses = {0x0003, 0x0006, 0x0009, 0x000C, 0x0017, 0x0018, 0x001A, 0x024E}
    assert not (write_addresses & set(smt.REGISTER_MAP))
    assert write_addresses <= set(smt.WRITABLE_REGISTER_MAP)
    assert {
        address: smt.WRITABLE_REGISTER_MAP[address]["count"]
        for address in write_addresses
    } == {
        0x0003: 2,
        0x0006: 2,
        0x0009: 2,
        0x000C: 2,
        0x0017: 1,
        0x0018: 1,
        0x001A: 1,
        0x024E: 1,
    }
    assert legacy.REGISTER_MAP[0x0017]["key"] == "measure_ups_contact_position"
    assert 0x0018 not in legacy.REGISTER_MAP
    assert legacy.REGISTER_MAP[0x001A]["key"] == "minimum_return_battery_capacity"
    assert 0x024E not in legacy.REGISTER_MAP
    assert {
        address: legacy.REGISTER_MAP[address]["key"]
        for address in (0x0003, 0x0006, 0x0009, 0x000C)
    } == {
        0x0003: "status_word_3",
        0x0006: "runtime_remaining",
        0x0009: "load_amps",
        0x000C: "load_percent",
    }


def test_scoped_stale_cleanup_preserves_unresolved_write_entities(monkeypatch):
    package_name = "setup_runtime"
    spec = importlib.util.spec_from_file_location(
        package_name,
        PACKAGE_PATH / "__init__.py",
        submodule_search_locations=[str(PACKAGE_PATH)],
    )
    assert spec and spec.loader

    pymodbus = ModuleType("pymodbus")
    pymodbus.__version__ = "test"
    monkeypatch.setitem(sys.modules, "pymodbus", pymodbus)

    homeassistant = ModuleType("homeassistant")
    config_entries = ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    exceptions = ModuleType("homeassistant.exceptions")
    exceptions.ConfigEntryNotReady = RuntimeError
    helpers = ModuleType("homeassistant.helpers")
    entity_registry = ModuleType("homeassistant.helpers.entity_registry")
    ha_const = ModuleType("homeassistant.const")
    ha_const.CONF_HOST = "host"
    ha_const.CONF_PORT = "port"
    ha_const.CONF_SCAN_INTERVAL = "scan_interval"
    for name, module in (
        ("homeassistant", homeassistant),
        ("homeassistant.config_entries", config_entries),
        ("homeassistant.core", core),
        ("homeassistant.exceptions", exceptions),
        ("homeassistant.helpers", helpers),
        ("homeassistant.helpers.entity_registry", entity_registry),
        ("homeassistant.const", ha_const),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    const = ModuleType(f"{package_name}.const")
    imported_constants = {
        "CONF_DETECTION_VERSION",
        "CONF_DEVICE_NAME",
        "CONF_DEVICE_TYPE",
        "CONF_KEEP_CONNECTION_OPEN",
        "CONF_TRANSPORT_MODE",
        "CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS",
        "CONF_SNMP_COMMUNITY",
        "CONF_SNMP_PORT",
        "CONF_UNIT",
        "DEFAULT_KEEP_CONNECTION_OPEN",
        "DEFAULT_NAME",
        "DEFAULT_PORT",
        "DEFAULT_SCAN_INTERVAL",
        "DEFAULT_SNMP_COMMUNITY",
        "DEFAULT_SNMP_PORT",
        "DEFAULT_UNIT",
        "KEY_CLIENT",
        "KEY_COORDINATOR",
    }
    for name in imported_constants:
        setattr(const, name, name.lower())
    const.DOMAIN = "apc_modbus"
    const.SUPPORTED_PLATFORMS = []
    const.SNMP_EXTERNAL_SENSOR_DESCRIPTIONS = []
    monkeypatch.setitem(sys.modules, f"{package_name}.const", const)

    coordinator_module = ModuleType(f"{package_name}.coordinator")
    coordinator_module.APCModbusCoordinator = object
    coordinator_module.create_modbus_client = lambda *args: None
    monkeypatch.setitem(sys.modules, f"{package_name}.coordinator", coordinator_module)

    device_types = ModuleType(f"{package_name}.device_types")

    class DeviceType(StrEnum):
        SMART_UPS = "smart_ups"
        SMT_UPS = "smt_ups"
        SMARTCONNECT_UPS = "smartconnect_ups"
        RACK_PDU = "rack_pdu"

    device_types.APCDeviceType = DeviceType
    device_types.DETECTION_VERSION = 4
    device_types.choose_device_type = lambda **kwargs: None
    device_types.is_concrete_device_type = lambda value: True
    device_types.should_probe_device_type = lambda *args: False
    monkeypatch.setitem(sys.modules, f"{package_name}.device_types", device_types)

    registers = ModuleType(f"{package_name}.registers_smt_ups")
    registers.SENSOR_DESCRIPTIONS = [SimpleNamespace(key="output_voltage")]
    registers.BINARY_SENSOR_DESCRIPTIONS = []
    monkeypatch.setitem(sys.modules, f"{package_name}.registers_smt_ups", registers)
    for module_name, attributes in {
        "external_probe_entities": {
            "filter_available_external_probe_keys": lambda keys, *args: keys
        },
        "register_factory": {"get_registers_for_device": lambda *args: ()},
        "scan_interval_guard": {
            "compute_effective_scan_interval": lambda value, count: value
        },
        "snmp_helper": {
            "detect_device_type": lambda *args: None,
            "get_device_metadata_sync": lambda *args: None,
        },
        "startup_stagger": {"compute_startup_stagger_delay": lambda *args: 0},
    }.items():
        module = ModuleType(f"{package_name}.{module_name}")
        for name, value in attributes.items():
            setattr(module, name, value)
        monkeypatch.setitem(sys.modules, f"{package_name}.{module_name}", module)

    runtime = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, package_name, runtime)
    spec.loader.exec_module(runtime)

    entries = [
        SimpleNamespace(
            entity_id="button.keep_unresolved",
            domain="button",
            unique_id="apc_modbus_entry_write_battery_test_start",
        ),
        SimpleNamespace(
            entity_id="sensor.keep_unresolved",
            domain="sensor",
            unique_id="apc_modbus_entry_battery_test_operation_state",
        ),
        SimpleNamespace(
            entity_id="button.remove_unsupported",
            domain="button",
            unique_id="apc_modbus_entry_write_calibration_start",
        ),
        SimpleNamespace(
            entity_id="sensor.remove_unsupported",
            domain="sensor",
            unique_id="apc_modbus_entry_runtime_calibration_operation_state",
        ),
        SimpleNamespace(
            entity_id="button.keep_unrelated",
            domain="button",
            unique_id="apc_modbus_entry_run_diagnostics",
        ),
    ]

    class Registry:
        def __init__(self):
            self.removed = []

        def async_remove(self, entity_id):
            self.removed.append(entity_id)

    registry = Registry()
    entity_registry.async_get = lambda hass: registry
    entity_registry.async_entries_for_config_entry = lambda reg, entry_id: entries
    coordinator = SimpleNamespace(
        device_type=DeviceType.SMT_UPS,
        write_capabilities=set(),
        write_capability_unresolved={"battery_test"},
        snmp_availability="unavailable",
        data={},
        _snmp_probe_detection={},
    )
    asyncio.run(
        runtime._async_cleanup_stale_entities(
            object(), SimpleNamespace(entry_id="entry"), coordinator
        )
    )
    assert registry.removed == [
        "button.remove_unsupported",
        "sensor.remove_unsupported",
    ]
