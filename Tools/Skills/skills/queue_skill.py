from __future__ import annotations

import os
from typing import Any, Dict

from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from ModuleFolders.Service.TaskQueue.QueueManager import QueueManager, QueueTaskItem
from Tools.Skills.skill_base import Skill, SkillMeta, SkillParameter, SkillResult
from Tools.Skills.skills.common import QUEUE_SECURITY_PATH, sanitize_payload


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


_TASK_TYPE_BY_NAME = {
    "translate": TaskType.TRANSLATION,
    "translation": TaskType.TRANSLATION,
    "polish": TaskType.POLISH,
    "polishing": TaskType.POLISH,
    "all_in_one": TaskType.TRANSLATE_AND_POLISH,
    "translate_and_polish": TaskType.TRANSLATE_AND_POLISH,
}
_TASK_TYPE_LABELS = {
    TaskType.TRANSLATION: "translate",
    TaskType.POLISH: "polish",
    TaskType.TRANSLATE_AND_POLISH: "all_in_one",
}


def _queue_manager() -> QueueManager:
    manager = QueueManager()
    manager.load_tasks()
    return manager


def _parse_task_type(value: Any) -> int:
    if isinstance(value, int):
        if value in _TASK_TYPE_LABELS:
            return value
        raise ValueError(f"Unsupported task_type: {value}")
    normalized = str(value or "translate").strip().lower()
    try:
        return _TASK_TYPE_BY_NAME[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported task_type: {value}") from exc


def _task_type_label(value: Any) -> str:
    return _TASK_TYPE_LABELS.get(value, str(value))


def _task_to_public_dict(index: int, task: QueueTaskItem) -> Dict[str, Any]:
    item = task.to_dict()
    item["index"] = index
    item["task_type"] = _task_type_label(item.get("task_type"))
    return sanitize_payload(item, path=QUEUE_SECURITY_PATH)


def _coerce_index(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("index must be an integer") from exc


class QueueSkill(Skill):
    @property
    def meta(self) -> SkillMeta:
        return SkillMeta(
            name="queue",
            description="Manage the translation task queue.",
            category="queue",
            parameters=[
                SkillParameter(
                    name="action",
                    description="Operation: list, add, remove, clear, run.",
                    type="string",
                    required=True,
                    enum=["list", "add", "remove", "clear", "run"],
                ),
                SkillParameter(
                    name="task_type",
                    description="Task type for new queue items (translate/polish/all_in_one).",
                    type="string",
                    required=False,
                ),
                SkillParameter(
                    name="input_path",
                    description="Input file path for new queue item.",
                    type="string",
                    required=False,
                ),
                SkillParameter(
                    name="output_path",
                    description="Output path for new queue item.",
                    type="string",
                    required=False,
                ),
                SkillParameter(
                    name="profile",
                    description="Profile name for queue item.",
                    type="string",
                    required=False,
                ),
                SkillParameter(
                    name="index",
                    description="Index of the queue item to remove.",
                    type="integer",
                    required=False,
                ),
            ],
            examples=[
                {"action": "list"},
                {
                    "action": "add",
                    "input_path": "/path/to/file.txt",
                    "task_type": "translate",
                    "profile": "default",
                },
                {"action": "remove", "index": 0},
                {"action": "clear"},
            ],
        )

    def execute(self, args: Dict[str, Any]) -> SkillResult:
        action = (args.get("action") or "").strip().lower()

        if action == "list":
            manager = _queue_manager()
            return SkillResult.ok({
                "queue_file": manager.queue_file,
                "count": len(manager.tasks),
                "items": [
                    _task_to_public_dict(i, task)
                    for i, task in enumerate(manager.tasks)
                ],
            })

        if action == "add":
            input_path = args.get("input_path")
            if not input_path:
                return SkillResult.fail(
                    "input_path is required for queue items.", "MISSING_PARAM"
                )
            try:
                task_type = _parse_task_type(args.get("task_type"))
            except ValueError as e:
                return SkillResult.fail(str(e), "INVALID_TASK_TYPE")

            manager = _queue_manager()
            item = QueueTaskItem(
                task_type=task_type,
                input_path=input_path,
                output_path=args.get("output_path"),
                profile=args.get("profile"),
                rules_profile=args.get("rules_profile"),
                source_lang=args.get("source_lang"),
                target_lang=args.get("target_lang"),
                project_type=args.get("project_type"),
                platform=args.get("platform"),
                api_url=args.get("api_url"),
                api_key=args.get("api_key"),
                model=args.get("model"),
                threads=args.get("threads"),
                retry=args.get("retry"),
                timeout=args.get("timeout"),
                rounds=args.get("rounds"),
                pre_lines=args.get("pre_lines"),
                lines_limit=args.get("lines_limit"),
                tokens_limit=args.get("tokens_limit"),
                think_depth=args.get("think_depth"),
                thinking_budget=args.get("thinking_budget"),
            )
            try:
                manager.add_task(item)
            except Exception as e:
                return SkillResult.fail(f"Failed to write queue file: {e}", "WRITE_ERROR")

            index = len(manager.tasks) - 1
            return SkillResult.ok({
                "added": True,
                "queue_file": manager.queue_file,
                "index": index,
                "total": len(manager.tasks),
                "item": _task_to_public_dict(index, item),
            })

        if action == "remove":
            if args.get("index") is None:
                return SkillResult.fail("index is required for remove.", "MISSING_PARAM")
            try:
                index = _coerce_index(args.get("index"))
            except ValueError as e:
                return SkillResult.fail(str(e), "INVALID_INDEX")

            manager = _queue_manager()
            if index < 0 or index >= len(manager.tasks):
                return SkillResult.fail(
                    f"Index {index} out of range (0-{len(manager.tasks) - 1}).", "INVALID_INDEX"
                )
            if not manager.can_modify_task(index):
                return SkillResult.fail(
                    f"Queue item {index} is locked and cannot be removed.", "LOCKED"
                )
            removed = _task_to_public_dict(index, manager.tasks[index])
            if manager.remove_task(index):
                return SkillResult.ok({
                    "removed": True,
                    "item": removed,
                    "total": len(manager.tasks),
                })
            return SkillResult.fail("Failed to write queue file.", "WRITE_ERROR")

        if action == "clear":
            manager = _queue_manager()
            locked = [
                index
                for index, _task in enumerate(manager.tasks)
                if not manager.can_modify_task(index)
            ]
            if locked:
                return SkillResult.fail(
                    f"Cannot clear queue while locked items exist: {locked}",
                    "LOCKED",
                )
            try:
                manager.clear_tasks()
                return SkillResult.ok({"cleared": True, "queue_file": manager.queue_file})
            except Exception as e:
                return SkillResult.fail(f"Failed to clear queue: {e}", "WRITE_ERROR")

        if action == "run":
            return SkillResult.ok({
                "note": "Queue execution is available via CLI.",
                "command": f"{os.path.join(PROJECT_ROOT, 'ainiee_cli.py')} queue --yes",
            })

        return SkillResult.fail(f"Unknown queue action: {action}", "INVALID_ACTION")
