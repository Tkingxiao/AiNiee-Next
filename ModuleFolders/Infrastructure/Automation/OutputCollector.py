import os
import shutil
from pathlib import Path


AUTOMATION_OUTPUT_COLLECTION_CONFIG_KEY = "automation_output_collection"

DEFAULT_OUTPUT_COLLECTION_CONFIG = {
    "enabled": False,
    "output_path": "",
    "collision_policy": "rename",
}

RUNTIME_DIR_NAMES = {
    "__pycache__",
    ".cache",
    "backups",
    "cache",
    "logs",
    "temp",
    "temp_conv",
    "temp_xlsx_conv",
    "tmp",
}

PRODUCT_DIR_NAMES = {
    "bilingual_auto",
    "bilingual_epub",
    "bilingual_pdf",
    "bilingual_srt",
    "bilingual_txt",
    "exports",
    "final",
}

RUNTIME_FILE_NAMES = {
    "AinieeCacheData.json",
    "AinieeCacheData_proofread.json",
    "ProjectStatistics.json",
}

RUNTIME_FILE_SUFFIXES = {
    ".jsonl",
    ".lock",
    ".log",
    ".tmp",
}


def normalize_output_collection_config(config: dict | None) -> dict:
    normalized = dict(DEFAULT_OUTPUT_COLLECTION_CONFIG)
    if isinstance(config, dict):
        normalized.update({
            key: value
            for key, value in config.items()
            if key in normalized
        })
    normalized["enabled"] = bool(normalized.get("enabled"))
    normalized["output_path"] = str(normalized.get("output_path") or "").strip().strip('"').strip("'")
    if normalized.get("collision_policy") not in {"rename", "overwrite"}:
        normalized["collision_policy"] = "rename"
    return normalized


def should_collect_automation_outputs(task) -> bool:
    return getattr(task, "source", None) == "watch"


def collect_automation_outputs(task, config: dict | None) -> list[dict]:
    collection_config = normalize_output_collection_config(config)
    if not collection_config["enabled"] or not collection_config["output_path"]:
        return []
    if not should_collect_automation_outputs(task):
        return []

    source_dir = Path(str(getattr(task, "output_path", "") or "")).expanduser()
    if not source_dir.is_dir():
        return []

    destination_root = Path(collection_config["output_path"]).expanduser()
    destination_root.mkdir(parents=True, exist_ok=True)

    copied = []
    for source_file, relative_path in _iter_product_files(source_dir):
        destination_path = _resolve_destination_path(
            destination_root,
            relative_path,
            collection_config["collision_policy"],
        )
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_path)
        copied.append({
            "source": str(source_file),
            "destination": str(destination_path),
        })
    return copied


def _iter_product_files(source_dir: Path):
    product_files = []
    final_dir = source_dir / "final"
    if final_dir.is_dir():
        product_files.extend(_walk_product_files(final_dir, final_dir, final_only=True))
    for product_dir in _iter_product_dirs(source_dir):
        if product_dir == final_dir:
            continue
        product_files.extend(_walk_product_files(product_dir, product_dir, final_only=True))

    if product_files:
        yield from product_files
        return

    yield from _walk_product_files(source_dir, source_dir)


def _walk_product_files(root_dir: Path, relative_root: Path, final_only: bool = False):
    for current_dir, dir_names, file_names in os.walk(root_dir):
        if final_only:
            dir_names[:] = [name for name in dir_names if not _is_runtime_dir_name(name)]
        else:
            dir_names[:] = [
                name
                for name in dir_names
                if not _is_runtime_dir_name(name) and _should_enter_dir(name)
            ]

        current_path = Path(current_dir)
        for file_name in file_names:
            source_file = current_path / file_name
            if _is_runtime_file(source_file):
                continue
            if not source_file.is_file():
                continue
            yield source_file, source_file.relative_to(relative_root)


def _iter_product_dirs(source_dir: Path):
    for current_dir, dir_names, _file_names in os.walk(source_dir):
        dir_names[:] = [
            name
            for name in dir_names
            if not _is_runtime_dir_name(name)
        ]
        current_path = Path(current_dir)
        for dir_name in list(dir_names):
            candidate = current_path / dir_name
            if dir_name in PRODUCT_DIR_NAMES:
                yield candidate


def _is_runtime_dir_name(name: str) -> bool:
    return str(name or "").strip() in RUNTIME_DIR_NAMES


def _should_enter_dir(name: str) -> bool:
    return str(name or "").strip() in PRODUCT_DIR_NAMES


def _is_runtime_file(path: Path) -> bool:
    name = path.name
    if name in RUNTIME_FILE_NAMES:
        return True
    return path.suffix.lower() in RUNTIME_FILE_SUFFIXES


def _resolve_destination_path(destination_root: Path, relative_path: Path, collision_policy: str) -> Path:
    destination_path = destination_root / relative_path
    if collision_policy == "overwrite" or not destination_path.exists():
        return destination_path

    stem = destination_path.stem
    suffix = destination_path.suffix
    parent = destination_path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
