import argparse
import os
import sys
import traceback

import rapidjson as json

from ModuleFolders.Base.Base import Base, TUIHandler
from ModuleFolders.Base.EventManager import EventManager
from ModuleFolders.Infrastructure.Automation.AutomationProgress import (
    AutomationProgressUI,
    reporter_from_env,
)


def _load_task_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def run_worker(task_config_path: str) -> int:
    task_config = _load_task_config(task_config_path)
    reporter = reporter_from_env(
        {
            "rule_id": task_config.get("rule_id", ""),
            "input_path": task_config.get("input_path", ""),
            "file_name": os.path.basename(os.path.normpath(task_config.get("input_path", ""))),
            "workflow": task_config.get("workflow_description", ""),
            "status": "starting",
            "phase": "worker",
            "message": "Automation worker starting",
        }
    )

    try:
        import ainiee_cli
        from ModuleFolders.Infrastructure.Automation.WorkflowRunner import WorkflowRunner

        cli = ainiee_cli.CLIMenu()
        ui = AutomationProgressUI(reporter) if reporter else None
        if ui:
            cli.ui = ui
            TUIHandler.set_ui(ui)
            Base.print = ui.log
            EventManager.get_singleton().subscribe(Base.EVENT.TASK_UPDATE, ui.update_progress)
            EventManager.get_singleton().subscribe(Base.EVENT.SYSTEM_STATUS_UPDATE, ui.update_status)

        if reporter:
            reporter.update(status="workflow", phase="workflow", message="Workflow started")

        WorkflowRunner(cli, progress_reporter=reporter).run(task_config)

        if ui:
            ui.finish("completed", "Workflow completed")
        return 0
    except Exception as exc:
        if reporter:
            reporter.log(traceback.format_exc(), level="error")
            reporter.finish("error", str(exc))
        return 1
    finally:
        if "ui" in locals() and ui:
            EventManager.get_singleton().unsubscribe(Base.EVENT.TASK_UPDATE, ui.update_progress)
            EventManager.get_singleton().unsubscribe(Base.EVENT.SYSTEM_STATUS_UPDATE, ui.update_status)
        TUIHandler.clear()


def main() -> int:
    parser = argparse.ArgumentParser(description="AiNiee automation worker")
    parser.add_argument("--task-config", required=True)
    args = parser.parse_args()
    return run_worker(args.task_config)


if __name__ == "__main__":
    sys.exit(main())
