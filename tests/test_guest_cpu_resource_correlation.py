import copy
import unittest

from tools.guest_cpu_resource_correlation import CorrelationError, MAX_U64, correlate


class GuestCpuResourceCorrelationTests(unittest.TestCase):
    def fixture(self):
        return {
            "schema_version": "bb-guest-cpu-resource-correlation/v1",
            "live_resources": [
                {"resource_id": "res:00000001", "guest_address": 0x1000, "size_bytes": 0x100},
                {"resource_id": "res:00000002", "guest_address": 0x2000, "size_bytes": 0x100},
            ],
            "access": {"guest_address": 0x1080, "size_bytes": 8},
        }

    def test_unique_full_containment_returns_resource(self):
        result = correlate(self.fixture())
        self.assertEqual("unique", result["status"])
        self.assertEqual("res:00000001", result["resource_id"])
        self.assertEqual(["res:00000001"], result["candidate_resource_ids"])

    def test_overlapping_live_ranges_preserve_ambiguity(self):
        document = self.fixture()
        document["live_resources"].append(
            {"resource_id": "res:00000003", "guest_address": 0x1070, "size_bytes": 0x40}
        )
        result = correlate(document)
        self.assertEqual("ambiguous", result["status"])
        self.assertIsNone(result["resource_id"])
        self.assertEqual(
            ["res:00000001", "res:00000003"], result["candidate_resource_ids"]
        )

    def test_boundary_touching_range_does_not_false_match(self):
        document = self.fixture()
        document["access"] = {"guest_address": 0x1100, "size_bytes": 1}
        result = correlate(document)
        self.assertEqual("unmapped", result["status"])
        self.assertEqual([], result["candidate_resource_ids"])

    def test_partial_overlap_is_not_full_containment(self):
        document = self.fixture()
        document["access"] = {"guest_address": 0x10F8, "size_bytes": 16}
        self.assertEqual("unmapped", correlate(document)["status"])

    def test_duplicate_live_resource_id_fails_closed(self):
        document = self.fixture()
        duplicate = copy.deepcopy(document["live_resources"][0])
        duplicate["guest_address"] = 0x3000
        document["live_resources"].append(duplicate)
        with self.assertRaisesRegex(CorrelationError, "duplicate live resource id"):
            correlate(document)

    def test_access_range_overflow_fails_closed(self):
        document = self.fixture()
        document["access"] = {"guest_address": MAX_U64, "size_bytes": 2}
        with self.assertRaisesRegex(CorrelationError, "exceeds unsigned 64-bit"):
            correlate(document)

    def test_resource_range_overflow_fails_closed(self):
        document = self.fixture()
        document["live_resources"][0] = {
            "resource_id": "res:00000001",
            "guest_address": MAX_U64,
            "size_bytes": 2,
        }
        with self.assertRaisesRegex(CorrelationError, "exceeds unsigned 64-bit"):
            correlate(document)

    def test_extra_fields_fail_schema_validation(self):
        document = self.fixture()
        document["access"]["nearest"] = True
        with self.assertRaisesRegex(CorrelationError, "schema validation failed"):
            correlate(document)


if __name__ == "__main__":
    unittest.main()
