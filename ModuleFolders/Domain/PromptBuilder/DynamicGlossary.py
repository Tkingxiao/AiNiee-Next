import copy


TIMELINE_TEXT_KEYS = {
    "world_building_content": "world_building_history",
    "writing_style_content": "writing_style_history",
}


def normalize_volume(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    import re
    match = re.search(r"(?i)(?:vol(?:ume)?|book|v|第)?[\s._\-]*0*(\d{1,4})(?:\s*[卷册集部])?", str(value))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def apply_dynamic_glossary(config, current_volume):
    volume = normalize_volume(current_volume)
    if volume is None:
        return

    config.prompt_dictionary_data = [
        selected
        for selected in (
            _select_timeline_item(item, volume, "src", ("dst", "info"))
            for item in _get_original_list(config, "prompt_dictionary_data")
            if isinstance(item, dict)
        )
        if selected is not None
    ]
    config.characterization_data = [
        selected
        for selected in (
            _select_timeline_item(
                item,
                volume,
                "original_name",
                (
                    "translated_name",
                    "aliases",
                    "gender",
                    "age",
                    "personality",
                    "speech_style",
                    "pronouns",
                    "speech_quirks",
                    "additional_info",
                ),
            )
            for item in _get_original_list(config, "characterization_data")
            if isinstance(item, dict)
        )
        if selected is not None
    ]

    for data_key, history_key in TIMELINE_TEXT_KEYS.items():
        selected = _select_text_history(getattr(config, history_key, None), volume)
        if selected is not None:
            setattr(config, data_key, selected)
        elif isinstance(getattr(config, history_key, None), list) and getattr(config, history_key, None):
            setattr(config, data_key, "")


def _get_original_list(config, attr_name):
    backup_attr = f"_dynamic_glossary_original_{attr_name}"
    if not hasattr(config, backup_attr):
        setattr(config, backup_attr, copy.deepcopy(getattr(config, attr_name, []) or []))
    return getattr(config, backup_attr)


def _select_timeline_item(item, current_volume, key_field, tracked_fields):
    selected = copy.deepcopy(item)
    history = item.get("history")
    if not isinstance(history, list) or not history:
        item_volume = normalize_volume(item.get("volume"))
        if item_volume is not None and item_volume > current_volume:
            return None
        return selected

    history_entry = _select_effective_history_entry(history, current_volume, key_field, tracked_fields)
    if not history_entry:
        return None

    base_key = item.get(key_field)
    selected = copy.deepcopy(item)
    selected.pop("history", None)
    selected.pop("updated_in", None)
    selected.pop("updated_volume", None)
    if base_key:
        selected[key_field] = base_key
    for field in tracked_fields:
        if field in history_entry:
            selected[field] = history_entry.get(field)
    if history_entry.get("source"):
        selected["source"] = history_entry.get("source")
    if normalize_volume(history_entry.get("volume")) is not None:
        selected["volume"] = normalize_volume(history_entry.get("volume"))
    return selected


def _select_text_history(history, current_volume):
    if not isinstance(history, list) or not history:
        return None
    selected = ""
    for entry in sorted((item for item in history if isinstance(item, dict)), key=_history_sort_key):
        volume = normalize_volume(entry.get("volume"))
        if volume is None or volume > current_volume:
            continue
        content = entry.get("content")
        if content is None:
            continue
        selected = _append_timeline_text_block(selected, str(content))
    return selected or None


def _select_effective_history_entry(history, current_volume, key_field, tracked_fields):
    selected = {}
    selected_volume = None
    selected_source = ""
    for entry in sorted((item for item in history if isinstance(item, dict)), key=_history_sort_key):
        if not isinstance(entry, dict):
            continue
        volume = normalize_volume(entry.get("volume"))
        if volume is None or volume > current_volume:
            continue
        key_value = entry.get(key_field)
        if key_value:
            selected[key_field] = key_value
        for field in tracked_fields:
            if _has_text(entry.get(field)):
                selected[field] = entry.get(field)
        selected_volume = volume
        selected_source = entry.get("source") or f"Vol_{volume}"
    if not selected:
        return None
    if selected_source:
        selected["source"] = selected_source
    if selected_volume is not None:
        selected["volume"] = selected_volume
    return selected


def _history_sort_key(entry):
    volume = normalize_volume(entry.get("volume")) if isinstance(entry, dict) else None
    if volume is None:
        return (10**9, str(entry.get("source") if isinstance(entry, dict) else ""))
    return (volume, "")


def _has_text(value):
    if isinstance(value, (list, tuple, set)):
        return any(_has_text(item) for item in value)
    return bool(str(value).strip()) if value is not None else False


def _append_timeline_text_block(existing, addition):
    existing = str(existing or "").strip()
    addition = str(addition or "").strip()
    if not addition:
        return existing
    if not existing:
        return addition
    if addition in existing:
        return existing
    if existing in addition:
        return addition
    return f"{existing.rstrip()}\n\n{addition}"
