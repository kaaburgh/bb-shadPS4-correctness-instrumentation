import json
import unittest
from pathlib import Path

from tools.guest_cpu_fault_pairing import PairingError, reconstruct, validate_input


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/instrumentation/examples/guest-cpu-fault-pairing.synthetic.json"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class GuestCpuFaultPairingTests(unittest.TestCase):
    def test_fixture_preserves_paired_unmatched_and_ambiguous(self):
        result = reconstruct(load_fixture())
        self.assertEqual(
            result["pairings"],
            [
                {"accepted_seq": 11, "status": "paired", "raw_seq": 10},
                {"accepted_seq": 12, "status": "unmatched"},
                {
                    "accepted_seq": 15,
                    "status": "ambiguous",
                    "candidate_raw_seqs": [13, 14],
                },
            ],
        )
        self.assertEqual(
            result["paired_accesses"],
            [
                {
                    "seq": 11,
                    "timestamp_ns": 101,
                    "guest_address": 4096,
                    "size_bytes": 8,
                    "access": "write",
                }
            ],
        )
        self.assertEqual(result["unpaired_raw_seqs"], [13, 14])
        self.assertEqual(
            result["summary"],
            {
                "raw_faults": 3,
                "accepted_accesses": 3,
                "paired": 1,
                "unmatched": 1,
                "ambiguous": 1,
                "unpaired_raw_faults": 2,
            },
        )

    def test_pairing_is_capture_thread_scoped(self):
        document = load_fixture()
        document["observations"] = [
            {
                "type": "raw_fault", "seq": 1, "timestamp_ns": 1,
                "thread_id": "thread:00000001", "guest_address": 4096, "access": "write"
            },
            {
                "type": "accepted_access", "seq": 2, "timestamp_ns": 2,
                "thread_id": "thread:00000002", "guest_address": 4096,
                "size_bytes": 8, "access": "write"
            },
        ]
        result = reconstruct(document)
        self.assertEqual(result["pairings"][0]["status"], "unmatched")
        self.assertEqual(result["unpaired_raw_seqs"], [1])

    def test_read_write_mismatch_is_not_paired(self):
        document = load_fixture()
        document["observations"] = [
            {
                "type": "raw_fault", "seq": 1, "timestamp_ns": 1,
                "thread_id": "thread:00000001", "guest_address": 4096, "access": "read"
            },
            {
                "type": "accepted_access", "seq": 2, "timestamp_ns": 2,
                "thread_id": "thread:00000001", "guest_address": 4096,
                "size_bytes": 8, "access": "write"
            },
        ]
        self.assertEqual(reconstruct(document)["pairings"][0]["status"], "unmatched")

    def test_rejects_non_increasing_sequence(self):
        document = load_fixture()
        document["observations"][1]["seq"] = document["observations"][0]["seq"]
        with self.assertRaisesRegex(PairingError, "strictly increasing"):
            validate_input(document)

    def test_rejects_non_monotonic_timestamp(self):
        document = load_fixture()
        document["observations"][1]["timestamp_ns"] = 99
        with self.assertRaisesRegex(PairingError, "timestamp_ns must be monotonic"):
            validate_input(document)

    def test_rejects_host_thread_identifier_shape(self):
        document = load_fixture()
        document["observations"][0]["thread_id"] = "tid:1234"
        with self.assertRaisesRegex(PairingError, r"thread:\[0-9\]\{8\}"):
            validate_input(document)

    def test_rejects_accepted_range_overflow(self):
        document = load_fixture()
        document["observations"][1]["guest_address"] = (1 << 64) - 4
        document["observations"][1]["size_bytes"] = 8
        with self.assertRaisesRegex(PairingError, "overflows"):
            validate_input(document)

    def test_rejects_extra_fields(self):
        document = load_fixture()
        document["observations"][0]["host_tid"] = 123
        with self.assertRaisesRegex(PairingError, "fields mismatch"):
            validate_input(document)

    def test_unique_pair_consumes_only_matching_raw_fault(self):
        document = load_fixture()
        document["observations"] = [
            {
                "type": "raw_fault", "seq": 1, "timestamp_ns": 1,
                "thread_id": "thread:00000001", "guest_address": 4096, "access": "write"
            },
            {
                "type": "raw_fault", "seq": 2, "timestamp_ns": 2,
                "thread_id": "thread:00000001", "guest_address": 8192, "access": "write"
            },
            {
                "type": "accepted_access", "seq": 3, "timestamp_ns": 3,
                "thread_id": "thread:00000001", "guest_address": 4096,
                "size_bytes": 8, "access": "write"
            },
        ]
        result = reconstruct(document)
        self.assertEqual(result["pairings"][0]["raw_seq"], 1)
        self.assertEqual(result["unpaired_raw_seqs"], [2])

    def test_ambiguous_pair_does_not_guess_or_consume_candidates(self):
        document = load_fixture()
        document["observations"] = [
            {
                "type": "raw_fault", "seq": 1, "timestamp_ns": 1,
                "thread_id": "thread:00000001", "guest_address": 4096, "access": "write"
            },
            {
                "type": "raw_fault", "seq": 2, "timestamp_ns": 2,
                "thread_id": "thread:00000001", "guest_address": 4096, "access": "write"
            },
            {
                "type": "accepted_access", "seq": 3, "timestamp_ns": 3,
                "thread_id": "thread:00000001", "guest_address": 4096,
                "size_bytes": 8, "access": "write"
            },
        ]
        result = reconstruct(document)
        self.assertEqual(result["pairings"][0]["candidate_raw_seqs"], [1, 2])
        self.assertEqual(result["unpaired_raw_seqs"], [1, 2])


if __name__ == "__main__":
    unittest.main()
