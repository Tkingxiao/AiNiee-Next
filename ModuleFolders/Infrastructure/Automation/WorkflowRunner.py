"""
Automation workflow runner.

This module keeps watch/scheduler managers focused on triggering events while
the runner adapts those events to existing AiNiee task, queue, and glossary
analysis capabilities.
"""
import copy
import os
import time
from typing import Any, Dict, Iterable, List, Optional

from rich.console import Console

from ModuleFolders.Base.Base import Base
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType


console = Console()


TASK_TYPE_ALIASES = {
    "translate": TaskType.TRANSLATION,
    "translation": TaskType.TRANSLATION,
    "polish": TaskType.POLISH,
    "polishing": TaskType.POLISH,
    "all_in_one": TaskType.TRANSLATE_AND_POLISH,
    "translate_and_polish": TaskType.TRANSLATE_AND_POLISH,
}


WORKFLOW_STEP_LABELS = {
    "extract_glossary": "AI glossary analysis",
    "translate": "Translation",
    "polish": "Polishing",
    "all_in_one": "Translation + polishing",
    "queue": "Add to queue",
    "run_queue": "Run queue",
}


def normalize_task_type(value: Any) -> int:
    if value in (TaskType.TRANSLATION, TaskType.POLISH, TaskType.TRANSLATE_AND_POLISH):
        return value
    text = str(value or "").strip().lower()
    return TASK_TYPE_ALIASES.get(text, TaskType.TRANSLATION)


def task_type_to_step_type(value: Any) -> str:
    normalized = normalize_task_type(value)
    if normalized == TaskType.POLISH:
        return "polish"
    if normalized == TaskType.TRANSLATE_AND_POLISH:
        return "all_in_one"
    return "translate"


def default_workflow_steps(task_type: Any = "translation", auto_start: bool = True) -> List[dict]:
    if not auto_start:
        return [{"type": "queue", "task_type": task_type_to_step_type(task_type)}]
    return [{"type": task_type_to_step_type(task_type)}]


def normalize_workflow_steps(
    steps: Optional[Iterable[dict]],
    task_type: Any = "translation",
    auto_start: bool = True,
) -> List[dict]:
    normalized_steps: List[dict] = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        step_type = str(step.get("type") or "").strip().lower()
        if not step_type:
            continue
        if step_type in {"translation", "translate"}:
            step_type = "translate"
        elif step_type in {"polishing", "polish"}:
            step_type = "polish"
        elif step_type in {"translate_and_polish", "all_in_one"}:
            step_type = "all_in_one"
        elif step_type in {"glossary", "analysis", "extract_glossary"}:
            step_type = "extract_glossary"
        elif step_type in {"add_to_queue", "queue"}:
            step_type = "queue"
        elif step_type in {"start_queue", "run_queue"}:
            step_type = "run_queue"
        else:
            continue

        prepared = dict(step)
        prepared["type"] = step_type
        if step_type == "queue":
            prepared["task_type"] = task_type_to_step_type(prepared.get("task_type", task_type))
        normalized_steps.append(prepared)

    return normalized_steps or default_workflow_steps(task_type, auto_start)


def describe_workflow_steps(steps: Iterable[dict]) -> str:
    labels = []
    for step in steps or []:
        step_type = str(step.get("type") or "").strip()
        labels.append(WORKFLOW_STEP_LABELS.get(step_type, step_type or "?"))
    return " -> ".join(labels)


def is_queue_only_workflow(steps: Iterable[dict]) -> bool:
    step_types = [str(step.get("type") or "").strip().lower() for step in steps or [] if isinstance(step, dict)]
    return bool(step_types) and all(step_type in {"queue", "run_queue"} for step_type in step_types)


