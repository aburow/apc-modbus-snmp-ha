"""Native Home Assistant entity contract tests using lightweight stubs."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from enum import StrEnum

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "custom_components/apc_modbus"


def _load_entities(monkeypatch: pytest.MonkeyPatch):
    package = ModuleType("entity_runtime")
    package.__path__ = [str(PACKAGE_PATH)]
    monkeypatch.setitem(sys.modules, "entity_runtime", package)

    homeassistant = ModuleType("homeassistant")
    components = ModuleType("homeassistant.components")
    switch = ModuleType("homeassistant.components.switch")
    button = ModuleType("homeassistant.components.button")
    logbook = ModuleType("homeassistant.components.logbook")
    sensor = ModuleType("homeassistant.components.sensor")
    notification = ModuleType("homeassistant.components.persistent_notification")

    class SwitchEntity:
        pass

    class ButtonEntity:
        pass

    class SensorEntity:
        pass

    switch.SwitchEntity = SwitchEntity
    switch.SwitchDeviceClass = SimpleNamespace(OUTLET="outlet")
    button.ButtonEntity = ButtonEntity
    logbook.entries = []

    def async_log_entry(*args, **kwargs):
        logbook.entries.append((args, kwargs))

    logbook.async_log_entry = async_log_entry
    sensor.SensorEntity = SensorEntity
    sensor.SensorDeviceClass = SimpleNamespace(ENUM="enum", ENERGY="energy")
    notification.async_create = lambda *args, **kwargs: None
    config_entries = ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    const_ha = ModuleType("homeassistant.const")
    const_ha.CONF_SCAN_INTERVAL = "scan_interval"
    helpers = ModuleType("homeassistant.helpers")
    registry = ModuleType("homeassistant.helpers.device_registry")
    registry.DeviceInfo = dict
    platform = ModuleType("homeassistant.helpers.entity_platform")
    platform.AddEntitiesCallback = object
    coordinator_module = ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator
            self.hass = coordinator.hass

        def _handle_coordinator_update(self):
            pass

        @property
        def available(self):
            return self.coordinator.last_update_success

    coordinator_module.CoordinatorEntity = CoordinatorEntity
    for name, module in (
        ("homeassistant", homeassistant),
        ("homeassistant.components", components),
        ("homeassistant.components.switch", switch),
        ("homeassistant.components.button", button),
        ("homeassistant.components.logbook", logbook),
        ("homeassistant.components.sensor", sensor),
        ("homeassistant.components.persistent_notification", notification),
        ("homeassistant.config_entries", config_entries),
        ("homeassistant.core", core),
        ("homeassistant.const", const_ha),
        ("homeassistant.helpers", helpers),
        ("homeassistant.helpers.device_registry", registry),
        ("homeassistant.helpers.entity_platform", platform),
        ("homeassistant.helpers.update_coordinator", coordinator_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    const = ModuleType("entity_runtime.const")
    for name, value in {
        "CONF_DETECTION_VERSION": "detection_version",
        "CONF_DEVICE_TYPE": "device_type",
        "CONF_KEEP_CONNECTION_OPEN": "keep_connection_open",
        "CONF_SNMP_PORT": "snmp_port",
        "DEFAULT_SCAN_INTERVAL": 10,
        "DEFAULT_SNMP_PORT": 161,
        "DOMAIN": "apc_modbus",
        "KEY_COORDINATOR": "coordinator",
        "APCModbusSensorDescription": object,
        "SNMP_EXTERNAL_SENSOR_DESCRIPTIONS": [],
        "SNMP_SELF_TEST_SENSOR_DESCRIPTIONS": [],
    }.items():
        setattr(const, name, value)
    monkeypatch.setitem(sys.modules, "entity_runtime.const", const)
    coordinator_stub = ModuleType("entity_runtime.coordinator")
    coordinator_stub.APCModbusCoordinator = object
    monkeypatch.setitem(sys.modules, "entity_runtime.coordinator", coordinator_stub)
    device_types = ModuleType("entity_runtime.device_types")
    device_types.DETECTION_VERSION = 4
    device_types.choose_device_type = lambda **kwargs: kwargs.get("stored_device_type")
    device_types.device_type_label = lambda value: str(value)

    class APCDeviceType(StrEnum):
        SMART_UPS = "smart_ups"
        SMT_UPS = "smt_ups"
        SMARTCONNECT_UPS = "smartconnect_ups"
        RACK_PDU = "rack_pdu"

    device_types.APCDeviceType = APCDeviceType
    monkeypatch.setitem(sys.modules, "entity_runtime.device_types", device_types)
    diagnostics = ModuleType("entity_runtime.diagnostic_collector")
    diagnostics.collect_diagnostic_dump = lambda *args: {}
    monkeypatch.setitem(sys.modules, "entity_runtime.diagnostic_collector", diagnostics)
    defaults = ModuleType("entity_runtime.entity_defaults")

    async def reset(*args, **kwargs):
        return (0, 0, 0)

    defaults.async_reset_entry_monitors_to_defaults = reset
    monkeypatch.setitem(sys.modules, "entity_runtime.entity_defaults", defaults)
    external = ModuleType("entity_runtime.external_probe_entities")
    external.is_external_probe_entity_available = lambda *args: True
    monkeypatch.setitem(sys.modules, "entity_runtime.external_probe_entities", external)
    icons = ModuleType("entity_runtime.icons_unified")
    icons.resolve_sensor_icon = lambda key: None
    monkeypatch.setitem(sys.modules, "entity_runtime.icons_unified", icons)
    availability = ModuleType("entity_runtime.sensor_availability_unified")
    availability.is_sensor_enabled_by_default = lambda *args: True
    monkeypatch.setitem(
        sys.modules, "entity_runtime.sensor_availability_unified", availability
    )

    def operation_description(key, options):
        return SimpleNamespace(
            key=key,
            translation_key=key,
            device_class="enum",
            entity_category="diagnostic",
            entity_registry_enabled_default=False,
            options=options,
            register_key=key,
            value_map=None,
            suggested_display_precision=None,
        )

    registers_smt = ModuleType("entity_runtime.registers_smt_ups")
    registers_smt.SENSOR_DESCRIPTIONS = []
    registers_smt.SMARTCONNECT_SENSOR_DESCRIPTIONS = []
    result_options = [
        "unknown",
        "pending",
        "in_progress",
        "passed",
        "failed",
        "refused",
        "aborted",
    ]
    registers_smt.WRITE_SENSOR_DESCRIPTIONS = {
        "battery_test": operation_description(
            "battery_test_operation_state", result_options
        ),
        "runtime_calibration": operation_description(
            "runtime_calibration_operation_state", result_options
        ),
        **{
            f"outlet_{target}": operation_description(
                f"outlet_{target}_operation_state",
                ["unknown", "on", "off", "pending", "reboot", "shutdown", "sleep"],
            )
            for target in ("mog", "sog_0", "sog_1", "sog_2")
        },
    }
    monkeypatch.setitem(sys.modules, "entity_runtime.registers_smt_ups", registers_smt)

    modules = []
    for name in ("switch", "button", "sensor"):
        spec = importlib.util.spec_from_file_location(
            f"entity_runtime.{name}", PACKAGE_PATH / f"{name}.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        modules.append(module)
    return (*modules, importlib.import_module("entity_runtime.write_support"))


class Coordinator:
    def __init__(self, support):
        self.hass = SimpleNamespace(config_entries=SimpleNamespace())
        self.device_name = "UPS"
        self._log_ctx = "UPS ups:502 (unit 1)"
        self.serial_number = "serial"
        self.last_update_success = True
        self.keep_connection_open_enabled = False
        self.device_type = SimpleNamespace(value="smt_ups")
        self.snmp_availability = "unavailable"
        self.fw_version = "9.0"
        self.fw_date = None
        self._snmp_probe_detection = {}
        self.write_capabilities = {
            capability.value
            for capability in support.WriteCapability
            if "settings" not in capability.value
        }
        self.data = {
            "outlet_status_mog": 1,
            "outlet_status_sog_0": 2,
            "outlet_status_sog_1": 2,
            "outlet_status_sog_2": 2,
            "battery_test_status": 0,
            "runtime_calibration_status": 0,
            "user_interface_status": 2,
            "battery_test_operation_state": "refused",
            "runtime_calibration_operation_state": "aborted",
            "outlet_mog_operation_state": "on",
            "outlet_sog_0_operation_state": "off",
            "outlet_sog_1_operation_state": "pending",
            "outlet_sog_2_operation_state": "shutdown",
        }
        self.calls = []
        self._write_pending = set()
        self._write_outcomes_unknown = {}
        self.write_hook = None
        self._io_lock = _unlocked()
        self.host = "192.0.2.1"
        self.snmp_community = "public"
        self.port = 502
        self.unit = 1
        self.transport_mode = "session"
        self.transport_promotion_reason = None

    def get_device_model_for_registry(self):
        return "SMT1500"

    def get_configuration_url_for_registry(self):
        return "http://ups"

    def _write_precondition(self, operation, target):
        if operation.endswith("abort"):
            return "operation_not_active"
        if target and target.endswith(":cancel"):
            return "outlet_nothing_to_cancel"
        return None

    def write_operation_available(self, operation, target=None):
        if operation == "outlet":
            pending_key = f"outlet:{target.split(':', 1)[0]}"
        elif operation.startswith("alarm_"):
            pending_key = "audible_alarm"
        else:
            pending_key = operation.split("_start", 1)[0].split("_abort", 1)[0]
        return bool(
            self._write_precondition(operation, target) is None
            and pending_key not in self._write_pending
            and pending_key not in self._write_outcomes_unknown
        )

    async def async_execute_write(self, operation, target=None):
        self.calls.append((operation, target))
        if self.write_hook:
            await self.write_hook()

    def async_add_listener(self, callback):
        return callback


class Hass:
    def __init__(self, coordinator):
        self.data = {"apc_modbus": {"entry": {"coordinator": coordinator}}}
        self.executor_hook = None

    async def async_add_executor_job(self, target, *args):
        if self.executor_hook:
            self.executor_hook()
        return target(*args)


@asynccontextmanager
async def _unlocked():
    yield


def _collect_setup(module, hass, entry):
    entities = []

    def add(values):
        entities.extend(list(values))

    asyncio.run(module.async_setup_entry(hass, entry, add))
    return entities


def test_native_write_entities_are_capability_filtered_and_disabled(monkeypatch):
    switch, button, sensor, support = _load_entities(monkeypatch)
    coordinator = Coordinator(support)
    hass = Hass(coordinator)
    coordinator.hass = hass
    entry = SimpleNamespace(entry_id="entry", data={})

    switches = _collect_setup(switch, hass, entry)
    outlet = next(
        entity
        for entity in switches
        if isinstance(entity, switch.APCModbusOutletSwitch)
    )
    alarm = next(
        entity
        for entity in switches
        if isinstance(entity, switch.APCModbusAlarmMuteSwitch)
    )
    assert len(switches) == 6  # existing connection switch + four outlets + alarm
    assert outlet._attr_device_class == "outlet"
    assert outlet._attr_entity_registry_enabled_default is False
    assert outlet._attr_unique_id == "apc_modbus_entry_write_outlet_mog"
    assert outlet.is_on and outlet.available
    assert not alarm.is_on and alarm.available
    asyncio.run(alarm.async_turn_on())
    assert coordinator.calls[-1] == (support.WriteOperation.ALARM_MUTE.value, None)

    buttons = _collect_setup(button, hass, entry)
    write_buttons = [
        entity for entity in buttons if isinstance(entity, button.APCModbusWriteButton)
    ]
    assert len(buttons) == 19  # three existing diagnostics + sixteen write buttons
    assert len(write_buttons) == 16
    assert all(
        entity._attr_entity_registry_enabled_default is False
        for entity in write_buttons
    )
    assert len({entity._attr_unique_id for entity in write_buttons}) == 16
    abort = next(
        entity
        for entity in write_buttons
        if entity._operation.value == "battery_test_abort"
    )
    start = next(
        entity
        for entity in write_buttons
        if entity._operation.value == "battery_test_start"
    )
    cancel = next(entity for entity in write_buttons if entity._target == "mog:cancel")
    assert start.available and not abort.available and not cancel.available
    coordinator._write_pending.add("battery_test")
    assert not start.available
    coordinator._write_pending.clear()
    coordinator._write_outcomes_unknown["battery_test"] = object()
    assert not start.available
    coordinator._write_outcomes_unknown.clear()
    coordinator._write_pending.update({"outlet:mog", "audible_alarm"})
    assert not outlet.available and not alarm.available
    coordinator._write_pending.clear()
    asyncio.run(start.async_press())
    assert coordinator.calls[-1] == (
        support.WriteOperation.BATTERY_TEST_START.value,
        None,
    )
    start.name = "Start battery self-test"
    start.entity_id = "button.ups_start_battery_self_test"
    start._context = object()
    start._mark_restoration_candidate()
    coordinator.data["battery_test_operation_state"] = "pending"
    coordinator._write_pending.add("battery_test")
    start._handle_coordinator_update()
    assert sys.modules["homeassistant.components.logbook"].entries == []
    coordinator._write_pending.clear()
    coordinator.data["battery_test_operation_state"] = "passed"
    start._handle_coordinator_update()
    log_entry = sys.modules["homeassistant.components.logbook"].entries[0]
    assert log_entry[0][1:3] == (
        "Start battery self-test",
        "Control restored to available; this is not another press. "
        "Terminal status: Passed.",
    )
    start._handle_coordinator_update()
    assert len(sys.modules["homeassistant.components.logbook"].entries) == 1
    diagnostics = next(
        entity
        for entity in buttons
        if isinstance(entity, button.APCModbusDiagnosticButton)
    )
    diagnostics.name = "Run Diagnostics"
    diagnostics.entity_id = "button.ups_run_diagnostics"
    diagnostics._context = object()
    diagnostics._mark_restoration_candidate()
    coordinator.last_update_success = False
    diagnostics._handle_coordinator_update()
    coordinator.last_update_success = True
    diagnostics._handle_coordinator_update()
    utility_entry = sys.modules["homeassistant.components.logbook"].entries[1]
    assert utility_entry[0][1:3] == (
        "Run Diagnostics",
        "Control restored to available; this is not another press.",
    )
    notifications = []
    monkeypatch.setattr(
        button,
        "async_create",
        lambda _hass, message, **kwargs: notifications.append((message, kwargs)),
    )

    async def snmp_retry():
        return False

    async def detect_type():
        return None

    async def refresh():
        return None

    coordinator.async_retry_snmp_metadata = snmp_retry
    coordinator.async_detect_device_type = detect_type
    coordinator.async_request_refresh = refresh
    redetect = next(
        entity
        for entity in buttons
        if isinstance(entity, button.APCModbusRedetectDeviceTypeButton)
    )
    redetect._entry.data = {"device_type": "smt_ups", "detection_version": 4}
    asyncio.run(redetect.async_press())
    assert "Modbus detection remains" in notifications[0][0]
    assert "Optional SNMP enrichment was unavailable" in notifications[0][0]
    assert "no user action is required" in notifications[0][0]
    coordinator.data["battery_test_operation_state"] = "refused"

    translations = json.loads(
        (PACKAGE_PATH / "translations/en.json").read_text(encoding="utf-8")
    )["entity"]
    for entity in [*switches[1:], *write_buttons]:
        domain = (
            "switch" if isinstance(entity, switch.APCModbusWriteSwitch) else "button"
        )
        assert entity._attr_translation_key in translations[domain]
    for key, expected_states in {
        "battery_test_operation_state": {
            "unknown",
            "pending",
            "in_progress",
            "passed",
            "failed",
            "refused",
            "aborted",
        },
        "runtime_calibration_operation_state": {
            "unknown",
            "pending",
            "in_progress",
            "passed",
            "failed",
            "refused",
            "aborted",
        },
        "outlet_mog_operation_state": {
            "unknown",
            "on",
            "off",
            "pending",
            "reboot",
            "shutdown",
            "sleep",
        },
        "outlet_sog_0_operation_state": {
            "unknown",
            "on",
            "off",
            "pending",
            "reboot",
            "shutdown",
            "sleep",
        },
        "outlet_sog_1_operation_state": {
            "unknown",
            "on",
            "off",
            "pending",
            "reboot",
            "shutdown",
            "sleep",
        },
        "outlet_sog_2_operation_state": {
            "unknown",
            "on",
            "off",
            "pending",
            "reboot",
            "shutdown",
            "sleep",
        },
    }.items():
        assert set(translations["sensor"][key]["state"]) == expected_states

    coordinator.device_type = sys.modules[
        "entity_runtime.device_types"
    ].APCDeviceType.SMT_UPS
    entry.async_on_unload = lambda callback: callback
    sensors = _collect_setup(sensor, hass, entry)
    operation_sensors = [
        entity
        for entity in sensors
        if entity.entity_description.key.endswith("_operation_state")
    ]
    assert len(operation_sensors) == 6
    assert all(
        entity._attr_entity_registry_enabled_default is False
        for entity in operation_sensors
    )
    assert {
        entity.entity_description.key: entity.native_value
        for entity in operation_sensors
    } == {
        "battery_test_operation_state": "refused",
        "runtime_calibration_operation_state": "aborted",
        "outlet_mog_operation_state": "on",
        "outlet_sog_0_operation_state": "off",
        "outlet_sog_1_operation_state": "pending",
        "outlet_sog_2_operation_state": "shutdown",
    }
    assert all(
        entity.entity_description.device_class == "enum" for entity in operation_sensors
    )

    coordinator.device_type = sensor.APCDeviceType.SMARTCONNECT_UPS
    smartconnect_sensors = _collect_setup(sensor, hass, entry)
    assert {
        entity.entity_description.key
        for entity in smartconnect_sensors
        if entity.entity_description.key.endswith("_operation_state")
    } == {entity.entity_description.key for entity in operation_sensors}


def test_no_capabilities_means_no_write_entities(monkeypatch):
    switch, button, sensor, support = _load_entities(monkeypatch)
    coordinator = Coordinator(support)
    coordinator.write_capabilities.clear()
    hass = Hass(coordinator)
    coordinator.hass = hass
    entry = SimpleNamespace(entry_id="entry", data={})
    assert len(_collect_setup(switch, hass, entry)) == 1
    assert len(_collect_setup(button, hass, entry)) == 3
    coordinator.device_type = sys.modules[
        "entity_runtime.device_types"
    ].APCDeviceType.SMT_UPS
    entry.async_on_unload = lambda callback: callback
    assert _collect_setup(sensor, hass, entry) == []


def _set_logbook_identity(entity, name):
    entity.name = name
    entity.entity_id = f"button.ups_{name.lower().replace(' ', '_')}"
    entity._context = object()


def test_write_restoration_is_armed_before_reconciliation(monkeypatch):
    _, button, _, support = _load_entities(monkeypatch)
    coordinator = Coordinator(support)
    hass = Hass(coordinator)
    coordinator.hass = hass
    entry = SimpleNamespace(entry_id="entry", data={})
    start = button.APCModbusWriteButton(
        coordinator,
        entry,
        support.WriteOperation.BATTERY_TEST_START,
        None,
        "battery_test_start",
    )
    _set_logbook_identity(start, "Start Battery Self Test")

    async def reconciliation_update():
        assert start._report_restoration
        coordinator._write_pending.add("battery_test")
        start._handle_coordinator_update()

    coordinator.write_hook = reconciliation_update
    asyncio.run(start.async_press())
    coordinator._write_pending.clear()
    coordinator.data["battery_test_operation_state"] = "pending"
    original_context = start._context
    start._context = object()
    start._handle_coordinator_update()

    entries = sys.modules["homeassistant.components.logbook"].entries
    assert len(entries) == 1
    assert entries[0][0][2] == (
        "Control restored to available; this is not another press. "
        "Current device status: Pending."
    )
    assert entries[0][1]["entity_id"] == start.entity_id
    assert entries[0][1]["context"] is original_context
    start._handle_coordinator_update()
    assert len(entries) == 1


def test_refused_write_restoration_and_rejected_write_do_not_misreport(monkeypatch):
    _, button, _, support = _load_entities(monkeypatch)
    coordinator = Coordinator(support)
    hass = Hass(coordinator)
    coordinator.hass = hass
    entry = SimpleNamespace(entry_id="entry", data={})
    calibration = button.APCModbusWriteButton(
        coordinator,
        entry,
        support.WriteOperation.CALIBRATION_START,
        None,
        "calibration_start",
    )
    _set_logbook_identity(calibration, "Start Runtime Calibration")

    async def reconciliation_update():
        coordinator._write_pending.add("calibration")
        calibration._handle_coordinator_update()

    coordinator.write_hook = reconciliation_update
    asyncio.run(calibration.async_press())
    coordinator._write_pending.clear()
    coordinator.data["runtime_calibration_operation_state"] = "refused"
    calibration._handle_coordinator_update()
    entries = sys.modules["homeassistant.components.logbook"].entries
    assert len(entries) == 1
    assert entries[0][0][2].endswith("Terminal status: Refused.")

    async def reject(*args):
        raise RuntimeError("not sent")

    coordinator.async_execute_write = reject
    with pytest.raises(RuntimeError, match="not sent"):
        asyncio.run(calibration.async_press())
    coordinator.last_update_success = False
    calibration._handle_coordinator_update()
    coordinator.last_update_success = True
    calibration._handle_coordinator_update()
    assert len(entries) == 1


def test_utility_buttons_log_one_event_after_genuine_recovery(monkeypatch):
    _, button, _, support = _load_entities(monkeypatch)
    coordinator = Coordinator(support)
    hass = Hass(coordinator)
    coordinator.hass = hass
    entry = SimpleNamespace(
        entry_id="entry", data={"device_type": "smt_ups", "detection_version": 4}
    )
    utilities = [
        button.APCModbusDiagnosticButton(coordinator, entry),
        button.APCModbusRedetectDeviceTypeButton(coordinator, entry),
        button.APCModbusResetMonitorDefaultsButton(coordinator, entry.entry_id),
    ]
    for entity in utilities:
        _set_logbook_identity(entity, entity._attr_name)

    def make_unavailable(entity):
        def update():
            assert entity._report_restoration
            coordinator.last_update_success = False
            entity._handle_coordinator_update()

        return update

    coordinator.hass.executor_hook = make_unavailable(utilities[0])
    asyncio.run(utilities[0].async_press())

    async def retry_metadata():
        make_unavailable(utilities[1])()
        return False

    async def detect_type():
        return coordinator.device_type

    async def refresh():
        return None

    coordinator.async_retry_snmp_metadata = retry_metadata
    coordinator.async_detect_device_type = detect_type
    coordinator.async_request_refresh = refresh
    coordinator.last_update_success = True
    asyncio.run(utilities[1].async_press())

    async def reset_defaults(*args, **kwargs):
        make_unavailable(utilities[2])()
        return (0, 0, 0)

    monkeypatch.setattr(
        button, "async_reset_entry_monitors_to_defaults", reset_defaults
    )
    coordinator.last_update_success = True
    asyncio.run(utilities[2].async_press())

    for entity in utilities:
        coordinator.last_update_success = True
        entity._handle_coordinator_update()
    entries = sys.modules["homeassistant.components.logbook"].entries
    assert len(entries) == 3
    assert all(
        entry[0][2] == "Control restored to available; this is not another press."
        for entry in entries
    )


def test_restoration_requires_an_unavailable_transition(monkeypatch):
    _, button, _, support = _load_entities(monkeypatch)
    coordinator = Coordinator(support)
    hass = Hass(coordinator)
    coordinator.hass = hass
    entry = SimpleNamespace(entry_id="entry", data={})
    start = button.APCModbusWriteButton(
        coordinator,
        entry,
        support.WriteOperation.BATTERY_TEST_START,
        None,
        "battery_test_start",
    )
    _set_logbook_identity(start, "Start Battery Self Test")
    asyncio.run(start.async_press())
    start._handle_coordinator_update()
    coordinator.last_update_success = False
    start._handle_coordinator_update()
    coordinator.last_update_success = True
    start._handle_coordinator_update()
    assert sys.modules["homeassistant.components.logbook"].entries == []
