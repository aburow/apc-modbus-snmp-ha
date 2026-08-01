import importlib.util
from pathlib import Path


path = (
    Path(__file__).resolve().parents[1] / "custom_components/apc_modbus/device_types.py"
)
spec = importlib.util.spec_from_file_location("apc_device_types", path)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

APCDeviceType = module.APCDeviceType
DETECTION_VERSION = module.DETECTION_VERSION
ProbeKind = module.ProbeKind
ProbeOutcome = module.ProbeOutcome


def response(*registers: int) -> ProbeOutcome:
    return ProbeOutcome(ProbeKind.RESPONSE, registers)


def unsupported() -> ProbeOutcome:
    return ProbeOutcome(ProbeKind.MODBUS_EXCEPTION, exception_code=2)


def probes(*, pdu_caps, pdu_measurements, legacy, smt):
    return {
        "rack_pdu_capabilities": pdu_caps,
        "rack_pdu_measurements": pdu_measurements,
        "legacy_ups_id": legacy,
        "smt_status": response(*([0] * 23)),
        "smt_measurements": smt,
    }


def test_live_schema_signatures_are_definitive() -> None:
    assert (
        module.classify_device_type(
            probes(
                pdu_caps=unsupported(),
                pdu_measurements=unsupported(),
                legacy=unsupported(),
                smt=response(*([0] * 26)),
            )
        )
        == APCDeviceType.SMT_UPS
    )
    assert (
        module.classify_device_type(
            probes(
                pdu_caps=unsupported(),
                pdu_measurements=unsupported(),
                legacy=response(0),
                smt=unsupported(),
            )
        )
        == APCDeviceType.SMART_UPS
    )
    assert (
        module.classify_device_type(
            probes(
                pdu_caps=response(1, 1, 0, 20, 0),
                pdu_measurements=response(0, 0, 0, 0, 0, 4),
                legacy=unsupported(),
                smt=response(*([0] * 26)),
            )
        )
        == APCDeviceType.RACK_PDU
    )


def test_ambiguous_and_incoherent_evidence_never_guesses() -> None:
    transport = ProbeOutcome(ProbeKind.TRANSPORT_FAILURE)
    for candidate in (
        probes(
            pdu_caps=response(0, 0, 0, 0, 0),
            pdu_measurements=response(0, 0, 0, 0, 0, 0),
            legacy=response(0),
            smt=response(*([0] * 26)),
        ),
        probes(
            pdu_caps=response(1, 2, 0, 0, 0),
            pdu_measurements=response(0, 0, 0, 0, 0, 5),
            legacy=unsupported(),
            smt=unsupported(),
        ),
        probes(
            pdu_caps=unsupported(),
            pdu_measurements=unsupported(),
            legacy=transport,
            smt=response(*([0] * 26)),
        ),
    ):
        assert module.classify_device_type(candidate) is None


def test_detection_version_and_selection_keep_ambiguous_stored_type() -> None:
    assert module.should_probe_device_type(
        APCDeviceType.SMART_UPS, stored_detection_version=None
    )
    assert module.should_probe_device_type(
        APCDeviceType.SMART_UPS, stored_detection_version="bad"
    )
    assert not module.should_probe_device_type(
        APCDeviceType.SMART_UPS, stored_detection_version=DETECTION_VERSION
    )
    assert (
        module.choose_device_type(
            stored_device_type=APCDeviceType.SMART_UPS,
            detected_device_type=None,
        )
        == APCDeviceType.SMART_UPS
    )
    assert (
        module.choose_device_type(stored_device_type=None, detected_device_type=None)
        is None
    )
