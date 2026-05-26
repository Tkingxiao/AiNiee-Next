import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import rapidjson as json
from rich.text import Text


PROGRESS_FILE_ENV = "AINIEE_AUTOMATION_PROGRESS_FILE"
RUN_ID_ENV = "AINIEE_AUTOMATION_RUN_ID"
TASK_CONFIG_ENV = "AINIEE_AUTOMATION_TASK_CONFIG"
TERMINAL_STATUSES = {"completed", "error", "stopped", "interrupted"}


def get_project_root() -> str:
    return str(Path(__file__).resolve().parents[3])


def get_progress_dir(project_root: str = None) -> str:
    root = project_root or get_project_root()
    path = os.path.join(root, "Resource", "automation_progress")
    os.makedirs(path, exist_ok=True)
    return path


def new_run_id(rule_id: str = "", input_path: str = "") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = str(rule_id or os.path.basename(os.path.normpath(input_path)) or "automation")
    safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in label)[:40]
    return f"{timestamp}_{safe_label}_{uuid.uuid4().hex[:8]}"


def progress_file_for_run(run_id: str, project_root: str = None) -> str:
    return os.path.join(get_progress_dir(project_root), f"{run_id}.jsonl")


def task_config_file_for_run(run_id: str, project_root: str = None) -> str:
    return os.path.join(get_progress_dir(project_root), f"{run_id}.task.json")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_default(value: Any):
    try:
        return str(value)
    except Exception:
        return repr(value)


