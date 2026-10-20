import json
import os
from pathlib import Path
from typing import Any, Dict, NoReturn

import toml


LLM_RESERVED_FIELDS = {
    "model",
    "messages",
    "temperature",
    "max_tokens",
    "max_new_tokens",
}
LLM_PROFILE_FIELDS = ("model", "api_key_env", "base_url", "custom_json")
REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")


def _reject_json_constant(value: str) -> NoReturn:
    """拒绝 JSON 标准中不存在的 NaN 和 Infinity 常量。"""
    raise ValueError(f"Invalid llm_config.custom_json constant: {value}.")


def parse_custom_json(value: Any) -> Dict[str, Any]:
    """解析 LLM 自定义 JSON，并要求结果为 JSON object。"""
    if value is None:
        return {}
    if isinstance(value, dict):
        parsed = dict(value)
    else:
        if not isinstance(value, str):
            raise ValueError("llm_config.custom_json must be a JSON object string.")

        stripped = value.strip()
        if not stripped:
            return {}

        try:
            parsed = json.loads(stripped, parse_constant=_reject_json_constant)
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


def build_llm_custom_json(llm_config: Dict[str, Any]) -> Dict[str, Any]:
    """合并 profile 自定义参数与显式思考强度，不修改原配置。"""
    custom_json = parse_custom_json(llm_config.get("custom_json"))
    effort = llm_config.get("reasoning_effort", "")
    if not isinstance(effort, str) or (effort and effort not in REASONING_EFFORTS):
        raise ValueError(
            "llm_config.reasoning_effort must be empty or one of: "
            + ", ".join(REASONING_EFFORTS)
            + "."
        )
    if effort:
        custom_json["reasoning_effort"] = effort
    return custom_json


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


def load_llm_profile(config: Dict[str, Any], config_path: str) -> Dict[str, Any]:
    """从主配置旁的 provider 目录加载并展开唯一的 LLM profile。"""
    llm_config = config.get("llm_config")
    if not isinstance(llm_config, dict):
        raise ValueError("[llm_config] must define a non-empty string profile.")

    unsupported = sorted(set(llm_config) - {"profile", "reasoning_effort"})
    if unsupported:
        fields = ", ".join(unsupported)
        raise ValueError(
            f"[llm_config] only supports profile and reasoning_effort; unsupported field(s): {fields}."
        )

    profile = llm_config.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("llm_config.profile must be a non-empty string.")
    profile = profile.strip()
    profile_name = Path(profile)
    if profile_name.name != profile or profile in {".", ".."}:
        raise ValueError("llm_config.profile must be a provider file name without a path.")

    provider_path = Path(config_path).resolve().parent / "provider" / f"{profile}.toml"
    if not provider_path.is_file():
        raise FileNotFoundError(f"LLM provider profile not found: {provider_path}")
    provider_config = toml.load(provider_path)
    if not isinstance(provider_config, dict):
        raise ValueError(f"LLM provider profile must be a TOML table: {provider_path}")
    if "llm_config" in provider_config:
        raise ValueError(
            f"LLM provider profile must define fields at the TOML root: {provider_path}"
        )

    missing = [field for field in LLM_PROFILE_FIELDS if field not in provider_config]
    if missing:
        raise ValueError(
            f"LLM provider profile is missing field(s): {', '.join(missing)}."
        )
    for field in LLM_PROFILE_FIELDS:
        if not isinstance(provider_config[field], str):
            raise ValueError(f"LLM provider field '{field}' must be a string.")

    config["llm_config"] = {"profile": profile}
    if "reasoning_effort" in llm_config:
        config["llm_config"]["reasoning_effort"] = llm_config["reasoning_effort"]
    config["llm_config"].update(
        {field: provider_config[field] for field in LLM_PROFILE_FIELDS}
    )
    return config


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
