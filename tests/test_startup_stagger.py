import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apc_modbus"
    / "startup_stagger.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("apc_startup_stagger", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
STARTUP_STAGGER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(STARTUP_STAGGER)

compute_startup_stagger_delay = STARTUP_STAGGER.compute_startup_stagger_delay


def test_compute_startup_stagger_delay_returns_zero_for_single_entry() -> None:
    assert compute_startup_stagger_delay(["entry-a"], "entry-a", 10) == 0.0


def test_compute_startup_stagger_delay_spreads_entries_across_window() -> None:
    assert compute_startup_stagger_delay(["entry-a", "entry-b"], "entry-a", 10) == 0.0
    assert compute_startup_stagger_delay(["entry-a", "entry-b"], "entry-b", 10) == 5.0


def test_compute_startup_stagger_delay_caps_window_at_sixty_seconds() -> None:
    delay = compute_startup_stagger_delay(
        [f"entry-{index:03d}" for index in range(100)],
        "entry-099",
        10,
    )
    assert delay < 60.0
    assert delay >= 58.0
