import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apc_modbus"
    / "device_types.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("apc_device_types", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
DEVICE_TYPES = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(DEVICE_TYPES)

APCDeviceType = DEVICE_TYPES.APCDeviceType
DETECTION_VERSION = DEVICE_TYPES.DETECTION_VERSION
choose_device_type = DEVICE_TYPES.choose_device_type
classify_device_type = DEVICE_TYPES.classify_device_type
classify_smart_ups_family = DEVICE_TYPES.classify_smart_ups_family
should_probe_device_type = DEVICE_TYPES.should_probe_device_type


def test_should_probe_device_type_requires_probe_for_unknown_types() -> None:
    assert should_probe_device_type(None, stored_detection_version=None) is True
    assert (
        should_probe_device_type(
            APCDeviceType.UNKNOWN,
            stored_detection_version=DETECTION_VERSION,
        )
        is True
    )
    assert (
        should_probe_device_type(
            APCDeviceType.UPS,
            stored_detection_version=DETECTION_VERSION,
        )
        is True
    )


def test_should_probe_device_type_skips_reprobe_for_current_concrete_type() -> None:
    assert (
        should_probe_device_type(
            APCDeviceType.SMART_UPS,
            stored_detection_version=DETECTION_VERSION,
        )
        is False
    )
    assert (
        should_probe_device_type(
            APCDeviceType.SMT_UPS,
            stored_detection_version=DETECTION_VERSION,
        )
        is False
    )
    assert (
        should_probe_device_type(
            APCDeviceType.RACK_PDU,
            stored_detection_version=DETECTION_VERSION,
        )
        is False
    )


def test_should_probe_device_type_skips_reprobe_when_detection_version_changes() -> (
    None
):
    assert (
        should_probe_device_type(
            APCDeviceType.RACK_PDU,
            stored_detection_version=DETECTION_VERSION - 1,
        )
        is False
    )


def test_should_probe_device_type_reprobes_on_conflicting_strong_snmp_hint() -> None:
    assert (
        should_probe_device_type(
            APCDeviceType.SMT_UPS,
            stored_detection_version=DETECTION_VERSION,
            snmp_hint_device_type=APCDeviceType.RACK_PDU,
        )
        is True
    )


def test_choose_device_type_prefers_detected_then_stored_then_snmp_then_default() -> (
    None
):
    assert (
        choose_device_type(
            stored_device_type=APCDeviceType.SMT_UPS,
            detected_device_type=APCDeviceType.RACK_PDU,
            snmp_hint_device_type=APCDeviceType.SMART_UPS,
        )
        == APCDeviceType.RACK_PDU
    )
    assert (
        choose_device_type(
            stored_device_type=APCDeviceType.SMT_UPS,
            detected_device_type=None,
            snmp_hint_device_type=APCDeviceType.RACK_PDU,
        )
        == APCDeviceType.SMT_UPS
    )
    assert (
        choose_device_type(
            stored_device_type=None,
            detected_device_type=None,
            snmp_hint_device_type=APCDeviceType.RACK_PDU,
        )
        == APCDeviceType.RACK_PDU
    )
    assert (
        choose_device_type(
            stored_device_type=None,
            detected_device_type=None,
            snmp_hint_device_type=None,
        )
        == APCDeviceType.SMART_UPS
    )


def test_classify_smart_ups_family_prefers_smt_when_legacy_probe_fails() -> None:
    assert (
        classify_smart_ups_family(
            legacy_probe_ok=False,
            smt_status_ok=True,
            smt_measurements_ok=True,
        )
        == APCDeviceType.SMT_UPS
    )


def test_classify_smart_ups_family_prefers_smt_when_measurements_only_succeed() -> None:
    assert (
        classify_smart_ups_family(
            legacy_probe_ok=False,
            smt_status_ok=False,
            smt_measurements_ok=True,
        )
        == APCDeviceType.SMT_UPS
    )


def test_classify_smart_ups_family_prefers_legacy_when_smt_probes_fail() -> None:
    assert (
        classify_smart_ups_family(
            legacy_probe_ok=True,
            smt_status_ok=False,
            smt_measurements_ok=False,
        )
        == APCDeviceType.SMART_UPS
    )


def test_classify_smart_ups_family_prefers_legacy_when_status_only_succeeds() -> None:
    assert (
        classify_smart_ups_family(
            legacy_probe_ok=True,
            smt_status_ok=True,
            smt_measurements_ok=False,
        )
        == APCDeviceType.SMART_UPS
    )


def test_classify_smart_ups_family_returns_none_when_ambiguous() -> None:
    assert (
        classify_smart_ups_family(
            legacy_probe_ok=True,
            smt_status_ok=True,
            smt_measurements_ok=True,
        )
        is None
    )


def test_classify_smart_ups_family_returns_none_when_no_discriminator_succeeds() -> (
    None
):
    assert (
        classify_smart_ups_family(
            legacy_probe_ok=False,
            smt_status_ok=True,
            smt_measurements_ok=False,
        )
        is None
    )


def test_classify_device_type_prefers_rack_pdu_when_only_pdu_probes_succeed() -> None:
    assert (
        classify_device_type(
            rack_pdu_capabilities_ok=True,
            rack_pdu_measurements_ok=True,
            legacy_probe_ok=False,
            smt_status_ok=False,
            smt_measurements_ok=False,
        )
        == APCDeviceType.RACK_PDU
    )
