import os
from typing import Any, Dict


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
