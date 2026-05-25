"""
自动化菜单模块
从 ainiee_cli.py 分离
"""
import os
import threading
import time

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.table import Table

from ModuleFolders.Infrastructure.Automation.WorkflowRunner import (
    describe_workflow_steps,
    normalize_task_type,
    normalize_workflow_steps,
    task_type_to_step_type,
)

console = Console()


class AutomationMenu:
    """自动化设置菜单"""

    def __init__(self, host):
        """
        初始化自动化菜单

        Args:
            host: CLIMenu实例，提供config、i18n等依赖
        """
        self.host = host
        self.scheduler_manager = None
        self.watch_manager = None

    @property
    def config(self):
        return self.host.config

    @property
    def i18n(self):
        return self.host.i18n

    def _ensure_managers(self):
        """确保管理器已初始化"""
        from ModuleFolders.Infrastructure.Automation import SchedulerManager, WatchManager

        if self.scheduler_manager is None:
            self.scheduler_manager = SchedulerManager(execute_callback=self._execute_scheduled_task)
            self.scheduler_manager.load_from_config(self.config)
            self.scheduler_manager.set_callback(self._execute_scheduled_task)
        if self.watch_manager is None:
            self.watch_manager = WatchManager(
                task_callback=self._execute_watch_task,
                queue_callback=self._enqueue_watch_task,
            )
            self.watch_manager.load_from_config(self.config)
            self.watch_manager.set_callbacks(
                task_callback=self._execute_watch_task,
                queue_callback=self._enqueue_watch_task,
            )

    def _enqueue_watch_task(self, task_config):
        """Add a watch-triggered workflow task to the central queue."""
        from ModuleFolders.Service.TaskQueue.QueueManager import QueueManager, QueueTaskItem

        queue_manager = QueueManager()
        queue_manager.add_task(
            QueueTaskItem(
                normalize_task_type(task_config.get("task_type", "translation")),
                task_config.get("input_path", ""),
                output_path=task_config.get("output_path") or None,
                profile=task_config.get("profile") or None,
                rules_profile=task_config.get("rules_profile") or None,
                workflow_steps=task_config.get("workflow_steps") or [],
                source=task_config.get("source"),
                rule_id=task_config.get("rule_id"),
            )
        )

        if task_config.get("auto_start", True):
            self._run_queue_if_needed()

    def _run_queue_if_needed(self):
        from ModuleFolders.Service.TaskQueue.QueueManager import QueueManager

        queue_manager = QueueManager()
        if not queue_manager.tasks or queue_manager.is_running:
            return

        self.host._is_queue_mode = True
        self.host.start_queue_log_monitor()
        queue_manager.start_queue(self.host)

        def queue_cleanup():
            try:
                while queue_manager.is_running:
                    time.sleep(0.5)
            finally:
                self.host.stop_queue_log_monitor()
                self.host._is_queue_mode = False

        threading.Thread(target=queue_cleanup, daemon=True).start()

    def _execute_watch_task(self, task_config):
        from ModuleFolders.Infrastructure.Automation.WorkflowRunner import WorkflowRunner

        return WorkflowRunner(self.host).run(task_config)

    def _execute_scheduled_task(self, task_config):
        workflow_steps = task_config.get("workflow_steps") or []
        if workflow_steps:
            from ModuleFolders.Infrastructure.Automation.WorkflowRunner import WorkflowRunner

            return WorkflowRunner(self.host).run(task_config)
        if task_config.get("run_queue"):
            return self._run_queue_if_needed()
        return self._execute_watch_task(task_config)

    def show(self):
        """显示自动化菜单（入口方法）"""
        self._ensure_managers()

        while True:
            self.host.display_banner()
            console.print(Panel(f"[bold]{self.i18n.get('menu_automation')}[/bold]"))
            console.print(f"[dim]{self.i18n.get('automation_cooperation_hint')}[/dim]\n")

            # 获取状态
            sched_status = self.scheduler_manager.get_status()
            watch_status = self.watch_manager.get_status()

            table = Table(show_header=False, box=None)
            table.add_row("[cyan]1.[/]", f"{self.i18n.get('menu_automation_scheduler')}",
                         f"[{'green' if sched_status['running'] else 'dim'}]{self.i18n.get('automation_running') if sched_status['running'] else self.i18n.get('automation_stopped')}[/] ({sched_status['task_count']} {self.i18n.get('automation_task_count')})")
            table.add_row("[cyan]2.[/]", f"{self.i18n.get('menu_automation_watch')}",
                         f"[{'green' if watch_status['running'] else 'dim'}]{self.i18n.get('automation_running') if watch_status['running'] else self.i18n.get('automation_stopped')}[/] ({watch_status['rule_count']} {self.i18n.get('automation_task_count')})")
            table.add_row("[cyan]3.[/]", f"{self.i18n.get('menu_automation_status')}")
            console.print(table)
            console.print(f"\n[dim]0. {self.i18n.get('menu_back')}[/dim]")

            choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=["0", "1", "2", "3"], show_choices=False)

            if choice == 0:
                # 保存配置
                self.scheduler_manager.save_to_config(self.config)
                self.watch_manager.save_to_config(self.config)
                self.host.save_config()
                break
            elif choice == 1:
                self.scheduler_submenu()
            elif choice == 2:
                self.watch_submenu()
            elif choice == 3:
                self.automation_status_view()

    def scheduler_submenu(self):
        """定时任务子菜单"""
        from ModuleFolders.Infrastructure.Automation.SchedulerManager import ScheduledTask

        while True:
            self.host.display_banner()
            console.print(Panel(f"[bold]{self.i18n.get('scheduler_title')}[/bold]"))
            console.print(f"[dim]{self.i18n.get('scheduler_usage_hint')}[/dim]\n")

            status = self.scheduler_manager.get_status()

            table = Table(show_header=False, box=None)
            table.add_row("[cyan]1.[/]", f"{self.i18n.get('scheduler_enabled')}: [{'green' if status['running'] else 'red'}]{'ON' if status['running'] else 'OFF'}[/]")
            table.add_row("[cyan]2.[/]", self.i18n.get('scheduler_add_task'))
            table.add_row("[cyan]3.[/]", self.i18n.get('scheduler_edit_task'))
            table.add_row("[cyan]4.[/]", self.i18n.get('scheduler_remove_task'))
            table.add_row("[cyan]5.[/]", self.i18n.get('scheduler_view_logs'))
            console.print(table)

            # 显示任务列表
            tasks = self.scheduler_manager.get_all_tasks()
            if tasks:
                console.print(f"\n[bold]{self.i18n.get('scheduler_task_list')}:[/bold]")
                task_table = Table(box=None)
                task_table.add_column("ID", style="cyan")
                task_table.add_column(self.i18n.get('scheduler_task_name'))
                task_table.add_column(self.i18n.get('scheduler_cron_expr'))
                task_table.add_column(self.i18n.get('scheduler_next_run'))
                task_table.add_column(self.i18n.get('label_status'))

                for task in tasks:
                    next_run = task.next_run.strftime("%m-%d %H:%M") if task.next_run else "-"
                    status_str = "[green]●[/]" if task.enabled else "[dim]○[/]"
                    task_table.add_row(task.id, task.name, task.schedule, next_run, status_str)
                console.print(task_table)
            else:
                console.print(f"\n[dim]{self.i18n.get('scheduler_no_tasks')}[/dim]")

            console.print(f"\n[dim]0. {self.i18n.get('menu_back')}[/dim]")
            choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=["0", "1", "2", "3", "4", "5"], show_choices=False)

            if choice == 0:
                break
            elif choice == 1:
                if self.scheduler_manager.running:
                    self.scheduler_manager.stop()
                else:
                    self.scheduler_manager.start()
            elif choice == 2:
                self.add_scheduled_task()
            elif choice == 3:
                self.edit_scheduled_task()
            elif choice == 4:
                self.remove_scheduled_task()
            elif choice == 5:
                self.view_automation_logs(self.scheduler_manager.get_logs())

    def add_scheduled_task(self):
        """添加定时任务"""
        from ModuleFolders.Infrastructure.Automation.SchedulerManager import ScheduledTask

        console.print(Panel(f"[bold]{self.i18n.get('scheduler_add_task')}[/bold]"))

        task_id = Prompt.ask(self.i18n.get('prompt_task_id_new'))
        if self.scheduler_manager.get_task(task_id):
            console.print(f"[red]{self.i18n.get('msg_id_exists')}[/red]")
            return

        name = Prompt.ask(self.i18n.get('scheduler_task_name'))
        schedule = Prompt.ask(self.i18n.get('scheduler_cron_expr'), default="0 2 * * *")

        # 验证 cron 表达式
        try:
            from ModuleFolders.Infrastructure.Automation.SchedulerManager import CronParser
            CronParser.parse(schedule)
        except ValueError:
            console.print(f"[red]{self.i18n.get('msg_invalid_cron')}[/red]")
            return

        input_path = Prompt.ask(self.i18n.get('scheduler_input_path'))
        run_queue = input_path.strip().lower() in {"queue", "__queue__", "队列"}
        if not run_queue and not os.path.exists(input_path):
            console.print(f"[red]{self.i18n.get('msg_path_not_exist')}[/red]")
            return

        # 选择任务类型
        task_types = ["translation", "polishing", "all_in_one"]
        console.print(f"\n{self.i18n.get('scheduler_task_type')}:")
        for i, t in enumerate(task_types):
            console.print(f"  [cyan]{i+1}.[/] {self.i18n.get(f'task_type_{t}')}")
        type_choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=["1", "2", "3"], default=1, show_choices=False)
        task_type = task_types[type_choice - 1]

        # 选择配置
        profiles = self.host._get_profiles_list(self.host.profiles_dir)
        console.print(f"\n{self.i18n.get('scheduler_profile')}:")
        for i, p in enumerate(profiles):
            console.print(f"  [cyan]{i+1}.[/] {p}")
        profile_choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=[str(i+1) for i in range(len(profiles))], default=1, show_choices=False)
        profile = profiles[profile_choice - 1]

        workflow_steps = []
        if run_queue:
            workflow_steps = [{"type": "run_queue"}]
        elif Confirm.ask("为这个定时任务配置自定义工作流?", default=False):
            workflow_steps, _ = self._prompt_workflow_steps(default_task_type=task_type)

        task = ScheduledTask(
            task_id=task_id,
            name=name,
            schedule=schedule,
            input_path=input_path,
            profile=profile,
            task_type=task_type,
            workflow_steps=workflow_steps,
            run_queue=run_queue,
        )

        if self.scheduler_manager.add_task(task):
            console.print(f"[green]{self.i18n.get('scheduler_task_added')}[/green]")
            self.scheduler_manager.save_to_config(self.config)
            self.host.save_config()

    def edit_scheduled_task(self):
        """编辑定时任务"""
        tasks = self.scheduler_manager.get_all_tasks()
        if not tasks:
            console.print(f"[dim]{self.i18n.get('scheduler_no_tasks')}[/dim]")
            return

        console.print(Panel(f"[bold]{self.i18n.get('scheduler_edit_task')}[/bold]"))
        for i, task in enumerate(tasks):
            console.print(f"  [cyan]{i+1}.[/] {task.id} - {task.name}")

        choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=[str(i+1) for i in range(len(tasks))] + ["0"], default=0, show_choices=False)
        if choice == 0:
            return

        task = tasks[choice - 1]

        # 编辑选项
        console.print(f"\n[bold]{task.name}[/bold]")
        console.print(f"1. {self.i18n.get('label_enabled')}: {'ON' if task.enabled else 'OFF'}")
        console.print(f"2. {self.i18n.get('scheduler_cron_expr')}: {task.schedule}")
        console.print(f"3. {self.i18n.get('scheduler_input_path')}: {task.input_path}")
        console.print(f"4. {self.i18n.get('watch_mode')}: {describe_workflow_steps(task.workflow_steps) if task.workflow_steps else '-'}")

        edit_choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=["0", "1", "2", "3", "4"], default=0, show_choices=False)

        if edit_choice == 1:
            self.scheduler_manager.update_task(task.id, enabled=not task.enabled)
        elif edit_choice == 2:
            new_schedule = Prompt.ask(self.i18n.get('scheduler_cron_expr'), default=task.schedule)
            try:
                from ModuleFolders.Infrastructure.Automation.SchedulerManager import CronParser
                CronParser.parse(new_schedule)
                self.scheduler_manager.update_task(task.id, schedule=new_schedule)
            except ValueError:
                console.print(f"[red]{self.i18n.get('msg_invalid_cron')}[/red]")
        elif edit_choice == 3:
            new_path = Prompt.ask(self.i18n.get('scheduler_input_path'), default=task.input_path)
            run_queue = new_path.strip().lower() in {"queue", "__queue__", "队列"}
            if run_queue or os.path.exists(new_path):
                workflow_steps = [{"type": "run_queue"}] if run_queue else task.workflow_steps
                self.scheduler_manager.update_task(task.id, input_path=new_path, run_queue=run_queue, workflow_steps=workflow_steps)
            else:
                console.print(f"[red]{self.i18n.get('msg_path_not_exist')}[/red]")
        elif edit_choice == 4:
            workflow_steps, _ = self._prompt_workflow_steps(
                default_task_type=task.task_type,
                current_steps=task.workflow_steps,
                current_auto_start=True,
            )
            self.scheduler_manager.update_task(task.id, workflow_steps=workflow_steps, run_queue=False)

        if edit_choice > 0:
            console.print(f"[green]{self.i18n.get('scheduler_task_updated')}[/green]")
            self.scheduler_manager.save_to_config(self.config)
            self.host.save_config()

    def remove_scheduled_task(self):
        """删除定时任务"""
        tasks = self.scheduler_manager.get_all_tasks()
        if not tasks:
            console.print(f"[dim]{self.i18n.get('scheduler_no_tasks')}[/dim]")
            return

        console.print(Panel(f"[bold]{self.i18n.get('scheduler_remove_task')}[/bold]"))
        for i, task in enumerate(tasks):
            console.print(f"  [cyan]{i+1}.[/] {task.id} - {task.name}")

        choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=[str(i+1) for i in range(len(tasks))] + ["0"], default=0, show_choices=False)
        if choice == 0:
            return

        task = tasks[choice - 1]
        if Confirm.ask(self.i18n.get('scheduler_confirm_remove')):
            self.scheduler_manager.remove_task(task.id)
            console.print(f"[green]{self.i18n.get('scheduler_task_removed')}[/green]")
            self.scheduler_manager.save_to_config(self.config)
            self.host.save_config()

    def watch_submenu(self):
        """文件夹监控子菜单"""
        from ModuleFolders.Infrastructure.Automation.WatchManager import WatchRule

        while True:
            self.host.display_banner()
            console.print(Panel(f"[bold]{self.i18n.get('watch_title')}[/bold]"))
            console.print(f"[dim]{self.i18n.get('watch_usage_hint')}[/dim]\n")

            status = self.watch_manager.get_status()

            table = Table(show_header=False, box=None)
            table.add_row("[cyan]1.[/]", f"{self.i18n.get('watch_enabled')}: [{'green' if status['running'] else 'red'}]{'ON' if status['running'] else 'OFF'}[/]")
            table.add_row("[cyan]2.[/]", self.i18n.get('watch_add_rule'))
            table.add_row("[cyan]3.[/]", self.i18n.get('watch_edit_rule'))
            table.add_row("[cyan]4.[/]", self.i18n.get('watch_remove_rule'))
            table.add_row("[cyan]5.[/]", self.i18n.get('watch_view_logs'))
            table.add_row("[cyan]6.[/]", self.i18n.get('watch_clear_history'))
            console.print(table)

            # 显示规则列表
            rules = self.watch_manager.get_all_rules()
            if rules:
                console.print(f"\n[bold]{self.i18n.get('watch_rule_list')}:[/bold]")
                rule_table = Table(box=None)
                rule_table.add_column("ID", style="cyan")
                rule_table.add_column(self.i18n.get('watch_path'))
                rule_table.add_column(self.i18n.get('watch_patterns'))
                rule_table.add_column(self.i18n.get('watch_mode'))
                rule_table.add_column(self.i18n.get('label_status'))

                for rule in rules:
                    patterns = ", ".join(rule.file_patterns[:3])
                    if len(rule.file_patterns) > 3:
                        patterns += "..."
                    mode = describe_workflow_steps(rule.workflow_steps)
                    status_str = "[green]●[/]" if rule.enabled else "[dim]○[/]"
                    rule_table.add_row(rule.id, os.path.basename(rule.watch_path), patterns, mode, status_str)
                console.print(rule_table)
            else:
                console.print(f"\n[dim]{self.i18n.get('watch_no_rules')}[/dim]")

            console.print(f"\n[dim]0. {self.i18n.get('menu_back')}[/dim]")
            choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=["0", "1", "2", "3", "4", "5", "6"], show_choices=False)

            if choice == 0:
                break
            elif choice == 1:
                if self.watch_manager.running:
                    self.watch_manager.stop()
                else:
                    self.watch_manager.start()
            elif choice == 2:
                self.add_watch_rule()
            elif choice == 3:
                self.edit_watch_rule()
            elif choice == 4:
                self.remove_watch_rule()
            elif choice == 5:
                self.view_automation_logs(self.watch_manager.get_logs())
            elif choice == 6:
                self.watch_manager.clear_processed_history()
                console.print(f"[green]{self.i18n.get('watch_history_cleared')}[/green]")

    def add_watch_rule(self):
        """添加监控规则"""
        from ModuleFolders.Infrastructure.Automation.WatchManager import WatchRule

        console.print(Panel(f"[bold]{self.i18n.get('watch_add_rule')}[/bold]"))

        rule_id = Prompt.ask(self.i18n.get('prompt_rule_id'))
        if self.watch_manager.get_rule(rule_id):
            console.print(f"[red]{self.i18n.get('msg_id_exists')}[/red]")
            return

        watch_path = Prompt.ask(self.i18n.get('watch_path'))
        if not os.path.exists(watch_path):
            console.print(f"[red]{self.i18n.get('msg_path_not_exist')}[/red]")
            return

        patterns_str = Prompt.ask(f"{self.i18n.get('watch_patterns')} ({self.i18n.get('watch_patterns_hint')})", default="*.epub, *.txt, *.srt")
        file_patterns = [p.strip() for p in patterns_str.split(",")]

        # 选择任务类型
        task_types = ["translation", "polishing", "all_in_one"]
        console.print(f"\n{self.i18n.get('watch_task_type')}:")
        for i, t in enumerate(task_types):
            console.print(f"  [cyan]{i+1}.[/] {self.i18n.get(f'task_type_{t}')}")
        type_choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=["1", "2", "3"], default=1, show_choices=False)
        task_type = task_types[type_choice - 1]

        # 选择监控模式
        workflow_steps, auto_start = self._prompt_workflow_steps(default_task_type=task_type)

        # 选择配置
        profiles = self.host._get_profiles_list(self.host.profiles_dir)
        console.print(f"\n{self.i18n.get('watch_profile')}:")
        for i, p in enumerate(profiles):
            console.print(f"  [cyan]{i+1}.[/] {p}")
        profile_choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=[str(i+1) for i in range(len(profiles))], default=1, show_choices=False)
        profile = profiles[profile_choice - 1]

        # 选择规则配置
        rules_profiles = self.host._get_profiles_list(self.host.rules_profiles_dir)
        rules_profile = ""
        if rules_profiles:
            console.print(f"\n{self.i18n.get('label_rules_profile') or 'Rules Profile'}:")
            for i, p in enumerate(rules_profiles):
                console.print(f"  [cyan]{i+1}.[/] {p}")
            rules_choice = IntPrompt.ask(
                self.i18n.get('prompt_select'),
                choices=[str(i+1) for i in range(len(rules_profiles))],
                default=1,
                show_choices=False,
            )
            rules_profile = rules_profiles[rules_choice - 1]

        output_path = Prompt.ask(self.i18n.get('watch_output_path'), default="")
        done_path = Prompt.ask(self.i18n.get('watch_done_path'), default="")

        # 其他选项
        debounce = IntPrompt.ask(f"{self.i18n.get('watch_debounce')} ({self.i18n.get('watch_debounce_hint')})", default=5)
        recursive = Confirm.ask(self.i18n.get('watch_recursive'), default=False)
        trigger_mode = "folder" if Confirm.ask("检测到更新后处理整个监控文件夹?", default=False) else "file"

        rule = WatchRule(
            rule_id=rule_id,
            watch_path=watch_path,
            output_path=output_path,
            done_path=done_path,
            file_patterns=file_patterns,
            profile=profile,
            rules_profile=rules_profile,
            task_type=task_type,
            auto_start=auto_start,
            debounce_seconds=debounce,
            recursive=recursive,
            workflow_steps=workflow_steps,
            trigger_mode=trigger_mode,
        )

        if self.watch_manager.add_rule(rule):
            console.print(f"[green]{self.i18n.get('watch_rule_added')}[/green]")
            self.watch_manager.save_to_config(self.config)
            self.host.save_config()

    def edit_watch_rule(self):
        """编辑监控规则"""
        rules = self.watch_manager.get_all_rules()
        if not rules:
            console.print(f"[dim]{self.i18n.get('watch_no_rules')}[/dim]")
            return

        console.print(Panel(f"[bold]{self.i18n.get('watch_edit_rule')}[/bold]"))
        for i, rule in enumerate(rules):
            console.print(f"  [cyan]{i+1}.[/] {rule.id} - {rule.watch_path}")

        choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=[str(i+1) for i in range(len(rules))] + ["0"], default=0, show_choices=False)
        if choice == 0:
            return

        rule = rules[choice - 1]

        # 编辑选项
        console.print(f"\n[bold]{rule.id}[/bold]")
        console.print(f"1. {self.i18n.get('label_enabled')}: {'ON' if rule.enabled else 'OFF'}")
        console.print(f"2. {self.i18n.get('watch_mode')}: {describe_workflow_steps(rule.workflow_steps)}")
        console.print(f"3. {self.i18n.get('watch_patterns')}: {', '.join(rule.file_patterns)}")
        console.print(f"4. {self.i18n.get('watch_debounce')}: {rule.debounce_seconds}s")
        console.print(f"5. {self.i18n.get('watch_output_path')}: {rule.output_path or '-'}")

        edit_choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=["0", "1", "2", "3", "4", "5"], default=0, show_choices=False)

        if edit_choice == 1:
            self.watch_manager.update_rule(rule.id, enabled=not rule.enabled)
        elif edit_choice == 2:
            workflow_steps, auto_start = self._prompt_workflow_steps(
                default_task_type=rule.task_type,
                current_steps=rule.workflow_steps,
                current_auto_start=rule.auto_start,
            )
            self.watch_manager.update_rule(rule.id, workflow_steps=workflow_steps, auto_start=auto_start)
        elif edit_choice == 3:
            patterns_str = Prompt.ask(self.i18n.get('watch_patterns'), default=", ".join(rule.file_patterns))
            file_patterns = [p.strip() for p in patterns_str.split(",")]
            self.watch_manager.update_rule(rule.id, file_patterns=file_patterns)
        elif edit_choice == 4:
            debounce = IntPrompt.ask(self.i18n.get('watch_debounce'), default=rule.debounce_seconds)
            self.watch_manager.update_rule(rule.id, debounce_seconds=debounce)
        elif edit_choice == 5:
            output_path = Prompt.ask(self.i18n.get('watch_output_path'), default=rule.output_path or "")
            self.watch_manager.update_rule(rule.id, output_path=output_path)

        if edit_choice > 0:
            console.print(f"[green]{self.i18n.get('watch_rule_updated')}[/green]")
            self.watch_manager.save_to_config(self.config)
            self.host.save_config()

    def remove_watch_rule(self):
        """删除监控规则"""
        rules = self.watch_manager.get_all_rules()
        if not rules:
            console.print(f"[dim]{self.i18n.get('watch_no_rules')}[/dim]")
            return

        console.print(Panel(f"[bold]{self.i18n.get('watch_remove_rule')}[/bold]"))
        for i, rule in enumerate(rules):
            console.print(f"  [cyan]{i+1}.[/] {rule.id} - {rule.watch_path}")

        choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=[str(i+1) for i in range(len(rules))] + ["0"], default=0, show_choices=False)
        if choice == 0:
            return

        rule = rules[choice - 1]
        if Confirm.ask(self.i18n.get('watch_confirm_remove')):
            self.watch_manager.remove_rule(rule.id)
            console.print(f"[green]{self.i18n.get('watch_rule_removed')}[/green]")
            self.watch_manager.save_to_config(self.config)
            self.host.save_config()

    def automation_status_view(self):
        """自动化状态总览"""
        self.host.display_banner()
        console.print(Panel(f"[bold]{self.i18n.get('automation_status_title')}[/bold]"))

        sched_status = self.scheduler_manager.get_status()
        watch_status = self.watch_manager.get_status()

        # 调度器状态
        console.print(f"\n[bold]{self.i18n.get('automation_scheduler_status')}[/bold]")
        sched_table = Table(show_header=False, box=None)
        sched_table.add_row(self.i18n.get('label_status'), f"[{'green' if sched_status['running'] else 'red'}]{self.i18n.get('automation_running') if sched_status['running'] else self.i18n.get('automation_stopped')}[/]")
        sched_table.add_row(self.i18n.get('automation_task_count'), f"{sched_status['enabled_count']}/{sched_status['task_count']}")
        if sched_status.get('next_task'):
            next_task = sched_status['next_task']
            sched_table.add_row(self.i18n.get('automation_next_task'), f"{next_task['name']} @ {next_task['next_run']}")
        console.print(sched_table)

        # 监控状态
        console.print(f"\n[bold]{self.i18n.get('automation_watch_status')}[/bold]")
        watch_table = Table(show_header=False, box=None)
        watch_table.add_row(self.i18n.get('label_status'), f"[{'green' if watch_status['running'] else 'red'}]{self.i18n.get('automation_running') if watch_status['running'] else self.i18n.get('automation_stopped')}[/]")
        watch_table.add_row(self.i18n.get('automation_task_count'), f"{watch_status['enabled_count']}/{watch_status['rule_count']}")
        watch_table.add_row(self.i18n.get('watch_pending_files'), str(watch_status['pending_files']))
        watch_table.add_row(self.i18n.get('automation_total_processed'), str(watch_status['total_processed']))
        console.print(watch_table)

        Prompt.ask(f"\n{self.i18n.get('msg_press_enter')}")

    def view_automation_logs(self, logs: list):
        """查看自动化日志"""
        self.host.display_banner()

        if not logs:
            console.print("[dim]No logs available.[/dim]")
        else:
            log_table = Table(box=None)
            log_table.add_column("Time", style="dim")
            log_table.add_column("Level")
            log_table.add_column("Message")

            for log in logs[-20:]:
                level_style = {"info": "green", "warning": "yellow", "error": "red"}.get(log['level'], "white")
                log_table.add_row(log['time'], f"[{level_style}]{log['level'].upper()}[/]", log['message'])

            console.print(log_table)

        Prompt.ask(f"\n{self.i18n.get('msg_press_enter')}")

    def _prompt_workflow_steps(self, default_task_type="translation", current_steps=None, current_auto_start=True):
        """Prompt a queue-managed workflow preset."""
        console.print(f"\n{self.i18n.get('watch_mode')}:")
        table = Table(show_header=False, box=None)
        table.add_row("[cyan]1.[/]", "加入队列后自动执行: AI术语表 -> 翻译")
        table.add_row("[cyan]2.[/]", "加入队列后自动执行: AI术语表 -> 翻译 -> 润色")
        table.add_row("[cyan]3.[/]", "加入队列后自动执行: 翻译")
        table.add_row("[cyan]4.[/]", "仅加入队列，不自动启动")
        table.add_row("[cyan]5.[/]", "自定义步骤")
        console.print(table)

        choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=["1", "2", "3", "4", "5"], default=1, show_choices=False)
        auto_start = choice != 4
        task_step = task_type_to_step_type(default_task_type)

        if choice == 1:
            steps = [
                self._prompt_glossary_step_defaults(),
                {"type": task_step if task_step != "polish" else "translate"},
            ]
        elif choice == 2:
            steps = [
                self._prompt_glossary_step_defaults(),
                {"type": "all_in_one"},
            ]
        elif choice == 3:
            steps = [{"type": task_step}]
        elif choice == 4:
            steps = [{"type": task_step}]
        else:
            steps, auto_start = self._prompt_custom_workflow_steps(current_steps, current_auto_start)

        return normalize_workflow_steps(steps, default_task_type, auto_start), auto_start

    def _prompt_glossary_step_defaults(self):
        return {
            "type": "extract_glossary",
            "analysis_mode": "full",
            "analysis_percent": IntPrompt.ask("术语表分析比例 (1-100)", default=100),
            "min_frequency": IntPrompt.ask("术语表最低词频", default=2),
            "translate_during_analysis": True,
            "new": True,
            "replace": True,
            "save_mode": "import",
        }

    def _prompt_custom_workflow_steps(self, current_steps=None, current_auto_start=True):
        steps = list(current_steps or [])
        auto_start = current_auto_start
        while True:
            console.print("\n[bold]Workflow[/bold]")
            if steps:
                for idx, step in enumerate(steps, 1):
                    console.print(f"  [cyan]{idx}.[/] {step.get('type')}")
            else:
                console.print("  [dim]No steps[/dim]")
            console.print(f"  [cyan]A.[/] Add step")
            console.print(f"  [cyan]R.[/] Remove last step")
            console.print(f"  [cyan]S.[/] Auto-start queue: {'ON' if auto_start else 'OFF'}")
            console.print(f"  [dim]0. Done[/dim]")
            choice = Prompt.ask(self.i18n.get('prompt_select'), choices=["0", "A", "a", "R", "r", "S", "s"], default="0", show_choices=False)
            if choice == "0":
                break
            if choice.upper() == "S":
                auto_start = not auto_start
            elif choice.upper() == "R":
                if steps:
                    steps.pop()
            elif choice.upper() == "A":
                steps.append(self._prompt_workflow_step())
        return steps, auto_start

    def _prompt_workflow_step(self):
        table = Table(show_header=False, box=None)
        table.add_row("[cyan]1.[/]", "AI术语表提取")
        table.add_row("[cyan]2.[/]", "翻译")
        table.add_row("[cyan]3.[/]", "润色")
        table.add_row("[cyan]4.[/]", "翻译+润色")
        console.print(table)
        choice = IntPrompt.ask(self.i18n.get('prompt_select'), choices=["1", "2", "3", "4"], default=1, show_choices=False)
        if choice == 1:
            return self._prompt_glossary_step_defaults()
        if choice == 2:
            return {"type": "translate"}
        if choice == 3:
            return {"type": "polish", "resume": True}
        return {"type": "all_in_one"}
