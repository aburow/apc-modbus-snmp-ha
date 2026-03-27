# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Register definitions for APC NetShelter Rack PDU devices.

Based on Rack PDU register maps.
Addresses are Modbus wire addresses (register number - 40000 for holding registers).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass

_LOGGER = logging.getLogger(__name__)


POWER_STATE_LABELS = {
    0: "Unknown",
    1: "Low",
    2: "Normal",
    3: "Near Overload",
    4: "Overload",
}

OUTLET_ALARM_STATE_LABELS = {
    0: "Unknown",
    1: "No Alarm",
    2: "Warning",
    3: "Alarm",
    4: "Critical",
}


# Capability registers for dynamic entity generation
CAPABILITY_REGISTERS = [
    {
        "key": "num_phases",
        "address": 0x009E,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "num_metered_phases",
        "address": 0x009F,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "num_banks",
        "address": 0x00A0,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "num_outlets",
        "address": 0x00A1,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "num_metered_outlets",
        "address": 0x00A2,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
]

# Device-level measurement registers (Priority 1)
DEVICE_REGISTERS = [
    # Real power (kW)
    {
        "key": "device_real_power",
        "address": 0x00CF,
        "count": 1,
        "type": "int16",
        "scale": 100,
    },
    # Apparent power (kVA)
    {
        "key": "device_apparent_power",
        "address": 0x00D0,
        "count": 1,
        "type": "int16",
        "scale": 100,
    },
    # Power factor
    {
        "key": "device_power_factor",
        "address": 0x00D1,
        "count": 1,
        "type": "int16",
        "scale": 100,
    },
    # Energy (kWh) - 2 registers
    {
        "key": "device_energy",
        "address": 0x00D2,
        "count": 2,
        "type": "uint32",
        "scale": 10,
    },
    # Load state (enum: 1=Low, 2=Normal, 3=Near Overload, 4=Overload)
    {
        "key": "device_load_state",
        "address": 0x00D4,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
]


def generate_phase_registers(num_phases: int) -> list[dict[str, Any]]:
    """Generate phase measurement registers for the given number of phases.

    Each phase has: current, voltage, power, apparent power, power factor, state.
    L1: 0x029B-0x02A0, L2: 0x02B1-0x02B6, L3: 0x02C7-0x02CC

    Args:
        num_phases: Number of phases (1 or 3)

    Returns:
        List of register descriptors for all phase measurements
    """
    registers = []

    phase_offsets = [
        (1, 0x029B),  # L1
        (2, 0x02B1),  # L2
        (3, 0x02C7),  # L3
    ]

    for phase_num, base_addr in phase_offsets:
        if phase_num > num_phases:
            break

        phase_label = f"L{phase_num}"

        # Phase current (scale /10)
        registers.append(
            {
                "key": f"phase_{phase_label}_current",
                "address": base_addr,
                "count": 1,
                "type": "int16",
                "scale": 10,
            }
        )

        # Phase voltage
        registers.append(
            {
                "key": f"phase_{phase_label}_voltage",
                "address": base_addr + 1,
                "count": 1,
                "type": "uint16",
                "scale": 1,
            }
        )

        # Phase real power (watts)
        registers.append(
            {
                "key": f"phase_{phase_label}_real_power",
                "address": base_addr + 2,
                "count": 1,
                "type": "int16",
                "scale": 1,
            }
        )

        # Phase apparent power (VA)
        registers.append(
            {
                "key": f"phase_{phase_label}_apparent_power",
                "address": base_addr + 3,
                "count": 1,
                "type": "int16",
                "scale": 1,
            }
        )

        # Phase power factor (scale /100)
        registers.append(
            {
                "key": f"phase_{phase_label}_power_factor",
                "address": base_addr + 4,
                "count": 1,
                "type": "int16",
                "scale": 100,
            }
        )

        # Phase state (enum)
        registers.append(
            {
                "key": f"phase_{phase_label}_state",
                "address": base_addr + 5,
                "count": 1,
                "type": "uint16",
                "scale": 1,
            }
        )

    return registers


def generate_outlet_registers(num_outlets: int) -> list[dict[str, Any]]:
    """Generate outlet measurement registers for the given number of outlets.

    Outlets are grouped by 8:
    - Outlets 1-8: current at 0x06FA+, power at 0x0712+, energy at 0x0702+, alarm at 0x071A+
    - Outlets 9-16: similar pattern at different base addresses
    - Up to 64 outlets total (8 groups of 8)

    Args:
        num_outlets: Number of metered outlets (0-64)

    Returns:
        List of register descriptors for outlet measurements
    """
    if num_outlets <= 0:
        return []

    registers = []

    # Outlet groups: (group_num, base_addr_current, base_addr_power, base_addr_energy, base_addr_alarm)
    outlet_groups = [
        (1, 0x06FA, 0x0712, 0x0702, 0x071A),  # Outlets 1-8
        (
            2,
            0x0702,
            0x072A,
            0x071A,
            0x0732,
        ),  # Outlets 9-16 (example - may vary by model)
        (3, 0x070A, 0x0742, 0x0732, 0x074A),  # Outlets 17-24
        (4, 0x0712, 0x075A, 0x074A, 0x0762),  # Outlets 25-32
        (5, 0x071A, 0x0772, 0x0762, 0x077A),  # Outlets 33-40
        (6, 0x0722, 0x078A, 0x077A, 0x0792),  # Outlets 41-48
        (7, 0x072A, 0x07A2, 0x0792, 0x07AA),  # Outlets 49-56
        (8, 0x0732, 0x07BA, 0x07AA, 0x07C2),  # Outlets 57-64
    ]

    for group_num, base_current, base_power, base_energy, base_alarm in outlet_groups:
        start_outlet = (group_num - 1) * 8 + 1
        end_outlet = min(start_outlet + 7, num_outlets)

        if start_outlet > num_outlets:
            break

        for offset in range(end_outlet - start_outlet + 1):
            outlet_num = start_outlet + offset

            # Outlet current (scale /10)
            registers.append(
                {
                    "key": f"outlet_{outlet_num}_current",
                    "address": base_current + offset,
                    "count": 1,
                    "type": "int16",
                    "scale": 10,
                }
            )

            # Outlet power (watts)
            registers.append(
                {
                    "key": f"outlet_{outlet_num}_power",
                    "address": base_power + offset,
                    "count": 1,
                    "type": "int16",
                    "scale": 1,
                }
            )

            # Outlet energy (kWh, 2 registers, scale /10)
            registers.append(
                {
                    "key": f"outlet_{outlet_num}_energy",
                    "address": base_energy + offset * 2,
                    "count": 2,
                    "type": "uint32",
                    "scale": 10,
                }
            )

            # Outlet alarm state (enum)
            registers.append(
                {
                    "key": f"outlet_{outlet_num}_alarm_state",
                    "address": base_alarm + offset,
                    "count": 1,
                    "type": "uint16",
                    "scale": 1,
                }
            )

    return registers


def generate_bank_registers(num_banks: int) -> list[dict[str, Any]]:
    """Generate bank measurement registers for the given number of banks.

    Banks 1-6: base address 0x030C
    Banks 7-12: base address varies by model (example: 0x0312)

    Args:
        num_banks: Number of banks (0-12)

    Returns:
        List of register descriptors for bank measurements
    """
    if num_banks <= 0:
        return []

    registers = []

    # Bank groups: (start_bank, end_bank, base_addr_current, base_addr_state)
    bank_groups = [
        (1, min(6, num_banks), 0x030C, 0x0312),  # Banks 1-6
        (7, min(12, num_banks), 0x0318, 0x031E),  # Banks 7-12
    ]

    for start_bank, end_bank, base_current, base_state in bank_groups:
        if start_bank > num_banks:
            break

        for bank_num in range(start_bank, end_bank + 1):
            offset = bank_num - start_bank

            # Bank current (scale /10)
            registers.append(
                {
                    "key": f"bank_{bank_num}_current",
                    "address": base_current + offset,
                    "count": 1,
                    "type": "int16",
                    "scale": 10,
                }
            )

            # Bank state (enum)
            registers.append(
                {
                    "key": f"bank_{bank_num}_state",
                    "address": base_state + offset,
                    "count": 1,
                    "type": "uint16",
                    "scale": 1,
                }
            )

    return registers


def _build_registers(
    num_phases: int = 1, num_outlets: int = 0, num_banks: int = 0
) -> list[dict[str, Any]]:
    """Build complete register list for Rack PDU with given capabilities.

    Args:
        num_phases: Number of phases
        num_outlets: Number of metered outlets
        num_banks: Number of banks

    Returns:
        Combined list of all applicable registers
    """
    registers = CAPABILITY_REGISTERS + DEVICE_REGISTERS
    registers.extend(generate_phase_registers(num_phases))
    registers.extend(generate_outlet_registers(num_outlets))
    registers.extend(generate_bank_registers(num_banks))
    return registers


# Default Rack PDU registers (with typical values)
# This will be populated with actual capabilities at runtime
REGISTERS = _build_registers()

# Block read configuration for optimized polling
REGISTER_BLOCKS = [
    {
        "name": "capabilities",
        "start_address": 0x009E,
        "count": 5,
        "registers": [0x009E, 0x009F, 0x00A0, 0x00A1, 0x00A2],
    },
    {
        "name": "device_measurements",
        "start_address": 0x00CF,
        "count": 7,
        "registers": [0x00CF, 0x00D0, 0x00D1, 0x00D2, 0x00D3, 0x00D4],
    },
    {
        "name": "phase_L1_measurements",
        "start_address": 0x029B,
        "count": 6,
        "registers": [0x029B, 0x029C, 0x029D, 0x029E, 0x029F, 0x02A0],
    },
]

# Lookup map: address -> descriptor
REGISTER_MAP = {reg["address"]: reg for reg in REGISTERS}


def get_sensor_descriptions(capabilities: dict = None):
    """Get sensor descriptions for Rack PDU device.

    Dynamically generates sensor descriptions based on device capabilities.

    Args:
        capabilities: Dict with keys: num_phases, num_outlets, num_metered_outlets, num_banks

    Returns:
        List of sensor descriptions
    """
    # Import here to avoid circular imports
    from .const import APCModbusSensorDescription, SensorStateClass

    if not capabilities:
        capabilities = {}

    num_phases = capabilities.get("num_phases", 1)
    num_metered_outlets = capabilities.get("num_metered_outlets", 0)
    num_banks = capabilities.get("num_banks", 0)

    descriptions = []

    # Device-level sensors
    descriptions.extend(
        [
            APCModbusSensorDescription(
                key="device_real_power",
                name="Real Power",
                native_unit_of_measurement="kW",
                state_class=SensorStateClass.MEASUREMENT,
                register_key="device_real_power",
            ),
            APCModbusSensorDescription(
                key="device_apparent_power",
                name="Apparent Power",
                native_unit_of_measurement="kVA",
                state_class=SensorStateClass.MEASUREMENT,
                register_key="device_apparent_power",
            ),
            APCModbusSensorDescription(
                key="device_power_factor",
                name="Power Factor",
                native_unit_of_measurement="",
                state_class=SensorStateClass.MEASUREMENT,
                register_key="device_power_factor",
            ),
            APCModbusSensorDescription(
                key="device_energy",
                name="Energy",
                native_unit_of_measurement="kWh",
                state_class=SensorStateClass.TOTAL_INCREASING,
                register_key="device_energy",
            ),
            APCModbusSensorDescription(
                key="device_load_state",
                name="Load State",
                device_class=SensorDeviceClass.ENUM,
                options=list(POWER_STATE_LABELS.values()),
                state_class=None,
                register_key="device_load_state",
                value_map=POWER_STATE_LABELS,
            ),
        ]
    )

    # Phase-specific sensors
    for phase_num in range(1, num_phases + 1):
        phase_label = f"L{phase_num}"
        descriptions.extend(
            [
                APCModbusSensorDescription(
                    key=f"phase_{phase_label}_current",
                    name=f"Phase {phase_label} Current",
                    native_unit_of_measurement="A",
                    state_class=SensorStateClass.MEASUREMENT,
                    register_key=f"phase_{phase_label}_current",
                ),
                APCModbusSensorDescription(
                    key=f"phase_{phase_label}_voltage",
                    name=f"Phase {phase_label} Voltage",
                    native_unit_of_measurement="V",
                    state_class=SensorStateClass.MEASUREMENT,
                    register_key=f"phase_{phase_label}_voltage",
                ),
                APCModbusSensorDescription(
                    key=f"phase_{phase_label}_real_power",
                    name=f"Phase {phase_label} Real Power",
                    native_unit_of_measurement="W",
                    state_class=SensorStateClass.MEASUREMENT,
                    register_key=f"phase_{phase_label}_real_power",
                ),
                APCModbusSensorDescription(
                    key=f"phase_{phase_label}_apparent_power",
                    name=f"Phase {phase_label} Apparent Power",
                    native_unit_of_measurement="VA",
                    state_class=SensorStateClass.MEASUREMENT,
                    register_key=f"phase_{phase_label}_apparent_power",
                ),
                APCModbusSensorDescription(
                    key=f"phase_{phase_label}_power_factor",
                    name=f"Phase {phase_label} Power Factor",
                    native_unit_of_measurement="",
                    state_class=SensorStateClass.MEASUREMENT,
                    register_key=f"phase_{phase_label}_power_factor",
                ),
                APCModbusSensorDescription(
                    key=f"phase_{phase_label}_state",
                    name=f"Phase {phase_label} State",
                    device_class=SensorDeviceClass.ENUM,
                    options=list(POWER_STATE_LABELS.values()),
                    state_class=None,
                    register_key=f"phase_{phase_label}_state",
                    value_map=POWER_STATE_LABELS,
                ),
            ]
        )

    # Outlet-specific sensors (metered outlets only)
    for outlet_num in range(1, num_metered_outlets + 1):
        descriptions.extend(
            [
                APCModbusSensorDescription(
                    key=f"outlet_{outlet_num}_current",
                    name=f"Outlet {outlet_num} Current",
                    native_unit_of_measurement="A",
                    state_class=SensorStateClass.MEASUREMENT,
                    register_key=f"outlet_{outlet_num}_current",
                ),
                APCModbusSensorDescription(
                    key=f"outlet_{outlet_num}_power",
                    name=f"Outlet {outlet_num} Power",
                    native_unit_of_measurement="W",
                    state_class=SensorStateClass.MEASUREMENT,
                    register_key=f"outlet_{outlet_num}_power",
                ),
                APCModbusSensorDescription(
                    key=f"outlet_{outlet_num}_energy",
                    name=f"Outlet {outlet_num} Energy",
                    native_unit_of_measurement="kWh",
                    state_class=SensorStateClass.TOTAL_INCREASING,
                    register_key=f"outlet_{outlet_num}_energy",
                ),
                APCModbusSensorDescription(
                    key=f"outlet_{outlet_num}_alarm_state",
                    name=f"Outlet {outlet_num} Alarm State",
                    device_class=SensorDeviceClass.ENUM,
                    options=list(OUTLET_ALARM_STATE_LABELS.values()),
                    state_class=None,
                    register_key=f"outlet_{outlet_num}_alarm_state",
                    value_map=OUTLET_ALARM_STATE_LABELS,
                ),
            ]
        )

    # Bank-specific sensors
    for bank_num in range(1, num_banks + 1):
        descriptions.extend(
            [
                APCModbusSensorDescription(
                    key=f"bank_{bank_num}_current",
                    name=f"Bank {bank_num} Current",
                    native_unit_of_measurement="A",
                    state_class=SensorStateClass.MEASUREMENT,
                    register_key=f"bank_{bank_num}_current",
                ),
                APCModbusSensorDescription(
                    key=f"bank_{bank_num}_state",
                    name=f"Bank {bank_num} State",
                    device_class=SensorDeviceClass.ENUM,
                    options=list(POWER_STATE_LABELS.values()),
                    state_class=None,
                    register_key=f"bank_{bank_num}_state",
                    value_map=POWER_STATE_LABELS,
                ),
            ]
        )

    return descriptions


def get_binary_sensor_descriptions(capabilities: dict = None):
    """Get binary sensor descriptions for Rack PDU device.

    Args:
        capabilities: Device capabilities (unused for Rack PDU in current implementation)

    Returns:
        List of binary sensor descriptions
    """
    # For now, Rack PDU has no binary sensors defined
    # This can be extended with alarm states as binary sensors if needed
    return []
