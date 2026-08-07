# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Constants for the APC UPS Modbus integration."""

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)

DOMAIN = "apc_modbus"
DEFAULT_NAME = "APC UPS"
DEFAULT_PORT = 502
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_UNIT = 1
DEFAULT_SNMP_COMMUNITY = "public"
DEFAULT_SNMP_PORT = 161
DEFAULT_KEEP_CONNECTION_OPEN = False
DEFAULT_IDLE_RECONNECT_SECONDS = 120
CONF_UNIT = "unit"
CONF_DEVICE_NAME = "device_name"
CONF_SNMP_COMMUNITY = "snmp_community"
CONF_SNMP_PORT = "snmp_port"
CONF_DEVICE_TYPE = "device_type"
CONF_DETECTION_VERSION = "detection_version"
CONF_KEEP_CONNECTION_OPEN = "keep_connection_open"
CONF_TRANSPORT_MODE = "transport_mode"
CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS = "output_energy_completed_rollovers"

KEY_CLIENT = "modbus_client"
KEY_COORDINATOR = "coordinator"

SUPPORTED_PLATFORMS = ["sensor", "binary_sensor", "button", "switch"]


@dataclass
class APCModbusSensorDescription(SensorEntityDescription):
    """Describe an APC Modbus sensor."""

    register_key: str = ""
    value_map: dict[int, str] | None = None


@dataclass
class APCModbusBinarySensorDescription(BinarySensorEntityDescription):
    """Describe an APC Modbus binary sensor."""

    register_key: str = ""
    bit_index: int = 0


SENSOR_DESCRIPTIONS = [
    # Battery Sensors
    APCModbusSensorDescription(
        key="battery_state_of_charge",
        name="Battery State of Charge",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="battery_state_of_charge",
    ),
    APCModbusSensorDescription(
        key="battery_voltage",
        name="Battery Voltage",
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="battery_voltage",
    ),
    APCModbusSensorDescription(
        key="runtime_remaining",
        name="Runtime Remaining",
        native_unit_of_measurement="s",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_unit_of_measurement="min",
        register_key="runtime_remaining",
    ),
    APCModbusSensorDescription(
        key="ups_internal_temperature",
        name="UPS Internal Temperature",
        native_unit_of_measurement="°C",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="ups_internal_temperature",
    ),
    APCModbusSensorDescription(
        key="bad_battery_packs",
        name="Bad Battery Packs",
        native_unit_of_measurement="",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        register_key="bad_battery_packs",
    ),
    APCModbusSensorDescription(
        key="total_battery_packs",
        name="Total Battery Packs",
        native_unit_of_measurement="",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        register_key="total_battery_packs",
    ),
    # Load Sensors
    APCModbusSensorDescription(
        key="load_amps",
        name="Load Current",
        native_unit_of_measurement="A",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="load_amps",
    ),
    APCModbusSensorDescription(
        key="load_percent",
        name="Load Percent",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        register_key="load_percent",
    ),
    # Input Sensors
    APCModbusSensorDescription(
        key="input_voltage",
        name="Input Voltage",
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="input_voltage",
    ),
    APCModbusSensorDescription(
        key="input_frequency",
        name="Input Frequency",
        native_unit_of_measurement="Hz",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        register_key="input_frequency",
    ),
    APCModbusSensorDescription(
        key="max_input_voltage",
        name="Max Input Voltage",
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="max_input_voltage",
    ),
    APCModbusSensorDescription(
        key="min_input_voltage",
        name="Min Input Voltage",
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="min_input_voltage",
    ),
    # Output Sensors
    APCModbusSensorDescription(
        key="actual_output_voltage",
        name="Output Voltage",
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="actual_output_voltage",
    ),
    APCModbusSensorDescription(
        key="nominal_output_voltage",
        name="Nominal Output Voltage",
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="nominal_output_voltage",
    ),
    # Configuration Sensors
    APCModbusSensorDescription(
        key="lower_transfer_point",
        name="Lower Transfer Point",
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="lower_transfer_point",
    ),
    APCModbusSensorDescription(
        key="upper_transfer_point",
        name="Upper Transfer Point",
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="upper_transfer_point",
    ),
    APCModbusSensorDescription(
        key="shutdown_delay",
        name="Shutdown Delay",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="shutdown_delay",
    ),
    APCModbusSensorDescription(
        key="low_battery_duration",
        name="Low Battery Duration",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="low_battery_duration",
    ),
    APCModbusSensorDescription(
        key="turn_on_delay",
        name="Turn On Delay",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="turn_on_delay",
    ),
]

SNMP_EXTERNAL_SENSOR_DESCRIPTIONS = [
    APCModbusSensorDescription(
        key="snmp_external_temp_1",
        name="External Temperature Probe 1",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement="°C",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="snmp_external_temp_1",
    ),
    APCModbusSensorDescription(
        key="snmp_external_humidity_1",
        name="External Humidity Probe 1",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="snmp_external_humidity_1",
    ),
    APCModbusSensorDescription(
        key="snmp_external_temp_2",
        name="External Temperature Probe 2",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement="°C",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="snmp_external_temp_2",
    ),
    APCModbusSensorDescription(
        key="snmp_external_humidity_2",
        name="External Humidity Probe 2",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        register_key="snmp_external_humidity_2",
    ),
]