class AutomationProgressReporter:
    def __init__(
        self,
        progress_file: str,
        run_id: str = "",
        initial: dict = None,
        min_interval: float = 0.1,
        min_percent_delta: int = 1,
        emit_initial: bool = True,
    ):
        self.progress_file = os.path.abspath(progress_file)
        self.run_id = run_id or os.environ.get(RUN_ID_ENV) or Path(progress_file).stem
        self.min_interval = min_interval
        self.min_percent_delta = min_percent_delta
        self._lock = threading.RLock()
        self._last_write_at = 0.0
        self._last_percent = -1
        self._pending_flush = False
        self.state = {
            "run_id": self.run_id,
            "task_id": self.run_id,
            "pid": os.getpid(),
            "event": "state",
            "status": "starting",
            "phase": "starting",
            "message": "",
            "input_path": "",
            "file_name": "",
            "rule_id": "",
            "task_name": "",
            "workflow": "",
            "step_index": 0,
            "step_total": 0,
            "step_type": "",
            "step_name": "",
            "line": 0,
            "total_line": 0,
            "token": 0,
            "time": 0,
            "percent": 0,
            "started_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        if initial:
            self.state.update(initial)
        if emit_initial:
            self.flush(force=True)

    def update(self, **fields: Any) -> None:
        with self._lock:
            self.state.update({key: value for key, value in fields.items() if value is not None})
            self.state["updated_at"] = _now_iso()
            self._normalize_percent()
            self.flush()

    def log(self, message: Any, level: str = "info") -> None:
        text = str(message)
        with self._lock:
            self.state.update({
                "event": "log",
                "level": level,
                "message": text,
                "updated_at": _now_iso(),
            })
            self.flush(force=True)
            self.state["event"] = "state"

    def update_progress(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        fields = dict(data)
        fields.setdefault("phase", "task")
        fields.setdefault("status", "running")
        if fields.get("file_path_full") and not fields.get("input_path"):
            fields["input_path"] = fields.get("file_path_full")
        if fields.get("file_name"):
            fields["file_name"] = fields.get("file_name")
        self.update(**fields)

    def update_status(self, status: str = "", message: str = "") -> None:
        fields = {}
        if status:
            fields["status"] = status
        if message:
            fields["message"] = message
        self.update(**fields)

    def update_workflow_step(self, index: int, total: int, step_type: str, step_name: str = "") -> None:
        self.update(
            status="workflow",
            phase="workflow",
            step_index=index,
            step_total=total,
            step_type=step_type,
            step_name=step_name or step_type,
            message=step_name or step_type,
        )

    def finish(self, status: str, message: str = "") -> None:
        with self._lock:
            self.state.update({
                "event": "state",
                "status": status,
                "phase": "finished" if status == "completed" else "error",
                "message": message or status,
                "percent": 100 if status == "completed" else self.state.get("percent", 0),
                "finished_at": _now_iso(),
                "updated_at": _now_iso(),
            })
            self._normalize_percent()
            if status == "completed":
                self.state["percent"] = 100
            self.flush(force=True)

    def _normalize_percent(self) -> None:
        total = self.state.get("total_line") or self.state.get("total") or 0
        current = self.state.get("line") or self.state.get("completed") or 0
        try:
            total = int(total or 0)
            current = int(current or 0)
        except (TypeError, ValueError):
            total = 0
            current = 0
        if total > 0:
            self.state["percent"] = max(0, min(100, int(current * 100 / total)))
            self.state["line"] = current
            self.state["total_line"] = total
            return

        step_total = int(self.state.get("step_total") or 0)
        step_index = int(self.state.get("step_index") or 0)
        if step_total > 0:
            self.state["percent"] = max(0, min(100, int(max(step_index - 1, 0) * 100 / step_total)))

    def flush(self, force: bool = False) -> None:
        now = time.monotonic()
        percent = int(self.state.get("percent") or 0)
        should_write = (
            force
            or self.state.get("status") in TERMINAL_STATUSES
            or (now - self._last_write_at) >= self.min_interval
            or abs(percent - self._last_percent) >= self.min_percent_delta
        )
        if not should_write:
            self._pending_flush = True
            return

        os.makedirs(os.path.dirname(self.progress_file), exist_ok=True)
        event = dict(self.state)
        event["written_at"] = _now_iso()
        line = json.dumps(event, ensure_ascii=False, default=_json_default)
        with open(self.progress_file, "a", encoding="utf-8") as file:
            file.write(line + "\n")
            file.flush()
        self._last_write_at = now
        self._last_percent = percent
        self._pending_flush = False


class AutomationProgressUI:
    def __init__(self, reporter: AutomationProgressReporter):
        self.reporter = reporter
        self._lock = threading.RLock()
        self.logs: List[Any] = []
        self.log_file = None
        self.taken_over = False
        self._last_progress_data: Dict[str, Any] = {}

    def log(self, message: Any) -> None:
        with self._lock:
            text = str(message)
            self.logs.append(Text(text))
            self.logs = self.logs[-100:]
            if self.log_file:
                try:
                    self.log_file.write(f"[{time.strftime('%H:%M:%S')}] {text}\n")
                    self.log_file.flush()
                except Exception:
                    pass
            self.reporter.log(text)

    def update_progress(self, event, data):
        with self._lock:
            if isinstance(data, dict):
                self._last_progress_data = data
                self.reporter.update_progress(data)

    def update_status(self, event, data):
        if isinstance(data, dict):
            self.reporter.update_status(data.get("status", ""), data.get("message", ""))

    def on_source_data(self, event, data):
        return None

    def on_result_data(self, event, data):
        return None

    def toggle_log_filter(self):
        return None

    def refresh_layout(self):
        return None

    def finish(self, status: str, message: str = ""):
        self.reporter.finish(status, message)


def reporter_from_env(initial: dict = None) -> Optional[AutomationProgressReporter]:
    progress_file = os.environ.get(PROGRESS_FILE_ENV)
    if not progress_file:
        return None
    return AutomationProgressReporter(progress_file, os.environ.get(RUN_ID_ENV, ""), initial=initial)


def read_progress_file(path: str, max_logs: int = 20) -> dict:
    state = {}
    logs = []
    try:
        with open(path, "r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if event.get("event") == "log":
                    logs.append(event)
                    logs = logs[-max_logs:]
                    continue
                state.update(event)
    except OSError:
        pass
    if logs:
        state["logs"] = logs
    state["_path"] = path
    return state


class AutomationProgressStore:
    def __init__(self, project_root: str = None):
        self.progress_dir = get_progress_dir(project_root)

    def list_states(self, limit: int = 20) -> List[dict]:
        states = []
        for path in Path(self.progress_dir).glob("*.jsonl"):
            state = read_progress_file(str(path))
            if state:
                states.append(state)
        states.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return states[:limit]
