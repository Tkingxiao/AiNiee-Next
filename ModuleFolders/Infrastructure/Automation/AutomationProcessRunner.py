import os
import subprocess
import sys
import threading
from typing import Dict

import rapidjson as json

from ModuleFolders.Infrastructure.Automation.AutomationProgress import (
    PROGRESS_FILE_ENV,
    RUN_ID_ENV,
    TERMINAL_STATUSES,
    AutomationProgressReporter,
    new_run_id,
    progress_file_for_run,
    read_progress_file,
    task_config_file_for_run,
)
from ModuleFolders.Infrastructure.Automation.WorkflowRunner import describe_workflow_steps


class AutomationProcessRunner:
    _lock = threading.RLock()
    _processes: Dict[str, subprocess.Popen] = {}

    @classmethod
    def start(cls, task_config: dict, project_root: str = None) -> dict:
        project_root = project_root or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        run_id = new_run_id(task_config.get("rule_id", ""), task_config.get("input_path", ""))
        progress_file = progress_file_for_run(run_id, project_root)
        task_config_path = task_config_file_for_run(run_id, project_root)

        prepared_config = dict(task_config)
        prepared_config["automation_run_id"] = run_id
        prepared_config["automation_progress_file"] = progress_file
        prepared_config["workflow_description"] = describe_workflow_steps(prepared_config.get("workflow_steps") or [])

        with open(task_config_path, "w", encoding="utf-8") as file:
            json.dump(prepared_config, file, ensure_ascii=False, indent=2)

        reporter = AutomationProgressReporter(
            progress_file,
            run_id,
            initial={
                "status": "queued",
                "phase": "queued",
                "message": "Automation task queued",
                "input_path": prepared_config.get("input_path", ""),
                "file_name": os.path.basename(os.path.normpath(prepared_config.get("input_path", ""))),
                "rule_id": prepared_config.get("rule_id", ""),
                "workflow": prepared_config.get("workflow_description", ""),
            },
        )

        env = os.environ.copy()
        env[PROGRESS_FILE_ENV] = progress_file
        env[RUN_ID_ENV] = run_id

        log_path = os.path.join(os.path.dirname(progress_file), f"{run_id}.worker.log")
        log_file = open(log_path, "a", encoding="utf-8")
        cmd = [
            sys.executable,
            "-m",
            "ModuleFolders.Infrastructure.Automation.AutomationWorker",
            "--task-config",
            task_config_path,
        ]
        process = subprocess.Popen(
            cmd,
            cwd=project_root,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        reporter.update(status="running", phase="worker", pid=process.pid, message="Automation worker started")

        with cls._lock:
            cls._processes[run_id] = process

        threading.Thread(
            target=cls._watch_process,
            args=(run_id, process, log_file, progress_file),
            daemon=True,
        ).start()

        return {
            "run_id": run_id,
            "progress_file": progress_file,
            "task_config_file": task_config_path,
            "pid": process.pid,
        }

    @classmethod
    def _watch_process(cls, run_id: str, process: subprocess.Popen, log_file, progress_file: str):
        return_code = process.wait()
        try:
            log_file.close()
        except Exception:
            pass

        state = read_progress_file(progress_file)
        if state.get("status") not in TERMINAL_STATUSES:
            reporter = AutomationProgressReporter(progress_file, run_id, emit_initial=False)
            if return_code == 0:
                reporter.finish("completed", "Automation worker completed")
            else:
                reporter.finish("interrupted", f"Automation worker exited with code {return_code}")

        with cls._lock:
            cls._processes.pop(run_id, None)

    @classmethod
    def get_process(cls, run_id: str):
        with cls._lock:
            return cls._processes.get(run_id)

    @classmethod
    def snapshot_processes(cls) -> dict:
        with cls._lock:
            return dict(cls._processes)
