from ModuleFolders.Infrastructure.Cache.CacheProject import ProjectType


TEXT_EBOOK_PROJECT_TYPES = {
    ProjectType.TXT,
    ProjectType.MD,
    ProjectType.EPUB,
    ProjectType.DOCX,
}


def should_normalize_japanese_quotes(task_config, cache_file, project_type: str) -> bool:
    if task_config is None or cache_file is None:
        return False
    if not getattr(task_config, "japanese_text_quote_style_switch", True):
        return False
    if project_type not in TEXT_EBOOK_PROJECT_TYPES:
        return False

    source_language = getattr(task_config, "source_language", "auto")
    target_language = getattr(task_config, "target_language", "")
    if not _is_chinese_target_language(target_language):
        return False

    language_stats = getattr(cache_file, "language_stats", [])
    resolved_language = _get_source_language_for_file(source_language, target_language, language_stats)
    normalized_language = _map_language_code_to_name(str(resolved_language or "").strip()).lower()
    return normalized_language == "japanese" or str(resolved_language or "").strip().lower() in {"ja", "japanese"}


def _is_chinese_target_language(target_language) -> bool:
    normalized_language = _map_language_code_to_name(str(target_language or "").strip()).lower()
    raw_language = str(target_language or "").strip().lower().replace("_", "-")
    return normalized_language in {"chinese", "chinese_simplified", "chinese_traditional"} or raw_language in {
        "chinese",
        "zh",
        "zh-cn",
        "zh-hans",
        "zh-tw",
        "zh-hant",
        "yue",
    }


def _get_source_language_for_file(source_language, target_language, language_stats) -> str:
    try:
        from ModuleFolders.Service.TaskExecutor.TranslatorUtil import get_source_language_for_file

        return get_source_language_for_file(source_language, target_language, language_stats)
    except Exception:
        if source_language and source_language != "auto":
            return source_language
        return language_stats[0][0] if language_stats else "un"


def _map_language_code_to_name(language_code: str) -> str:
    try:
        from ModuleFolders.Service.TaskExecutor.TranslatorUtil import map_language_code_to_name

        return map_language_code_to_name(language_code)
    except Exception:
        return {
            "ja": "japanese",
            "jpn": "japanese",
        }.get(str(language_code or "").strip().lower(), language_code)


def normalize_japanese_quotes(text: str) -> str:
    if not text:
        return text

    result = []
    in_double_quote = False
    in_single_quote = False

    for index, char in enumerate(text):
        if char == "“":
            result.append("「")
            in_double_quote = True
        elif char == "”":
            result.append("」")
            in_double_quote = False
        elif char == '"':
            result.append("」" if in_double_quote else "「")
            in_double_quote = not in_double_quote
        elif char == "‘":
            result.append("『")
            in_single_quote = True
        elif char == "’":
            if _is_ascii_apostrophe(text, index):
                result.append(char)
            else:
                result.append("』")
                in_single_quote = False
        elif char == "'":
            if _is_ascii_apostrophe(text, index):
                result.append(char)
            else:
                result.append("』" if in_single_quote else "『")
                in_single_quote = not in_single_quote
        else:
            result.append(char)

    return "".join(result)


def _is_ascii_apostrophe(text: str, index: int) -> bool:
    previous_char = text[index - 1] if index > 0 else ""
    next_char = text[index + 1] if index + 1 < len(text) else ""
    return _is_ascii_word_char(previous_char) and _is_ascii_word_char(next_char)


def _is_ascii_word_char(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char == "_")
