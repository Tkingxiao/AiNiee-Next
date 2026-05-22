from __future__ import annotations

import copy
from typing import Any, Dict, Tuple

from ModuleFolders.Infrastructure.TaskConfig.ConfigProfileService import (
    PROFILES_PATH,
    atomic_write_json,
    get_active_profile_name,
    list_profile_names,
    load_json_file,
    load_root_config,
    resolve_profile_path,
    save_root_config,
)
from Tools.MCPServer.security import (
    contains_redacted_secret,
    restore_redacted_secrets,
    sanitize_data_for_mcp,
    strip_mcp_security_metadata,
)


CONFIG_SECURITY_PATH = "/api/config"
QUEUE_SECURITY_PATH = "/api/queue/raw"


def load_dict_json(path: str) -> Dict[str, Any]:
    """Load a JSON object from disk and return an empty dict on invalid data."""
    try:
        data = load_json_file(path, {})
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def active_profile_name() -> str:
    return get_active_profile_name(load_root_config())


def resolve_config_profile_path(profile: Any = None) -> Tuple[str, str]:
    """Resolve a profile file path without allowing path traversal."""
    profile_name = profile or active_profile_name()
    return resolve_profile_path(PROFILES_PATH, profile_name)


def sanitize_config_value(value: Any, key: str) -> Any:
    """Redact a config value when exposing it to Skills clients."""
    return sanitize_data_for_mcp(
        value,
        path=CONFIG_SECURITY_PATH,
        field_name=key,
    )


def sanitize_payload(data: Any, *, path: str = CONFIG_SECURITY_PATH) -> Any:
    return sanitize_data_for_mcp(data, path=path)


def prepare_config_value_for_save(value: Any, current_value: Any, key: str) -> Any:
    """
    Restore redacted secret placeholders before saving.

    This lets a client round-trip sanitized data without overwriting an existing
    API key with "[MCP_SECRET_REDACTED]".
    """
    clean_value = strip_mcp_security_metadata(copy.deepcopy(value))
    restored = restore_redacted_secrets(clean_value, current_value, field_name=key)
    if contains_redacted_secret(restored, field_name=key):
        raise ValueError(
            f"Refusing to save redacted placeholder for sensitive config key: {key}"
        )
    return restored
