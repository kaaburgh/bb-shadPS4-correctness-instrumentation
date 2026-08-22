import copy
import unittest
from pathlib import Path

from tools import trace_event_model


ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "docs" / "instrumentation" / "examples" / "trace-events.synthetic.json"


def _capability(state: str):
    result = {"state": state}
    if state != "unknown":
        result["evidence_sha256"] = "5" * 64
    if state == "negative_validated":
        result["coverage_oracle_sha256"] = "6" * 64
    return result


def _observer(
    *,
    mechanism: str = "access_violation",
    read_state: str = "observable",
    write_state: str = "observable",
):
    build_path = (
        "enable_userfaultfd"
        if mechanism == "userfaultfd_write_protect"
        else "non_userfaultfd"
    )
    return {
        "schema_version": trace_event_model.OBSERVER_SCHEMA_VERSION,
        "fault_mechanism": mechanism,
        "build_path": build_path,
        "capabilities": {
            "read": _capability(read_state),
            "write": _capability(write_state),
        },
    }


class TraceEventContractTests(unittest.TestCase):
    def setUp(self):
        self.document = trace_event_model.load_strict(EXAMPLE)

    def _runtime_document(self, *, observer=None):
        document = copy.deepcopy(self.document)
        material = document["provenance"]["material"]
        material["evidence_class"] = "runtime"
        material["producer"]["producer_id"] = "shadps4-bb-instrumentation"
        material["producer"]["producer_sha256"] = "7" * 64
        if observer is not None:
            material["observer"] = observer
        document["provenance"]["baseline_id"] = trace_event_model.baseline_id_for(material)
        return document

    def test_synthetic_fixture_validates(self):
        trace_event_model.validate_schema(self.document)
        trace_event_model.validate_semantics(self.document)

    def test_duplicate_json_member_is_rejected(self):
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "duplicate JSON member"):
            trace_event_model.loads_strict('{"schema_version":"a","schema_version":"b"}')

    def test_provenance_material_change_invalidates_baseline_id(self):
        document = copy.deepcopy(self.document)
        document["provenance"]["material"]["target_manifest_sha256"] = "9" * 64
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "baseline_id does not match"):
            trace_event_model.validate_semantics(document)

    def test_expected_baseline_mismatch_is_rejected(self):
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "does not match expected baseline"):
            trace_event_model.validate_semantics(self.document, expected_baseline_id="0" * 64)

    def test_repository_producer_digest_mismatch_is_rejected(self):
        document = copy.deepcopy(self.document)
        material = document["provenance"]["material"]
        material["producer"]["producer_sha256"] = "0" * 64
        document["provenance"]["baseline_id"] = trace_event_model.baseline_id_for(material)
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "producer_sha256"):
            trace_event_model.validate_semantics(document)

    def test_repository_schema_digest_mismatch_is_rejected(self):
        document = copy.deepcopy(self.document)
        material = document["provenance"]["material"]
        material["producer"]["schema_sha256"] = "0" * 64
        document["provenance"]["baseline_id"] = trace_event_model.baseline_id_for(material)
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "schema_sha256"):
            trace_event_model.validate_semantics(document)

    def test_contract_producer_cannot_self_declare_runtime(self):
        document = copy.deepcopy(self.document)
        material = document["provenance"]["material"]
        material["evidence_class"] = "runtime"
        document["provenance"]["baseline_id"] = trace_event_model.baseline_id_for(material)
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "runtime evidence requires"):
            trace_event_model.validate_semantics(document)

    def test_private_operator_string_is_rejected_as_resource_id(self):
        document = copy.deepcopy(self.document)
        document["events"][0]["correlation"]["resource_id"] = "alice"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "schema validation failed"):
            trace_event_model.validate_schema(document)

    def test_token_like_kind_is_rejected(self):
        document = copy.deepcopy(self.document)
        document["events"][0]["kind"] = "ghp_deadbeefdeadbeef"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "schema validation failed"):
            trace_event_model.validate_schema(document)

    def test_category_kind_mismatch_is_rejected(self):
        document = copy.deepcopy(self.document)
        document["events"][2]["kind"] = "guest_cpu"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "invalid for category"):
            trace_event_model.validate_semantics(document)

    def test_access_fields_are_rejected_on_non_access_events(self):
        document = copy.deepcopy(self.document)
        document["events"][2]["access"] = "write"
        document["events"][2]["coverage"] = "observed"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "only valid on access events"):
            trace_event_model.validate_semantics(document)

    def test_access_events_require_access_and_coverage(self):
        document = copy.deepcopy(self.document)
        del document["events"][1]["coverage"]
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "require access and coverage"):
            trace_event_model.validate_semantics(document)

    def test_timing_duration_is_required_and_category_scoped(self):
        missing = copy.deepcopy(self.document)
        del missing["events"][4]["duration_ns"]
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "timing events require"):
            trace_event_model.validate_semantics(missing)

        misplaced = copy.deepcopy(self.document)
        misplaced["events"][3]["duration_ns"] = 1
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "only valid on timing events"):
            trace_event_model.validate_semantics(misplaced)

    def test_size_bytes_is_create_only(self):
        document = copy.deepcopy(self.document)
        document["events"][0]["kind"] = "destroy"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "only valid on resource create"):
            trace_event_model.validate_semantics(document)

    def test_event_count_is_bounded(self):
        document = copy.deepcopy(self.document)
        document["capture"]["limits"]["max_events"] = 4
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "exceeds max_events"):
            trace_event_model.validate_semantics(document)

    def test_sequence_gaps_are_rejected(self):
        document = copy.deepcopy(self.document)
        document["events"][2]["seq"] = 9
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "contiguous"):
            trace_event_model.validate_semantics(document)

    def test_timestamp_regression_is_rejected(self):
        document = copy.deepcopy(self.document)
        document["events"][3]["timestamp_ns"] = 1
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "monotonic"):
            trace_event_model.validate_semantics(document)

    def test_filter_is_enforced(self):
        document = copy.deepcopy(self.document)
        document["capture"]["filter"].remove("graphics")
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "not enabled"):
            trace_event_model.validate_semantics(document)

    def test_runtime_guest_cpu_event_requires_observer_provenance(self):
        document = self._runtime_document()
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "versioned observer provenance"):
            trace_event_model.validate_semantics(document)

    def test_runtime_observed_write_accepts_observable_capability(self):
        document = self._runtime_document(observer=_observer())
        trace_event_model.validate_schema(document)
        trace_event_model.validate_semantics(document)

    def test_observable_capability_requires_independent_evidence_digest(self):
        observer = _observer()
        del observer["capabilities"]["write"]["evidence_sha256"]
        document = self._runtime_document(observer=observer)
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "independent evidence_sha256"):
            trace_event_model.validate_semantics(document)

    def test_negative_validated_capability_requires_separate_coverage_oracle(self):
        observer = _observer(write_state="negative_validated")
        del observer["capabilities"]["write"]["coverage_oracle_sha256"]
        document = self._runtime_document(observer=observer)
        document["events"][1]["coverage"] = "unobserved"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "coverage_oracle_sha256"):
            trace_event_model.validate_semantics(document)

    def test_negative_validated_capability_rejects_reused_evidence_digest_as_oracle(self):
        observer = _observer(write_state="negative_validated")
        write = observer["capabilities"]["write"]
        write["coverage_oracle_sha256"] = write["evidence_sha256"]
        document = self._runtime_document(observer=observer)
        document["events"][1]["coverage"] = "unobserved"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "distinct from evidence_sha256"):
            trace_event_model.validate_semantics(document)

    def test_runtime_unobserved_rejects_observable_only_capability(self):
        document = self._runtime_document(observer=_observer())
        document["events"][1]["coverage"] = "unobserved"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "negative_validated write"):
            trace_event_model.validate_semantics(document)

    def test_runtime_unobserved_accepts_negative_validated_capability(self):
        document = self._runtime_document(
            observer=_observer(write_state="negative_validated")
        )
        document["events"][1]["coverage"] = "unobserved"
        trace_event_model.validate_semantics(document)

    def test_userfaultfd_direct_read_capability_remains_unknown(self):
        document = self._runtime_document(
            observer=_observer(
                mechanism="userfaultfd_write_protect",
                read_state="observable",
                write_state="observable",
            )
        )
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "direct-read capability remains unknown"):
            trace_event_model.validate_semantics(document)

    def test_userfaultfd_observed_write_is_compatible_with_unknown_read(self):
        document = self._runtime_document(
            observer=_observer(
                mechanism="userfaultfd_write_protect",
                read_state="unknown",
                write_state="observable",
            )
        )
        trace_event_model.validate_semantics(document)

    def test_userfaultfd_observed_read_fails_closed(self):
        document = self._runtime_document(
            observer=_observer(
                mechanism="userfaultfd_write_protect",
                read_state="unknown",
                write_state="observable",
            )
        )
        document["events"][1]["access"] = "read"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "observable read capability"):
            trace_event_model.validate_semantics(document)

    def test_observer_fault_mechanism_must_match_build_path(self):
        observer = _observer()
        observer["build_path"] = "enable_userfaultfd"
        document = self._runtime_document(observer=observer)
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "mechanism/build path mismatch"):
            trace_event_model.validate_semantics(document)

    def test_synthetic_guest_cpu_unobserved_remains_contract_testable(self):
        document = copy.deepcopy(self.document)
        document["events"][1]["coverage"] = "unobserved"
        trace_event_model.validate_semantics(document)

    def test_drop_accounting_is_explicit(self):
        document = copy.deepcopy(self.document)
        document["summary"]["dropped_events"] = 17
        trace_event_model.validate_semantics(document)
        self.assertEqual(document["summary"]["dropped_events"], 17)

    def test_buffer_high_water_cannot_exceed_bound(self):
        document = copy.deepcopy(self.document)
        document["summary"]["buffer_high_water_bytes"] = 70000
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "high-water"):
            trace_event_model.validate_semantics(document)

    def test_all_sampling_requires_every_event(self):
        document = copy.deepcopy(self.document)
        document["capture"]["sampling"]["every_n"] = 2
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "every_n=1"):
            trace_event_model.validate_semantics(document)


if __name__ == "__main__":
    unittest.main()
