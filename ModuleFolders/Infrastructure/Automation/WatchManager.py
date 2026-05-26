"""
文件夹监控管理器
监控指定目录，检测新文件并自动加入翻译队列
"""
import os
import shutil
import threading
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any, Set
from ModuleFolders.Base.Base import Base
from ModuleFolders.Infrastructure.Automation.WorkflowRunner import (
    describe_workflow_steps,
    normalize_workflow_steps,
)


class WatchRule:
    """监控规则"""

    def __init__(self, rule_id: str, watch_path: str, output_path: str = "",
                 done_path: str = "", file_patterns: List[str] = None,
                 profile: str = "default", task_type: str = "translation",
                 auto_start: bool = True, debounce_seconds: int = 5,
                 recursive: bool = False, enabled: bool = True,
                 move_to_done: bool = True, workflow_steps: List[dict] = None,
                 trigger_mode: str = "file", rules_profile: str = "",
                 settle_existing: bool = False, **kwargs):
        self.id = rule_id
        self.watch_path = os.path.abspath(watch_path)
        self.output_path = output_path
        self.done_path = done_path
        self.file_patterns = self._normalize_patterns(file_patterns)
        self.profile = profile
        self.rules_profile = rules_profile
        self.task_type = task_type
        self.auto_start = auto_start
        self.debounce_seconds = debounce_seconds
        self.recursive = recursive
        self.enabled = enabled
        self.move_to_done = move_to_done
        self.workflow_steps = normalize_workflow_steps(workflow_steps, task_type, auto_start)
        self.trigger_mode = trigger_mode if trigger_mode in {"file", "folder"} else "file"
        self.settle_existing = settle_existing
        self.extra = kwargs

        # 运行状态
        self.files_processed = 0
        self.last_activity: Optional[datetime] = None

    @staticmethod
    def _normalize_patterns(file_patterns: List[str] = None) -> List[str]:
        patterns = []
        for pattern in file_patterns or ["*.txt", "*.epub", "*.srt"]:
            pattern = str(pattern or "").strip()
            if not pattern:
                continue
            if pattern.startswith("."):
                pattern = f"*{pattern}"
            elif "*" not in pattern and "?" not in pattern:
                pattern = f"*.{pattern.lstrip('.')}"
            patterns.append(pattern)
        return patterns or ["*.txt", "*.epub", "*.srt"]

    def matches_pattern(self, filename: str) -> bool:
        """检查文件是否匹配模式"""
        from fnmatch import fnmatch
        return any(fnmatch(filename.lower(), pattern.lower())
                   for pattern in self.file_patterns)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "watch_path": self.watch_path,
            "output_path": self.output_path,
            "done_path": self.done_path,
            "file_patterns": self.file_patterns,
            "profile": self.profile,
            "rules_profile": self.rules_profile,
            "task_type": self.task_type,
            "auto_start": self.auto_start,
            "debounce_seconds": self.debounce_seconds,
            "recursive": self.recursive,
            "enabled": self.enabled,
            "move_to_done": self.move_to_done,
            "workflow_steps": self.workflow_steps,
            "trigger_mode": self.trigger_mode,
            "settle_existing": self.settle_existing,
            **self.extra
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WatchRule":
        """从字典创建"""
        return cls(
            rule_id=data.get("id", ""),
            watch_path=data.get("watch_path", ""),
            output_path=data.get("output_path", ""),
            done_path=data.get("done_path", ""),
            file_patterns=data.get("file_patterns", ["*.txt", "*.epub", "*.srt"]),
            profile=data.get("profile", "default"),
            rules_profile=data.get("rules_profile", ""),
            task_type=data.get("task_type", "translation"),
            auto_start=data.get("auto_start", True),
            debounce_seconds=data.get("debounce_seconds", 5),
            recursive=data.get("recursive", False),
            enabled=data.get("enabled", True),
            move_to_done=data.get("move_to_done", True),
            workflow_steps=data.get("workflow_steps"),
            trigger_mode=data.get("trigger_mode", "file"),
            settle_existing=data.get("settle_existing", False),
        )


