import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apc_modbus"
    / "scan_interval_guard.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "apc_scan_interval_guard", MODULE_PATH
)
assert MODULE_SPEC and MODULE_SPEC.loader
SCAN_INTERVAL_GUARD = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(SCAN_INTERVAL_GUARD)

compute_effective_scan_interval = SCAN_INTERVAL_GUARD.compute_effective_scan_interval


def test_small_fleet_keeps_configured_interval() -> None:
    assert compute_effective_scan_interval(10, 1) == 10
    assert compute_effective_scan_interval(10, 8) == 10


def test_large_fleet_applies_floor() -> None:
    assert compute_effective_scan_interval(10, 9) == 20
    assert compute_effective_scan_interval(10, 26) == 52


def test_respects_higher_user_interval() -> None:
    assert compute_effective_scan_interval(90, 26) == 90


def test_caps_floor_at_upper_bound() -> None:
    assert compute_effective_scan_interval(10, 200) == 120
