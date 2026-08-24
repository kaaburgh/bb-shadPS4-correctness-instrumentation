import unittest

from tools.buffer_resource_id_binding import BindingError, bind_lifetimes


def event(seq, buffer_id, address, size, live):
    return {
        "seq": seq,
        "buffer_id": buffer_id,
        "guest_address": address,
        "size_bytes": size,
        "live": live,
    }


class BufferResourceIdBindingTests(unittest.TestCase):
    def bind(self, events, complete=True, first_resource_ordinal=1):
        return bind_lifetimes({
            "schema_version": "bb-buffer-resource-id-binding/v1",
            "complete": complete,
            "first_resource_ordinal": first_resource_ordinal,
            "events": events,
        })

    def test_output_uses_documented_contract_schema_version(self):
        self.assertEqual(self.bind([])["schema_version"], "bb-buffer-resource-id-binding/v1")

    def test_assigns_fresh_durable_id_on_buffer_id_reuse(self):
        result = self.bind([
            event(10, 7, 0x1000, 0x100, True),
            event(20, 7, 0x1000, 0x100, False),
            event(30, 7, 0x2000, 0x80, True),
            event(40, 7, 0x2000, 0x80, False),
        ])
        self.assertEqual([b["resource_id"] for b in result["bindings"]], ["res:00000001", "res:00000002"])
        self.assertEqual(result["next_resource_ordinal"], 3)
        self.assertEqual([b["end_seq"] for b in result["bindings"]], [20, 40])

    def test_consumes_caller_owned_resource_namespace(self):
        result = self.bind([
            event(1, 99, 0x1000, 0x10, True),
            event(2, 3, 0x2000, 0x10, True),
            event(3, 99, 0x1000, 0x10, False),
            event(4, 3, 0x2000, 0x10, False),
        ], first_resource_ordinal=41)
        self.assertEqual([b["resource_id"] for b in result["bindings"]], ["res:00000041", "res:00000042"])
        self.assertEqual(result["next_resource_ordinal"], 43)

    def test_rejects_invalid_resource_namespace_start(self):
        with self.assertRaisesRegex(BindingError, "resource-ID namespace"):
            self.bind([], first_resource_ordinal=0)

    def test_rejects_non_monotonic_sequence(self):
        with self.assertRaisesRegex(BindingError, "strictly increasing"):
            self.bind([event(10, 1, 0, 1, True), event(9, 1, 0, 1, False)])

    def test_rejects_duplicate_live_registration(self):
        with self.assertRaisesRegex(BindingError, "already live"):
            self.bind([event(1, 1, 0, 1, True), event(2, 1, 0, 1, True)], complete=False)

    def test_rejects_unmatched_unregister(self):
        with self.assertRaisesRegex(BindingError, "without active lifetime"):
            self.bind([event(1, 1, 0, 1, False)])

    def test_rejects_unregister_range_mismatch(self):
        with self.assertRaisesRegex(BindingError, "does not match"):
            self.bind([event(1, 1, 0x1000, 0x10, True), event(2, 1, 0x1000, 0x20, False)])

    def test_rejects_unclosed_lifetime_when_complete(self):
        with self.assertRaisesRegex(BindingError, "ended with live"):
            self.bind([event(1, 1, 0, 1, True)])

    def test_allows_unclosed_lifetime_for_partial_stream(self):
        result = self.bind([event(1, 1, 0, 1, True)], complete=False)
        self.assertIsNone(result["bindings"][0]["end_seq"])

    def test_rejects_range_overflow(self):
        with self.assertRaisesRegex(BindingError, "overflows"):
            self.bind([event(1, 1, (1 << 64) - 1, 2, True)], complete=False)

    def test_rejects_extra_fields(self):
        document = {
            "schema_version": "bb-buffer-resource-id-binding/v1",
            "complete": True,
            "first_resource_ordinal": 1,
            "events": [],
            "unexpected": True,
        }
        with self.assertRaisesRegex(BindingError, "fields mismatch"):
            bind_lifetimes(document)


if __name__ == "__main__":
    unittest.main()