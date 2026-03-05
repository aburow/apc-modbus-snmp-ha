# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Brent Avery
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Register definitions for APC Smart-UPS devices with SMT, SMX, and SRT prefix.

Based on 990-9840B-EN (Smart-UPS Models with prefix SMT, SMX, SURTD, and SRT).
Addresses are Modbus wire addresses (Absolute Starting Register Address 0 = Modicon 40001).

Scale: raw register value divided by scale gives the engineering-unit value.
  e.g. StateOfCharge_Pct scale=512: raw 51200 / 512 = 100.0 %

All registers listed here are ReadOnly and supported on SMT/SMX and SRT.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfTemperature,
    UnitOfTime,
)

from .const import APCModbusBinarySensorDescription, APCModbusSensorDescription

# ---------------------------------------------------------------------------
# Individual register descriptors
# (also used to build REGISTER_MAP and as fallback for individual reads)
# ---------------------------------------------------------------------------

REGISTERS: list[dict] = [
    # --- Status bitfield registers ---
    # UPSStatus_BF (0x0000): macro-level UPS operating state; 2 registers = UINT32
    {
        "key": "ups_status_bf",
        "address": 0x0000,
        "count": 2,
        "type": "uint32",
        "scale": 1,
    },
    # GeneralError_BF (0x0013): miscellaneous system faults
    {
        "key": "general_error_bf",
        "address": 0x0013,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # PowerSystemError_BF (0x0014): power-path faults; 2 registers = UINT32
    {
        "key": "power_system_error_bf",
        "address": 0x0014,
        "count": 2,
        "type": "uint32",
        "scale": 1,
    },
    # BatterySystemError_BF (0x0016): battery subsystem faults
    {
        "key": "battery_system_error_bf",
        "address": 0x0016,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # --- Measurement registers ---
    # RunTimeRemaining (0x0080): seconds until output off on battery; 2 registers = UINT32
    {
        "key": "runtime_remaining",
        "address": 0x0080,
        "count": 2,
        "type": "uint32",
        "scale": 1,
    },
    # StateOfCharge_Pct (0x0082): battery charge, raw/512 = %
    {
        "key": "battery_state_of_charge",
        "address": 0x0082,
        "count": 1,
        "type": "uint16",
        "scale": 512,
    },
    # Battery.Positive.VoltageDC (0x0083): positive bus voltage, raw/32 = V
    {
        "key": "battery_voltage",
        "address": 0x0083,
        "count": 1,
        "type": "int16",
        "scale": 32,
    },
    # Battery.Temperature (0x0087): battery temperature, raw/128 = °C
    {
        "key": "battery_temperature",
        "address": 0x0087,
        "count": 1,
        "type": "int16",
        "scale": 128,
    },
    # Output[0].RealPower_Pct (0x0088): output load as % of rated real power, raw/256 = %
    {
        "key": "output_load_percent",
        "address": 0x0088,
        "count": 1,
        "type": "uint16",
        "scale": 256,
    },
    # Output[0].CurrentAC (0x008C): Phase 1 RMS current, raw/32 = A
    {
        "key": "output_current",
        "address": 0x008C,
        "count": 1,
        "type": "uint16",
        "scale": 32,
    },
    # Output[0].VoltageAC (0x008E): Phase 1 output voltage, raw/64 = V
    {
        "key": "output_voltage",
        "address": 0x008E,
        "count": 1,
        "type": "uint16",
        "scale": 64,
    },
    # Output.Frequency (0x0090): output frequency, raw/128 = Hz
    {
        "key": "output_frequency",
        "address": 0x0090,
        "count": 1,
        "type": "uint16",
        "scale": 128,
    },
    # Output.Energy (0x0091): cumulative output energy, raw = Wh; 2 registers = UINT32
    {
        "key": "output_energy",
        "address": 0x0091,
        "count": 2,
        "type": "uint32",
        "scale": 1,
    },
    # Input[0].VoltageAC (0x0097): Phase 1 input voltage, raw/64 = V
    {
        "key": "input_voltage",
        "address": 0x0097,
        "count": 1,
        "type": "uint16",
        "scale": 64,
    },
]

# ---------------------------------------------------------------------------
# Block read definitions
# Contiguous address ranges read in a single Modbus request for efficiency.
# Gaps (reserved / unused registers) return zero and are harmless.
# ---------------------------------------------------------------------------

REGISTER_BLOCKS: list[dict] = [
    {
        # Covers UPSStatus_BF (0x0000) through BatterySystemError_BF (0x0016).
        # count=23: addresses 0x0000-0x0016 inclusive (0x0016 is at offset 22).
        "name": "status",
        "start_address": 0x0000,
        "count": 23,
        "registers": [0x0000, 0x0013, 0x0014, 0x0016],
    },
    {
        # Covers RunTimeRemaining (0x0080) through Input[0].VoltageAC (0x0097).
        # count=24: addresses 0x0080-0x0097 inclusive (0x0097 is at offset 23).
        "name": "measurements",
        "start_address": 0x0080,
        "count": 24,
        "registers": [
            0x0080,
            0x0082,
            0x0083,
            0x0087,
            0x0088,
            0x008C,
            0x008E,
            0x0090,
            0x0091,
            0x0097,
        ],
    },
]

# ---------------------------------------------------------------------------
# Address → descriptor map (used by coordinator to decode block read results)
# ---------------------------------------------------------------------------

REGISTER_MAP: dict[int, dict] = {r["address"]: r for r in REGISTERS}

# ---------------------------------------------------------------------------
# Sensor entity descriptions
# ---------------------------------------------------------------------------

SENSOR_DESCRIPTIONS: list[APCModbusSensorDescription] = [
    APCModbusSensorDescription(
        key="runtime_remaining",
        name="Runtime Remaining",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        register_key="runtime_remaining",
    ),
    APCModbusSensorDescription(
        key="battery_state_of_charge",
        name="Battery State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register_key="battery_state_of_charge",
    ),
    APCModbusSensorDescription(
        key="battery_voltage",
        name="Battery Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register_key="battery_voltage",
    ),
    APCModbusSensorDescription(
        key="battery_temperature",
        name="Battery Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register_key="battery_temperature",
    ),
    APCModbusSensorDescription(
        key="output_load_percent",
        name="Output Load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register_key="output_load_percent",
    ),
    APCModbusSensorDescription(
        key="output_current",
        name="Output Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        register_key="output_current",
    ),
    APCModbusSensorDescription(
        key="output_voltage",
        name="Output Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register_key="output_voltage",
    ),
    APCModbusSensorDescription(
        key="output_frequency",
        name="Output Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        register_key="output_frequency",
    ),
    APCModbusSensorDescription(
        key="output_energy",
        name="Output Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register_key="output_energy",
    ),
    APCModbusSensorDescription(
        key="input_voltage",
        name="Input Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register_key="input_voltage",
    ),
]

# ---------------------------------------------------------------------------
# Binary sensor entity descriptions
# ---------------------------------------------------------------------------
# UPSStatus_BF (register key "ups_status_bf") is a UINT32 decoded from
# 2 Modbus registers. Bit indices 0-31 are valid.
#
# BatterySystemError_BF (register key "battery_system_error_bf") is a UINT16.
# ---------------------------------------------------------------------------

BINARY_SENSOR_DESCRIPTIONS: list[APCModbusBinarySensorDescription] = [
    # --- UPSStatus_BF bits (register 0x0000, UINT32) ---
    APCModbusBinarySensorDescription(
        key="ups_online",
        name="UPS Online",
        device_class=BinarySensorDeviceClass.POWER,
        register_key="ups_status_bf",
        bit_index=1,  # StateOnline: output sourced from input
    ),
    APCModbusBinarySensorDescription(
        key="ups_on_battery",
        name="UPS On Battery",
        device_class=BinarySensorDeviceClass.BATTERY,
        register_key="ups_status_bf",
        bit_index=2,  # StateOnBattery: output sourced from battery
    ),
    APCModbusBinarySensorDescription(
        key="ups_on_bypass",
        name="UPS On Bypass",
        device_class=BinarySensorDeviceClass.POWER,
        register_key="ups_status_bf",
        bit_index=3,  # StateBypass: output bypassing UPS electronics
    ),
    APCModbusBinarySensorDescription(
        key="ups_output_off",
        name="UPS Output Off",
        device_class=BinarySensorDeviceClass.POWER,
        register_key="ups_status_bf",
        bit_index=4,  # StateOutputOff: output not powered (fault or low battery)
    ),
    APCModbusBinarySensorDescription(
        key="ups_fault",
        name="UPS Fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="ups_status_bf",
        bit_index=5,  # FaultModifier: a fault of any severity is present
    ),
    APCModbusBinarySensorDescription(
        key="ups_input_bad",
        name="Input Bad",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="ups_status_bf",
        bit_index=6,  # InputBad: input not acceptable
    ),
    APCModbusBinarySensorDescription(
        key="ups_fault_state",
        name="UPS Fault State",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="ups_status_bf",
        bit_index=15,  # FaultState: UPS operating in a fault state
    ),
    APCModbusBinarySensorDescription(
        key="ups_overload",
        name="UPS Overload",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="ups_status_bf",
        bit_index=21,  # OverloadState: operating in overload state
    ),
    # --- BatterySystemError_BF bits (register 0x0016, UINT16) ---
    APCModbusBinarySensorDescription(
        key="battery_disconnected",
        name="Battery Disconnected",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="battery_system_error_bf",
        bit_index=0,  # Disconnected: battery electrically disconnected
    ),
    APCModbusBinarySensorDescription(
        key="battery_needs_replacement",
        name="Battery Needs Replacement",
        device_class=BinarySensorDeviceClass.BATTERY,
        register_key="battery_system_error_bf",
        bit_index=2,  # NeedsReplacement: battery at end of service life
    ),
    APCModbusBinarySensorDescription(
        key="battery_overtemperature",
        name="Battery Overtemperature",
        device_class=BinarySensorDeviceClass.PROBLEM,
        register_key="battery_system_error_bf",
        bit_index=7,  # OvertemperatureWarning: battery temp exceeded warning level
    ),
]