class WorkflowRunner:
    """Execute configured automation workflow steps against a host CLIMenu."""

    def __init__(self, host, progress_reporter=None):
        self.host = host
        self.progress_reporter = progress_reporter

    def run(self, task_config: dict) -> bool:
        input_path = task_config.get("input_path") or ""
        steps = normalize_workflow_steps(
            task_config.get("workflow_steps"),
            task_config.get("task_type", "translation"),
            task_config.get("auto_start", True),
        )

        original_active_profile = getattr(self.host, "active_profile_name", "default")
        original_rules_profile = getattr(self.host, "active_rules_profile_name", "default")
        original_root_config = copy.deepcopy(getattr(self.host, "root_config", {}))
        original_config = copy.deepcopy(getattr(self.host, "config", {}))

        try:
            self._apply_profile_context(task_config)

            for index, step in enumerate(steps, 1):
                step = self._with_task_defaults(step, task_config)
                step_type = step.get("type")
                self._report_step(index, len(steps), step_type)
                self._log("info", f"Workflow step {index}/{len(steps)}: {step_type}")
                if step_type == "extract_glossary":
                    self._run_glossary_step(input_path, step)
                elif step_type == "translate":
                    self._run_task_step(TaskType.TRANSLATION, input_path, step)
                elif step_type == "polish":
                    self._run_task_step(TaskType.POLISH, input_path, step, resume=bool(step.get("resume", True)))
                elif step_type == "all_in_one":
                    self._run_all_in_one_step(input_path, step)
                elif step_type == "queue":
                    self._run_queue_add_step(input_path, task_config, step)
                elif step_type == "run_queue":
                    self._run_queue_step()
                else:
                    raise ValueError(f"Unsupported workflow step: {step_type}")

            return True
        finally:
            self.host.active_profile_name = original_active_profile
            self.host.active_rules_profile_name = original_rules_profile
            self.host.root_config = original_root_config
            self.host.config = original_config

    def _report_step(self, index: int, total: int, step_type: str):
        if not self.progress_reporter:
            return
        label = WORKFLOW_STEP_LABELS.get(step_type, step_type or "?")
        self.progress_reporter.update_workflow_step(index, total, step_type, label)

    def _with_task_defaults(self, step: dict, task_config: dict) -> dict:
        prepared = dict(step)
        if (
            prepared.get("type") in {"translate", "polish", "all_in_one"}
            and task_config.get("output_path")
            and not prepared.get("output_path")
            and not prepared.get("output_root")
        ):
            prepared["output_path"] = task_config.get("output_path")
            prepared["output_mode"] = "exact"
        return prepared

    def _apply_profile_context(self, task_config: dict):
        profile = task_config.get("profile")
        rules_profile = task_config.get("rules_profile")
        if profile or rules_profile:
            self.host.load_config(
                active_profile_name=profile or getattr(self.host, "active_profile_name", None),
                active_rules_profile_name=rules_profile or getattr(self.host, "active_rules_profile_name", None),
            )

    def _run_glossary_step(self, input_path: str, step: dict):
        if not input_path:
            raise ValueError("Glossary analysis requires input_path")
        if not os.path.exists(input_path):
            raise FileNotFoundError(input_path)

        from ModuleFolders.Service.GlossaryAnalysis import GlossaryAnalyzer

        analyzer = GlossaryAnalyzer(self.host)
        analysis_result = analyzer.execute_analysis(
            input_path,
            int(step.get("analysis_percent", 100) or 100),
            step.get("analysis_lines"),
            temp_config=None,
            analysis_mode=str(step.get("analysis_mode") or "full"),
            prompt_file=step.get("prompt_file") or None,
            translate_during_analysis=bool(step.get("translate_during_analysis", True)),
            new=bool(step.get("new", True)),
            replace=bool(step.get("replace", True)),
            source_label=step.get("source_label") or self._source_label_for(input_path),
            source_volume=step.get("source_volume"),
        )
        if analysis_result is None:
            raise RuntimeError("Glossary analysis returned no result")

        min_frequency = int(step.get("min_frequency", 2) or 2)
        save_result = analyzer.filter_and_save(analysis_result, min_frequency)
        if save_result is None:
            raise RuntimeError("Glossary analysis did not produce savable rules")

        structured_rules = save_result.get("structured_rules")
        incremental_options = save_result.get("incremental_options")
        if structured_rules:
            analyzer.save_structured_rules_directly(
                structured_rules,
                save_mode=str(step.get("save_mode") or "import"),
                base_glossary_path=save_result.get("glossary_path"),
                merge_options=incremental_options,
            )
        elif save_result.get("glossary_data"):
            analyzer.save_glossary_directly(
                save_result["glossary_data"],
                save_mode=str(step.get("save_mode") or "import"),
                base_glossary_path=save_result.get("glossary_path"),
                merge_options=incremental_options,
            )

    def _run_task_step(self, task_type: int, input_path: str, step: dict, resume: bool = False):
        if not input_path:
            raise ValueError("Task step requires input_path")
        if not os.path.exists(input_path):
            raise FileNotFoundError(input_path)

        output_path = self._resolve_step_output_path(input_path, step)
        previous_output_path = self.host.config.get("label_output_path", "")
        previous_auto_output = self.host.config.get("auto_set_output_path", False)
        if output_path:
            self.host.config["label_output_path"] = output_path
            self.host.config["auto_set_output_path"] = False

        try:
            ok = self.host.run_task(
                task_type,
                target_path=input_path,
                continue_status=resume,
                non_interactive=True,
                from_queue=True,
                skip_preflight=True,
                save_runtime_config=False,
                automation_progress=bool(self.progress_reporter),
            )
        finally:
            self.host.config["label_output_path"] = previous_output_path
            self.host.config["auto_set_output_path"] = previous_auto_output

        if not ok:
            raise RuntimeError("Task blocked before start")

    def _run_all_in_one_step(self, input_path: str, step: dict):
        if not self.host.prompt_selection_guard.ensure_prompts_selected(
            TaskType.TRANSLATE_AND_POLISH,
            interactive=False,
        ):
            raise RuntimeError("Required prompt selection is missing for all-in-one task.")

        self._run_task_step(TaskType.TRANSLATION, input_path, step, resume=bool(step.get("resume", False)))
        if Base.work_status != Base.STATUS.STOPING:
            polish_step = dict(step)
            polish_step.setdefault("resume", True)
            self._run_task_step(TaskType.POLISH, input_path, polish_step, resume=True)

    def _run_queue_add_step(self, input_path: str, task_config: dict, step: dict):
        from ModuleFolders.Service.TaskQueue.QueueManager import QueueManager, QueueTaskItem

        if not input_path:
            raise ValueError("Queue step requires input_path")
        if not os.path.exists(input_path):
            raise FileNotFoundError(input_path)

        queue_manager = QueueManager()
        output_path = self._resolve_step_output_path(input_path, step) or task_config.get("output_path") or None
        queue_manager.add_task(
            QueueTaskItem(
                normalize_task_type(step.get("task_type", task_config.get("task_type", "translation"))),
                input_path,
                output_path=output_path,
                profile=task_config.get("profile") or None,
                rules_profile=task_config.get("rules_profile") or None,
            )
        )

    def _run_queue_step(self):
        from ModuleFolders.Service.TaskQueue.QueueManager import QueueManager

        queue_manager = QueueManager()
        if not queue_manager.tasks:
            self._log("warning", "Task queue is empty")
            return
        if queue_manager.is_running:
            self._log("info", "Task queue is already running")
            return

        self.host._is_queue_mode = True
        self.host.start_queue_log_monitor()
        queue_manager.start_queue(self.host)
        try:
            while queue_manager.is_running:
                time.sleep(0.5)
        finally:
            self.host.stop_queue_log_monitor()
            self.host._is_queue_mode = False

    def _resolve_step_output_path(self, input_path: str, step: dict) -> str:
        output_path = str(step.get("output_path") or step.get("output_root") or "").strip()
        if not output_path:
            return ""

        mode = str(step.get("output_mode") or "subdir").strip().lower()
        if mode == "exact":
            return os.path.abspath(os.path.expanduser(output_path))

        base_name = os.path.basename(os.path.normpath(input_path))
        if os.path.isfile(input_path):
            base_name = os.path.splitext(base_name)[0]
        return os.path.join(os.path.abspath(os.path.expanduser(output_path)), f"{base_name}_AiNiee_Output")

    def _source_label_for(self, input_path: str) -> str:
        base_name = os.path.basename(os.path.normpath(input_path))
        if os.path.isfile(input_path):
            base_name = os.path.splitext(base_name)[0]
        return base_name or "Automation"

    def _log(self, level: str, message: str):
        ui = getattr(self.host, "ui", None)
        if ui is not None and hasattr(ui, "log"):
            try:
                ui.log(f"[{level}] {message}")
                return
            except Exception:
                pass
        console.print(message)