SNMP_SELF_TEST_SENSOR_DESCRIPTIONS = [
    APCModbusSensorDescription(
        key="snmp_self_test_schedule",
        name="Automatic Self-Test Schedule",
        device_class=SensorDeviceClass.ENUM,
        register_key="snmp_self_test_schedule",
        value_map={
            1: "Unknown",
            2: "Biweekly",
            3: "Weekly",
            4: "At Turn On",
            5: "Never",
            6: "Every 4 Weeks",
            7: "Every 12 Weeks",
            8: "Biweekly Since Last Test",
            9: "Weekly Since Last Test",
            10: "Every 8 Weeks",
            11: "Every 26 Weeks",
            12: "Every 52 Weeks",
        },
    ),
    APCModbusSensorDescription(
        key="snmp_self_test_result",
        name="Last Self-Test Result",
        device_class=SensorDeviceClass.ENUM,
        register_key="snmp_self_test_result",
        value_map={1: "OK", 2: "Failed", 3: "Invalid Test", 4: "Test In Progress"},
    ),
    APCModbusSensorDescription(
        key="snmp_last_self_test_date",
        name="Last Self-Test Date",
        device_class=SensorDeviceClass.DATE,
        register_key="snmp_last_self_test_date",
    ),
    APCModbusSensorDescription(
        key="snmp_self_test_time",
        name="Automatic Self-Test Time",
        register_key="snmp_self_test_time",
    ),
    APCModbusSensorDescription(
        key="snmp_self_test_day",
        name="Automatic Self-Test Day",
        device_class=SensorDeviceClass.ENUM,
        register_key="snmp_self_test_day",
        value_map={
            1: "Monday",
            2: "Tuesday",
            3: "Wednesday",
            4: "Thursday",
            5: "Friday",
            6: "Saturday",
            7: "Sunday",
        },
    ),
    APCModbusSensorDescription(
        key="snmp_runtime_calibration_status",
        name="Runtime Calibration Status",
        device_class=SensorDeviceClass.ENUM,
        register_key="snmp_runtime_calibration_status",
        value_map={
            1: "Calibration Complete",
            2: "Cannot Calibrate — Battery Not Fully Charged",
            3: "Calibration In Progress",
            4: "Calibration Refused",
            5: "Calibration Aborted",
            6: "Calibration Pending",
        },
    ),
]

BINARY_SENSOR_DESCRIPTIONS = [
    # Status Word 1 - Faults
    APCModbusBinarySensorDescription(
        key="ups_on_battery_low_shutdown",
        name="Low Battery Shutdown",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="status_word_1",
        bit_index=0,
    ),
    APCModbusBinarySensorDescription(
        key="ups_unable_transfer_overload",
        name="Unable to Transfer (Overload)",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="status_word_1",
        bit_index=1,
    ),
    APCModbusBinarySensorDescription(
        key="ups_main_relay_fault",
        name="Main Relay Fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="status_word_1",
        bit_index=2,
    ),
    APCModbusBinarySensorDescription(
        key="ups_battery_charger_fault",
        name="Battery Charger Fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="status_word_1",
        bit_index=5,
    ),
    APCModbusBinarySensorDescription(
        key="ups_temperature_fault",
        name="Temperature Fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="status_word_1",
        bit_index=7,
    ),
    # Status Word 2 - Faults
    APCModbusBinarySensorDescription(
        key="ups_bypass_fault",
        name="Bypass Fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="status_word_2",
        bit_index=4,
    ),
    APCModbusBinarySensorDescription(
        key="ups_inverter_fault",
        name="Inverter Fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="status_word_2",
        bit_index=7,
    ),
    # Status Word 3 - Operating Status
    APCModbusBinarySensorDescription(
        key="ups_online",
        name="UPS Online",
        device_class=BinarySensorDeviceClass.POWER,
        register_key="status_word_3",
        bit_index=3,
    ),
    APCModbusBinarySensorDescription(
        key="ups_on_battery",
        name="UPS On Battery",
        device_class=BinarySensorDeviceClass.POWER,
        register_key="status_word_3",
        bit_index=4,
    ),
    APCModbusBinarySensorDescription(
        key="ups_overload",
        name="UPS Overload",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="status_word_3",
        bit_index=5,
    ),
    APCModbusBinarySensorDescription(
        key="ups_low_battery",
        name="UPS Low Battery",
        device_class=BinarySensorDeviceClass.BATTERY,
        register_key="status_word_3",
        bit_index=6,
    ),
    APCModbusBinarySensorDescription(
        key="ups_replace_battery",
        name="UPS Replace Battery",
        device_class=BinarySensorDeviceClass.BATTERY,
        register_key="status_word_3",
        bit_index=7,
    ),
]

SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
