import unittest

from src.config import build_llm_custom_json, merge_llm_payload, parse_custom_json


class LlmConfigTests(unittest.TestCase):
    def test_reasoning_effort_overrides_profile_without_mutating_it(self):
        """显式强度覆盖 profile 字段，保留其他自定义参数及原配置。"""
        for effort in ("low", "medium", "high", "xhigh", "max", "ultra"):
            with self.subTest(effort=effort):
                custom = {"reasoning_effort": "high", "enable_thinking": True}
                result = build_llm_custom_json({
                    "reasoning_effort": effort, "custom_json": custom,
                })
                self.assertEqual(result, {
                    "reasoning_effort": effort, "enable_thinking": True,
                })
                self.assertEqual(custom["reasoning_effort"], "high")

    def test_unset_reasoning_effort_preserves_profile_or_omits_parameter(self):
        """未设置强度时不改变 profile，也不向旧请求追加空字段。"""
        for override in ({}, {"reasoning_effort": ""}):
            with self.subTest(override=override):
                self.assertEqual(build_llm_custom_json(override), {})
                self.assertEqual(build_llm_custom_json({
                    **override, "custom_json": '{"reasoning_effort": "high"}',
                }), {"reasoning_effort": "high"})

    def test_invalid_reasoning_effort_is_rejected(self):
        """显式强度仅接受约定的字符串值。"""
        for effort in ("invalid", "HIGH", 1, None, []):
            with self.subTest(effort=effort):
                with self.assertRaisesRegex(ValueError, "reasoning_effort"):
                    build_llm_custom_json({"reasoning_effort": effort})

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
        with self.assertRaises(ValueError):
            parse_custom_json('{"budget": NaN}')
        with self.assertRaises(ValueError):
            parse_custom_json('{"budget": Infinity}')

    def test_parse_custom_json_rejects_reserved_request_fields(self):
        with self.assertRaisesRegex(ValueError, "model"):
            parse_custom_json('{"model": "override"}')
        with self.assertRaisesRegex(ValueError, "model"):
            parse_custom_json({"model": "override"})

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
