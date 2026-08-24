import json
import os
from typing import Any, Dict


LLM_RESERVED_FIELDS = {
    "model",
    "messages",
    "temperature",
    "max_tokens",
    "max_new_tokens",
}


def parse_custom_json(value: Any) -> Dict[str, Any]:
    """解析 LLM 自定义 JSON，并要求结果为 JSON object。"""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        raise ValueError("llm_config.custom_json must be a JSON object string.")

    stripped = value.strip()
    if not stripped:
        return {}

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid llm_config.custom_json JSON: {exc.msg}.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("llm_config.custom_json must decode to a JSON object.")
    conflicts = sorted(LLM_RESERVED_FIELDS.intersection(parsed))
    if conflicts:
        fields = ", ".join(conflicts)
        raise ValueError(
            f"llm_config.custom_json cannot override reserved field(s): {fields}."
        )
    return parsed


def merge_llm_payload(
    payload: Dict[str, Any],
    custom_json: Dict[str, Any],
) -> Dict[str, Any]:
    """将自定义 LLM 字段追加到请求体，并拒绝覆盖已有字段。"""
    conflicts = sorted(set(payload).intersection(custom_json))
    if conflicts:
        fields = ", ".join(conflicts)
        raise ValueError(
            f"llm_config.custom_json cannot override request field(s): {fields}."
        )

    merged = dict(payload)
    merged.update(custom_json)
    return merged


def resolve_llm_api_key(config: Dict[str, Any]) -> Dict[str, Any]:
    llm_config = config.setdefault("llm_config", {})
    api_key = str(llm_config.get("api_key") or "").strip()
    api_key_env = str(llm_config.get("api_key_env") or "").strip()

    if api_key or not api_key_env:
        return config

    resolved_api_key = os.environ.get(api_key_env, "").strip()
    if not resolved_api_key:
        raise ValueError(f"Environment variable '{api_key_env}' is not set or empty.")

    llm_config["api_key"] = resolved_api_key
    return config