class FileState:
    """文件状态追踪"""

    def __init__(self, path: str):
        self.path = path
        self.size = 0
        self.mtime = 0
        self.hash = ""
        self.first_seen = datetime.now()
        self.stable_since: Optional[datetime] = None
        self.status = "pending"  # pending, stable, processing, done, error

    def update(self) -> bool:
        """更新文件状态，返回是否有变化"""
        try:
            stat = os.stat(self.path)
            new_size = stat.st_size
            new_mtime = stat.st_mtime

            if new_size != self.size or new_mtime != self.mtime:
                self.size = new_size
                self.mtime = new_mtime
                self.stable_since = None
                return True
            else:
                if self.stable_since is None:
                    self.stable_since = datetime.now()
                return False
        except OSError:
            return False

    def is_stable(self, debounce_seconds: int) -> bool:
        """检查文件是否稳定（不再被写入）"""
        if self.stable_since is None:
            return False
        elapsed = (datetime.now() - self.stable_since).total_seconds()
        return elapsed >= debounce_seconds


class WatchManager(Base):
    """文件夹监控管理器"""

    def __init__(self, task_callback: Callable[[dict], Any] = None,
                 queue_callback: Callable[[dict], Any] = None):
        super().__init__()
        self.task_callback = task_callback  # 直接执行任务
        self.queue_callback = queue_callback  # 加入队列
        self.rules: Dict[str, WatchRule] = {}
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # 文件状态追踪
        self.file_states: Dict[str, FileState] = {}
        self.processed_files: Set[str] = set()
        self.file_observations: Dict[str, Dict[str, Any]] = {}

        # 配置
        self.scan_interval = 10  # 扫描间隔（秒）
        self.max_concurrent = 2  # 最大并发任务数
        self.current_tasks = 0
        self._active_targets: Set[str] = set()

        # 日志
        self.logs: List[dict] = []
        self.max_logs = 100

        # 持久化已处理文件记录
        self.processed_file_path = ""

    def set_callbacks(self, task_callback: Callable = None,
                      queue_callback: Callable = None):
        """设置回调函数"""
        if task_callback:
            self.task_callback = task_callback
        if queue_callback:
            self.queue_callback = queue_callback

    def add_rule(self, rule: WatchRule) -> bool:
        """添加监控规则"""
        with self._lock:
            if rule.id in self.rules:
                return False

            # 确保监控目录存在
            if not os.path.exists(rule.watch_path):
                try:
                    os.makedirs(rule.watch_path)
                except OSError as e:
                    self._log("error", f"Cannot create watch directory: {e}")
                    return False

            # 确保完成目录存在
            if rule.done_path and not os.path.exists(rule.done_path):
                try:
                    os.makedirs(rule.done_path)
                except OSError:
                    pass

            self.rules[rule.id] = rule
            self._log("info", f"Watch rule added: {rule.watch_path}")
            return True

    def remove_rule(self, rule_id: str) -> bool:
        """移除监控规则"""
        with self._lock:
            if rule_id in self.rules:
                rule = self.rules.pop(rule_id)
                self.file_observations = {
                    path: item
                    for path, item in self.file_observations.items()
                    if item.get("rule_id") != rule_id
                }
                self._log("info", f"Watch rule removed: {rule.watch_path}")
                return True
            return False

    def update_rule(self, rule_id: str, **kwargs) -> bool:
        """更新监控规则"""
        with self._lock:
            if rule_id not in self.rules:
                return False

            rule = self.rules[rule_id]
            for key, value in kwargs.items():
                if hasattr(rule, key):
                    if key == "file_patterns":
                        value = WatchRule._normalize_patterns(value)
                    if key == "workflow_steps":
                        value = normalize_workflow_steps(value, rule.task_type, rule.auto_start)
                    setattr(rule, key, value)
            return True

    def get_rule(self, rule_id: str) -> Optional[WatchRule]:
        """获取规则"""
        return self.rules.get(rule_id)

    def get_all_rules(self) -> List[WatchRule]:
        """获取所有规则"""
        return list(self.rules.values())

    @staticmethod
    def _observation_key(file_path: str, rule: WatchRule) -> str:
        return f"{rule.id}:{os.path.abspath(file_path)}"

    def _record_file_observation(
        self,
        file_path: str,
        rule: WatchRule,
        matched: bool,
        status: str = None,
    ) -> dict:
        path = os.path.abspath(file_path)
        now = datetime.now()
        observation_key = self._observation_key(path, rule)
        observation = self.file_observations.get(observation_key)
        if observation is None:
            observation = {
                "path": path,
                "detected_at": now,
                "queued_at": None,
                "processed_at": None,
            }
            self.file_observations[observation_key] = observation

        try:
            relative_path = os.path.relpath(path, rule.watch_path)
        except ValueError:
            relative_path = os.path.basename(path)

        observation.update({
            "rule_id": rule.id,
            "name": os.path.basename(path),
            "relative_path": relative_path,
            "matched": matched,
            "patterns": list(rule.file_patterns),
            "workflow": describe_workflow_steps(rule.workflow_steps),
            "last_seen": now,
        })
        if status:
            observation["status"] = status
            if status == "queued":
                observation["queued_at"] = now
            elif status == "done":
                observation["processed_at"] = now

        try:
            stat = os.stat(path)
            observation["size"] = stat.st_size
            observation["mtime"] = stat.st_mtime
        except OSError:
            observation["missing"] = True

        return observation

    def _scan_rule_file_entries(
        self,
        rule: WatchRule,
        include_unmatched: bool,
        scan_limit: int,
    ) -> tuple:
        entries = []
        truncated = False

        def add_entry(path: str, name: str) -> bool:
            nonlocal truncated
            matched = rule.matches_pattern(name)
            if not matched and not include_unmatched:
                return True
            try:
                stat = os.stat(path)
            except OSError:
                return True
            entries.append({
                "path": os.path.abspath(path),
                "name": name,
                "matched": matched,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
            if len(entries) >= scan_limit:
                truncated = True
                return False
            return True

        try:
            if rule.recursive:
                excluded_dirs = {
                    os.path.abspath(path)
                    for path in (rule.output_path, rule.done_path)
                    if path
                }
                for root, dirs, files in os.walk(rule.watch_path):
                    dirs[:] = [
                        d for d in dirs
                        if os.path.abspath(os.path.join(root, d)) not in excluded_dirs
                    ]
                    for filename in files:
                        if not add_entry(os.path.join(root, filename), filename):
                            return entries, truncated
            else:
                for entry in os.scandir(rule.watch_path):
                    if entry.is_file() and not add_entry(entry.path, entry.name):
                        return entries, truncated
        except OSError:
            pass

        return entries, truncated

    def _get_queue_task_lookup(self) -> dict:
        lookup = {"by_rule_path": {}, "by_path": {}}
        try:
            from ModuleFolders.Service.TaskQueue.QueueManager import QueueManager

            queue_manager = QueueManager()
            for task in queue_manager.tasks:
                if getattr(task, "source", None) != "watch":
                    continue
                input_path = os.path.abspath(getattr(task, "input_path", "") or "")
                rule_id = getattr(task, "rule_id", None)
                info = {
                    "status": getattr(task, "status", "waiting"),
                    "workflow": describe_workflow_steps(getattr(task, "workflow_steps", []) or []),
                    "locked": getattr(task, "locked", False),
                    "is_processing": getattr(task, "is_processing", False),
                }
                lookup["by_path"][input_path] = info
                if rule_id:
                    lookup["by_rule_path"][(rule_id, input_path)] = info
        except Exception:
            pass
        return lookup

    def _find_queue_task_for_file(self, file_path: str, rule: WatchRule, queue_lookup: dict) -> Optional[dict]:
        target_path = rule.watch_path if rule.trigger_mode == "folder" else file_path
        target_path = os.path.abspath(target_path)
        return (
            queue_lookup.get("by_rule_path", {}).get((rule.id, target_path))
            or queue_lookup.get("by_path", {}).get(target_path)
        )

    @staticmethod
    def _format_snapshot_time(value) -> str:
        if isinstance(value, datetime):
            return value.strftime("%m-%d %H:%M:%S")
        if isinstance(value, (int, float)) and value:
            return datetime.fromtimestamp(value).strftime("%m-%d %H:%M:%S")
        return "-"

    @staticmethod
    def _status_enters_workflow(status: str) -> bool:
        return status in {
            "waiting",
            "queued",
            "workflow",
            "translating",
            "translated",
            "polishing",
            "processing",
            "completed",
            "done",
            "processed",
        }

    def _build_file_status_row(self, rule: WatchRule, entry: dict, queue_lookup: dict) -> dict:
        path = entry["path"]
        matched = entry["matched"]
        observation = self._record_file_observation(
            path,
            rule,
            matched,
            "ignored" if not matched else None,
        )
        state = self.file_states.get(path)
        queue_task = self._find_queue_task_for_file(path, rule, queue_lookup) if matched else None
        processed = self._get_file_key(path) in self.processed_files if matched else False
        observation_status = observation.get("status")

        if not matched:
            status = "ignored"
        elif queue_task:
            status = queue_task.get("status") or "queued"
        elif state:
            status = state.status
        elif processed:
            status = observation_status if observation_status in {"queued", "done", "primed", "processed"} else "processed"
        elif observation_status in {"queued", "done", "error", "processing", "waiting_stable", "waiting_capacity", "waiting_target"}:
            status = observation_status
        elif not rule.enabled:
            status = "rule_disabled"
        elif not self.running:
            status = "watch_stopped"
        else:
            status = "ready"

        detected_at = state.first_seen if state else observation.get("detected_at")
        workflow = queue_task.get("workflow") if queue_task and queue_task.get("workflow") else observation.get("workflow", "")
        entered_workflow = bool(queue_task) or self._status_enters_workflow(status)

        return {
            "rule_id": rule.id,
            "path": path,
            "file": observation.get("relative_path") or entry["name"],
            "matched": matched,
            "patterns": ", ".join(rule.file_patterns),
            "detected_at": self._format_snapshot_time(detected_at),
            "mtime": self._format_snapshot_time(entry.get("mtime")),
            "size": entry.get("size", 0),
            "status": status,
            "entered_workflow": entered_workflow,
            "workflow": workflow,
        }

    def get_file_status_snapshot(
        self,
        limit_per_rule: int = 30,
        include_unmatched: bool = True,
    ) -> List[dict]:
        """获取监控目录当前文件状态快照。"""
        queue_lookup = self._get_queue_task_lookup()
        limit_per_rule = max(1, limit_per_rule)
        scan_limit = max(limit_per_rule * 5, 100)

        with self._lock:
            snapshots = []
            for rule in self.rules.values():
                entries, truncated = self._scan_rule_file_entries(rule, include_unmatched, scan_limit)
                rows = [self._build_file_status_row(rule, entry, queue_lookup) for entry in entries]
                rows.sort(key=lambda item: (item["matched"], item.get("mtime") or ""), reverse=True)

                visible_rows = rows[:limit_per_rule]
                snapshots.append({
                    "rule_id": rule.id,
                    "watch_path": rule.watch_path,
                    "patterns": list(rule.file_patterns),
                    "enabled": rule.enabled,
                    "running": self.running,
                    "files": visible_rows,
                    "omitted": max(0, len(rows) - len(visible_rows)),
                    "truncated": truncated or len(rows) > len(visible_rows),
                })

            return snapshots

    def start(self):
        """启动监控"""
        if self.running:
            return

        self.running = True
        self._stop_event.clear()
        self._load_processed_files()
        self._prime_existing_files()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        self._log("info", "Watch manager started")

    def stop(self):
        """停止监控"""
        if not self.running:
            return

        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._save_processed_files()
        self._log("info", "Watch manager stopped")

    def _watch_loop(self):
        """监控主循环"""
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    for rule in self.rules.values():
                        if rule.enabled:
                            self._scan_directory(rule)

                # 等待下一次扫描
                self._stop_event.wait(self.scan_interval)

            except Exception as e:
                self._log("error", f"Watch loop error: {e}")
                time.sleep(30)

    def _scan_directory(self, rule: WatchRule):
        """扫描目录"""
        try:
            if rule.recursive:
                files = self._scan_recursive(rule.watch_path, rule)
            else:
                files = self._scan_flat(rule.watch_path, rule)

            for file_path in files:
                self._process_file(file_path, rule)

        except Exception as e:
            self._log("error", f"Scan error for {rule.watch_path}: {e}")

    def _scan_flat(self, directory: str, rule: WatchRule) -> List[str]:
        """扫描单层目录"""
        result = []
        try:
            for entry in os.scandir(directory):
                if entry.is_file() and rule.matches_pattern(entry.name):
                    result.append(entry.path)
        except OSError:
            pass
        return result

    def _scan_recursive(self, directory: str, rule: WatchRule) -> List[str]:
        """递归扫描目录"""
        result = []
        try:
            excluded_dirs = {
                os.path.abspath(path)
                for path in (rule.output_path, rule.done_path)
                if path
            }
            for root, dirs, files in os.walk(directory):
                # 排除输出目录和完成目录
                dirs[:] = [
                    d for d in dirs
                    if os.path.abspath(os.path.join(root, d)) not in excluded_dirs
                ]

                for filename in files:
                    if rule.matches_pattern(filename):
                        result.append(os.path.join(root, filename))
        except OSError:
            pass
        return result

    def _prime_existing_files(self):
        """Record existing files so watch mode reacts to future changes by default."""
        for rule in self.rules.values():
            if rule.settle_existing:
                continue
            try:
                files = self._scan_recursive(rule.watch_path, rule) if rule.recursive else self._scan_flat(rule.watch_path, rule)
                for file_path in files:
                    self.processed_files.add(self._get_file_key(file_path))
                    self._record_file_observation(file_path, rule, True, "primed")
            except Exception as e:
                self._log("warning", f"Failed to prime existing files for {rule.watch_path}: {e}")

    def _process_file(self, file_path: str, rule: WatchRule):
        """处理检测到的文件"""
        # 检查是否已处理
        file_key = self._get_file_key(file_path)
        if file_key in self.processed_files:
            observation = self.file_observations.get(self._observation_key(file_path, rule))
            if observation and observation.get("status") == "primed":
                return
            self._record_file_observation(file_path, rule, True, "processed")
            return

        self._record_file_observation(file_path, rule, True, "pending")

        # 获取或创建文件状态
        if file_path not in self.file_states:
            self.file_states[file_path] = FileState(file_path)

        state = self.file_states[file_path]

        # 更新状态
        state.update()

        # 检查文件是否稳定
        if not state.is_stable(rule.debounce_seconds):
            state.status = "waiting_stable"
            self._record_file_observation(file_path, rule, True, "waiting_stable")
            return

        # 检查并发限制
        if self.current_tasks >= self.max_concurrent:
            state.status = "waiting_capacity"
            self._record_file_observation(file_path, rule, True, "waiting_capacity")
            return

        # 标记为处理中
        state.status = "processing"
        self._record_file_observation(file_path, rule, True, "processing")
        self.current_tasks += 1
        target_path = rule.watch_path if rule.trigger_mode == "folder" else file_path
        target_key = self._get_file_key(target_path)
        if target_key in self._active_targets:
            self.current_tasks -= 1
            state.status = "waiting_target"
            self._record_file_observation(file_path, rule, True, "waiting_target")
            return
        self._active_targets.add(target_key)

        # 创建任务
        task_config = {
            "input_path": target_path,
            "output_path": rule.output_path or self._generate_output_path(target_path),
            "profile": rule.profile,
            "rules_profile": rule.rules_profile,
            "task_type": rule.task_type,
            "source": "watch",
            "rule_id": rule.id,
            "auto_start": rule.auto_start,
            "workflow_steps": rule.workflow_steps,
        }

        self._log(
            "info",
            f"New file detected: {os.path.basename(file_path)} | workflow: {describe_workflow_steps(rule.workflow_steps)}",
        )

        # 默认交给队列系统管理；只有未配置队列回调时才直接执行。
        if self.queue_callback:
            # 加入队列
            try:
                self.queue_callback(task_config)
                self._mark_processed(file_path, rule, "queued")
            except Exception as e:
                self._log("error", f"Failed to queue task: {e}")
                state.status = "error"
                self._record_file_observation(file_path, rule, True, "error")
            finally:
                self.current_tasks -= 1
                self._active_targets.discard(target_key)
        elif rule.auto_start and self.task_callback:
            # 在新线程中执行
            exec_thread = threading.Thread(
                target=self._execute_task,
                args=(file_path, rule, task_config, target_key),
                daemon=True
            )
            exec_thread.start()
        else:
            self._log("warning", "No task or queue callback configured")
            state.status = "error"
            self._record_file_observation(file_path, rule, True, "error")
            self.current_tasks -= 1
            self._active_targets.discard(target_key)

    def _execute_task(self, file_path: str, rule: WatchRule, task_config: dict, target_key: str):
        """执行任务"""
        state = self.file_states.get(file_path)
        try:
            self.task_callback(task_config)
            self._mark_processed(file_path, rule, "done")
            self._log("info", f"Task completed: {os.path.basename(file_path)}")
        except Exception as e:
            self._log("error", f"Task failed: {os.path.basename(file_path)} - {e}")
            if state:
                state.status = "error"
            self._record_file_observation(file_path, rule, True, "error")
        finally:
            self.current_tasks -= 1
            self._active_targets.discard(target_key)

    def _mark_processed(self, file_path: str, rule: WatchRule, status: str):
        """标记文件已处理"""
        file_key = self._get_file_key(file_path)
        self.processed_files.add(file_key)
        if rule.trigger_mode == "folder":
            try:
                files = self._scan_recursive(rule.watch_path, rule) if rule.recursive else self._scan_flat(rule.watch_path, rule)
                for related_path in files:
                    self.processed_files.add(self._get_file_key(related_path))
            except Exception as e:
                self._log("warning", f"Failed to mark related files: {e}")

        state = self.file_states.get(file_path)
        if state:
            state.status = status
        self._record_file_observation(file_path, rule, True, status)

        rule.files_processed += 1
        rule.last_activity = datetime.now()

        # 移动到完成目录
        if rule.move_to_done and rule.done_path and status == "done":
            try:
                dest = os.path.join(rule.done_path, os.path.basename(file_path))
                # 处理同名文件
                if os.path.exists(dest):
                    base, ext = os.path.splitext(dest)
                    dest = f"{base}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
                shutil.move(file_path, dest)
                self._log("info", f"Moved to done: {os.path.basename(file_path)}")
            except Exception as e:
                self._log("warning", f"Failed to move file: {e}")

        # 清理状态
        if file_path in self.file_states:
            del self.file_states[file_path]

    def _get_file_key(self, file_path: str) -> str:
        """生成文件唯一标识"""
        # 使用路径 + 修改时间 + 大小作为标识
        try:
            stat = os.stat(file_path)
            key_str = f"{file_path}:{stat.st_mtime}:{stat.st_size}"
            return hashlib.md5(key_str.encode()).hexdigest()
        except OSError:
            return hashlib.md5(file_path.encode()).hexdigest()

    def _generate_output_path(self, input_path: str) -> str:
        """生成输出路径"""
        parent = os.path.dirname(input_path)
        return os.path.join(parent, "output")

    def _load_processed_files(self):
        """加载已处理文件记录"""
        if not self.processed_file_path:
            return

        try:
            if os.path.exists(self.processed_file_path):
                with open(self.processed_file_path, 'r', encoding='utf-8') as f:
                    self.processed_files = set(line.strip() for line in f)
        except Exception:
            pass

    def _save_processed_files(self):
        """保存已处理文件记录"""
        if not self.processed_file_path:
            return

        try:
            with open(self.processed_file_path, 'w', encoding='utf-8') as f:
                for file_key in self.processed_files:
                    f.write(file_key + '\n')
        except Exception:
            pass

    def _log(self, level: str, message: str):
        """记录日志"""
        log_entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "message": message
        }
        self.logs.append(log_entry)

        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]

    def get_logs(self, limit: int = 20) -> List[dict]:
        """获取最近的日志"""
        return self.logs[-limit:]

    def load_from_config(self, config: dict):
        """从配置加载规则"""
        watch_config = config.get("watch_mode", {})

        self.scan_interval = watch_config.get("scan_interval", 10)
        self.max_concurrent = watch_config.get("max_concurrent", 2)

        rules_data = watch_config.get("rules", [])
        for rule_data in rules_data:
            try:
                rule = WatchRule.from_dict(rule_data)
                self.add_rule(rule)
            except Exception as e:
                self._log("error", f"Failed to load rule: {e}")

    def save_to_config(self, config: dict):
        """保存规则到配置"""
        if "watch_mode" not in config:
            config["watch_mode"] = {}

        config["watch_mode"]["rules"] = [
            rule.to_dict() for rule in self.rules.values()
        ]
        config["watch_mode"]["enabled"] = self.running
        config["watch_mode"]["scan_interval"] = self.scan_interval
        config["watch_mode"]["max_concurrent"] = self.max_concurrent

    def get_status(self) -> dict:
        """获取监控状态"""
        return {
            "running": self.running,
            "rule_count": len(self.rules),
            "enabled_count": sum(1 for r in self.rules.values() if r.enabled),
            "pending_files": len([s for s in self.file_states.values()
                                  if s.status in {"pending", "waiting_stable", "waiting_capacity", "waiting_target"}]),
            "current_tasks": self.current_tasks,
            "total_processed": sum(r.files_processed for r in self.rules.values())
        }

    def clear_processed_history(self):
        """清除已处理文件历史"""
        self.processed_files.clear()
        self.file_states.clear()
        self.file_observations.clear()
        self._log("info", "Processed history cleared")
