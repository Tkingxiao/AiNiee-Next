import os


AUTOMATION_GLOSSARY_DIR_NAME = "自动术语"
AUTOMATION_OUTPUT_DIR_NAMES = {"output"}
AUTOMATION_OUTPUT_DIR_SUFFIXES = ("_AiNiee_Output", "_Polishing_Output")


def automation_glossary_dir_for(input_path: str) -> str:
    input_dir = os.path.dirname(os.path.abspath(input_path)) if input_path else os.getcwd()
    if os.path.isdir(input_path):
        input_dir = os.path.abspath(input_path)
    return os.path.join(input_dir, AUTOMATION_GLOSSARY_DIR_NAME)


def is_under_automation_glossary_dir(path: str, watch_root: str = "") -> bool:
    if not path:
        return False
    try:
        path = os.path.abspath(path)
        if watch_root:
            relative = os.path.relpath(path, os.path.abspath(watch_root))
            if relative.startswith(".."):
                return False
            parts = relative.split(os.sep)
        else:
            parts = path.split(os.sep)
    except (OSError, ValueError):
        return False
    return any(part == AUTOMATION_GLOSSARY_DIR_NAME for part in parts)


def is_under_automation_output_dir(path: str, watch_root: str = "") -> bool:
    if not path:
        return False
    try:
        path = os.path.abspath(path)
        if watch_root:
            relative = os.path.relpath(path, os.path.abspath(watch_root))
            if relative.startswith(".."):
                return False
            parts = relative.split(os.sep)
        else:
            parts = path.split(os.sep)
    except (OSError, ValueError):
        return False
    return any(
        part in AUTOMATION_OUTPUT_DIR_NAMES
        or any(part.endswith(suffix) for suffix in AUTOMATION_OUTPUT_DIR_SUFFIXES)
        for part in parts
    )
