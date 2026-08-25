"""Documented PowerNet SNMP commands for legacy Smart-UPS testing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SnmpCommand:
    key: str
    name: str
    oid: str
    value: int = 2


LEGACY_SNMP_COMMANDS = {
    command.key: command
    for command in (
        SnmpCommand(
            "conserve_battery", "Conserve battery", "1.3.6.1.4.1.318.1.1.1.6.1.1.0"
        ),
        SnmpCommand("ups_off", "Turn UPS off", "1.3.6.1.4.1.318.1.1.1.6.2.1.0"),
        SnmpCommand("ups_reboot", "Reboot UPS", "1.3.6.1.4.1.318.1.1.1.6.2.2.0"),
        SnmpCommand("ups_sleep", "Put UPS to sleep", "1.3.6.1.4.1.318.1.1.1.6.2.3.0"),
        SnmpCommand(
            "simulate_power_failure",
            "Simulate power failure",
            "1.3.6.1.4.1.318.1.1.1.6.2.4.0",
        ),
        SnmpCommand("alarm_test", "Run alarm test", "1.3.6.1.4.1.318.1.1.1.6.2.5.0"),
        SnmpCommand("ups_turn_on", "Turn UPS on", "1.3.6.1.4.1.318.1.1.1.6.2.6.0"),
        SnmpCommand(
            "battery_self_test",
            "Run battery self-test",
            "1.3.6.1.4.1.318.1.1.1.7.2.2.0",
        ),
    )
}
