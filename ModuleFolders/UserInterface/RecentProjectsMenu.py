import os
import time

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from ModuleFolders.Infrastructure.TaskConfig.ConfigProfileService import save_root_config
from ModuleFolders.UserInterface.ConfigExperience import calculate_output_path
from ModuleFolders.UserInterface.RulePreview import i18n_text


console = Console()


def normalize_recent_item(item):
    if isinstance(item, dict):
        return {
            "path": str(item.get("path", "")).strip(),
            "profile": str(item.get("profile", "default") or "default"),
            "rules_profile": str(item.get("rules_profile", "default") or "default"),
            "pinned": bool(item.get("pinned", False)),
        }
    return {
        "path": str(item or "").strip(),
        "profile": "default",
        "rules_profile": "default",
        "pinned": False,
    }


class RecentProjectsMenu:
    def __init__(self, host):
        self.host = host

    @property
    def i18n(self):
        return self.host.i18n

    @property
    def recent_projects(self):
        return [normalize_recent_item(item) for item in self.host.root_config.get("recent_projects", [])]

    def show(self):
        while True:
            self.host.display_banner()
            console.print(Panel(f"[bold]{i18n_text(self.i18n, 'menu_recent_project_manager', 'Recent Project Manager')}[/bold]"))
            projects = self.recent_projects
            if not projects:
                console.print(f"[dim]{i18n_text(self.i18n, 'msg_recent_empty', 'No recent projects.')}[/dim]")
                Prompt.ask(f"\n{i18n_text(self.i18n, 'msg_press_enter', 'Press Enter to continue')}")
                return

            self._render_projects(projects)
            console.print(f"\n[cyan]1.[/] {i18n_text(self.i18n, 'option_recent_open', 'Open project')}")
            console.print(f"[cyan]2.[/] {i18n_text(self.i18n, 'option_recent_bind_profiles', 'Change bound profiles')}")
            console.print(f"[cyan]3.[/] {i18n_text(self.i18n, 'option_recent_toggle_pin', 'Pin/unpin project')}")
            console.print(f"[cyan]4.[/] {i18n_text(self.i18n, 'option_recent_remove', 'Remove from recent projects')}")
            console.print(f"[cyan]5.[/] {i18n_text(self.i18n, 'option_recent_clean_missing', 'Clean missing projects')}")
            console.print(f"[dim]0. {i18n_text(self.i18n, 'menu_back', 'Back')}[/dim]")

            choice = IntPrompt.ask(
                f"\n{i18n_text(self.i18n, 'prompt_select', 'Select')}",
                choices=["0", "1", "2", "3", "4", "5"],
                show_choices=False,
            )
            if choice == 0:
                return
            if choice == 1:
                selected = self._ask_project_index(projects)
                if selected is not None:
                    item = projects[selected]
                    self._save_projects(projects)
                    self._activate_project(item)
                    return
            elif choice == 2:
                selected = self._ask_project_index(projects)
                if selected is not None:
                    self._bind_profiles(projects[selected])
                    self._save_projects(projects)
            elif choice == 3:
                selected = self._ask_project_index(projects)
                if selected is not None:
                    projects[selected]["pinned"] = not projects[selected].get("pinned", False)
                    self._save_projects(projects)
            elif choice == 4:
                selected = self._ask_project_index(projects)
                if selected is not None and Confirm.ask(i18n_text(self.i18n, "confirm_recent_remove", "Remove this project from recent projects?"), default=False):
                    projects.pop(selected)
                    self._save_projects(projects)
            elif choice == 5:
                cleaned = [item for item in projects if item.get("pinned") or os.path.exists(item.get("path", ""))]
                removed = len(projects) - len(cleaned)
                self._save_projects(cleaned)
                console.print(i18n_text(self.i18n, "msg_recent_cleaned", "Removed {} missing projects.").format(removed))
                time.sleep(1)

    def _render_projects(self, projects):
        table = Table(show_header=True)
        table.add_column("ID", style="dim")
        table.add_column(i18n_text(self.i18n, "label_status", "Status"))
        table.add_column(i18n_text(self.i18n, "label_input", "Input"), overflow="fold")
        table.add_column(i18n_text(self.i18n, "label_profile", "Profile"))
        table.add_column(i18n_text(self.i18n, "label_rules_profile", "Rules"))
        table.add_column(i18n_text(self.i18n, "label_cache_status", "Cache"))

        for index, item in enumerate(projects, 1):
            path = item.get("path", "")
            exists = os.path.exists(path)
            status = "[green]OK[/green]" if exists else f"[red]{i18n_text(self.i18n, 'label_missing', 'Missing')}[/red]"
            if item.get("pinned"):
                status += " [yellow]*[/yellow]"
            output_path = calculate_output_path(self.host.config, path)
            cache_path = os.path.join(output_path, "cache", "AinieeCacheData.json") if output_path else ""
            cache_status = (
                i18n_text(self.i18n, "label_resume_available", "Resume available")
                if cache_path and os.path.exists(cache_path)
                else i18n_text(self.i18n, "label_new_task", "New task")
            )
            table.add_row(
                str(index),
                status,
                path,
                item.get("profile", "default"),
                item.get("rules_profile", "default"),
                cache_status,
            )
        console.print(table)

    def _ask_project_index(self, projects):
        if not projects:
            return None
        selected = IntPrompt.ask(
            i18n_text(self.i18n, "prompt_recent_project_id", "Project ID"),
            choices=[str(i) for i in range(1, len(projects) + 1)],
            show_choices=False,
        )
        return selected - 1

    def _bind_profiles(self, item):
        profiles = self.host._get_profiles_list(self.host.profiles_dir)
        rules_profiles = ["None"] + self.host._get_profiles_list(self.host.rules_profiles_dir)

        console.print(f"[cyan]{i18n_text(self.i18n, 'label_profiles', 'Profiles')}:[/cyan] {', '.join(profiles)}")
        profile = Prompt.ask(
            i18n_text(self.i18n, "prompt_profile_queue", "Profile"),
            choices=profiles,
            default=item.get("profile", self.host.active_profile_name),
        )
        console.print(f"[cyan]{i18n_text(self.i18n, 'label_rules_profiles', 'Rules Profiles')}:[/cyan] {', '.join(rules_profiles)}")
        rules_profile = Prompt.ask(
            i18n_text(self.i18n, "prompt_rules_profile_queue", "Rules Profile"),
            choices=rules_profiles,
            default=item.get("rules_profile", self.host.active_rules_profile_name),
        )
        item["profile"] = profile
        item["rules_profile"] = rules_profile

    def _activate_project(self, item):
        path = item.get("path", "")
        if not os.path.exists(path):
            console.print(f"[red]{i18n_text(self.i18n, 'msg_recent_missing', 'Project path does not exist.')}[/red]")
            time.sleep(1)
            return

        profile = item.get("profile")
        rules_profile = item.get("rules_profile")
        if profile:
            self.host.active_profile_name = profile
            self.host.root_config["active_profile"] = profile
        if rules_profile:
            self.host.active_rules_profile_name = rules_profile
            self.host.root_config["active_rules_profile"] = rules_profile
        save_root_config(self.host.root_config)
        self.host.load_config()
        task_mode = self._ask_task_mode()
        if task_mode is not None:
            self.host.run_task(task_mode, target_path=path)

    def _ask_task_mode(self):
        console.print(f"\n[cyan]1.[/] {i18n_text(self.i18n, 'task_type_translation', 'Translation')}")
        console.print(f"[cyan]2.[/] {i18n_text(self.i18n, 'task_type_polishing', 'Polishing')}")
        console.print(f"[cyan]3.[/] {i18n_text(self.i18n, 'task_type_all_in_one', 'All in One')}")
        console.print(f"[dim]0. {i18n_text(self.i18n, 'menu_cancel', 'Cancel')}[/dim]")
        choice = IntPrompt.ask(
            f"\n{i18n_text(self.i18n, 'prompt_select', 'Select')}",
            choices=["0", "1", "2", "3"],
            default=1,
            show_choices=False,
        )
        return {
            1: TaskType.TRANSLATION,
            2: TaskType.POLISH,
            3: TaskType.TRANSLATE_AND_POLISH,
        }.get(choice)

    def _save_projects(self, projects):
        pinned = [item for item in projects if item.get("pinned")]
        normal = [item for item in projects if not item.get("pinned")]
        self.host.root_config["recent_projects"] = pinned + normal[: max(0, 10 - len(pinned))]
        self.host.config["recent_projects"] = self.host.root_config["recent_projects"]
        save_root_config(self.host.root_config)
