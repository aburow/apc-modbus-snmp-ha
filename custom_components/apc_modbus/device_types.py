# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Device type definitions for APC devices."""

from enum import Enum


class APCDeviceType(Enum):
    """Enumeration of supported APC device types."""

    SMART_UPS = "smart_ups"
    RACK_PDU = "rack_pdu"
    UNKNOWN = "unknown"
