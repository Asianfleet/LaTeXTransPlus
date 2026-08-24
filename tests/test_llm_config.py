import unittest

from src.config import merge_llm_payload, parse_custom_json


class LlmConfigTests(unittest.TestCase):
    def test_parse_custom_json_accepts_object_and_empty_value(self):
        self.assertEqual(
            parse_custom_json('{"enable_thinking": true}'),
            {"enable_thinking": True},
        )
        self.assertEqual(parse_custom_json("  "), {})

    def test_parse_custom_json_rejects_non_object_and_invalid_json(self):
        with self.assertRaises(ValueError):
            parse_custom_json("[]")
        with self.assertRaises(ValueError):
            parse_custom_json("{")

    def test_parse_custom_json_rejects_reserved_request_fields(self):
        with self.assertRaisesRegex(ValueError, "model"):
            parse_custom_json('{"model": "override"}')

    def test_merge_llm_payload_adds_custom_fields_without_mutating_input(self):
        payload = {"model": "m", "temperature": 0}

        merged = merge_llm_payload(payload, {"enable_thinking": True})

        self.assertEqual(merged["enable_thinking"], True)
        self.assertNotIn("enable_thinking", payload)

    def test_merge_llm_payload_rejects_reserved_field_conflicts(self):
        with self.assertRaises(ValueError):
            merge_llm_payload({"model": "m"}, {"model": "override"})


if __name__ == "__main__":
    unittest.main()
