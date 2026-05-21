from __future__ import annotations

from typing import Any, Dict

from Tools.Skills.skill_base import Skill, SkillMeta, SkillParameter, SkillResult
from Tools.Skills.skills.common import (
    active_profile_name,
    atomic_write_json,
    load_dict_json,
    load_root_config,
    prepare_config_value_for_save,
    resolve_config_profile_path,
    sanitize_config_value,
)


_MISSING = object()


class ConfigSkill(Skill):
    @property
    def meta(self) -> SkillMeta:
        return SkillMeta(
            name="config",
            description="Read and write AiNiee profile configuration.",
            category="config",
            parameters=[
                SkillParameter(
                    name="action",
                    description="Operation: get, set, list_keys.",
                    type="string",
                    required=True,
                    enum=["get", "set", "list_keys"],
                ),
                SkillParameter(
                    name="key",
                    description="Configuration key to read or write.",
                    type="string",
                    required=False,
                ),
                SkillParameter(
                    name="value",
                    description="Value to set (for set action).",
                    type="object",
                    required=False,
                ),
                SkillParameter(
                    name="profile",
                    description="Profile name (defaults to active profile).",
                    type="string",
                    required=False,
                ),
            ],
            examples=[
                {"action": "get", "key": "model"},
                {"action": "get", "key": "target_platform"},
                {"action": "list_keys"},
                {"action": "set", "key": "model", "value": "gpt-4o-mini"},
            ],
        )

    def execute(self, args: Dict[str, Any]) -> SkillResult:
        action = (args.get("action") or "").strip().lower()

        if action == "list_keys":
            try:
                path, profile = resolve_config_profile_path(args.get("profile"))
            except ValueError as e:
                return SkillResult.fail(str(e), "INVALID_PROFILE")
            cfg = load_dict_json(path)
            return SkillResult.ok({
                "profile": profile,
                "keys": sorted(cfg.keys()),
            })

        if action == "get":
            key = (args.get("key") or "").strip()
            if not key:
                return SkillResult.fail("Missing required parameter: key", "MISSING_PARAM")
            try:
                path, profile = resolve_config_profile_path(args.get("profile"))
            except ValueError as e:
                return SkillResult.fail(str(e), "INVALID_PROFILE")

            cfg = load_dict_json(path)
            value = cfg.get(key, _MISSING)
            source = "profile"
            if value is _MISSING:
                root = load_root_config()
                value = root.get(key, _MISSING)
                source = "root"

            found = value is not _MISSING
            exposed_value = None if not found else sanitize_config_value(value, key)
            return SkillResult.ok({
                "profile": profile,
                "key": key,
                "value": exposed_value,
                "found": found,
                "source": source if found else None,
            })

        if action == "set":
            key = (args.get("key") or "").strip()
            if not key:
                return SkillResult.fail("Missing required parameter: key", "MISSING_PARAM")
            if "value" not in args:
                return SkillResult.fail("Missing required parameter: value", "MISSING_PARAM")
            try:
                path, profile = resolve_config_profile_path(args.get("profile") or active_profile_name())
            except ValueError as e:
                return SkillResult.fail(str(e), "INVALID_PROFILE")

            cfg = load_dict_json(path)
            try:
                value = prepare_config_value_for_save(args["value"], cfg.get(key), key)
            except ValueError as e:
                return SkillResult.fail(str(e), "REDACTED_SECRET")

            cfg[key] = value
            try:
                atomic_write_json(path, cfg)
                return SkillResult.ok({
                    "profile": profile,
                    "key": key,
                    "value": sanitize_config_value(value, key),
                    "saved": True,
                })
            except Exception as e:
                return SkillResult.fail(f"Failed to write config: {e}", "WRITE_ERROR")

        return SkillResult.fail(f"Unknown config action: {action}", "INVALID_ACTION")
