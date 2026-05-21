import re
from collections import Counter


DEFAULT_MAX_STRONG = 5
DEFAULT_MAX_CANDIDATES = 2
DEFAULT_MIN_STRONG_SCORE = 80
DEFAULT_MIN_CANDIDATE_SCORE = 40
COMMON_JA_HONORIFICS = (
    "さん",
    "ちゃん",
    "くん",
    "君",
    "様",
    "さま",
    "殿",
    "先輩",
    "先生",
)


def recall_characters(
    characters,
    current_text_dict,
    previous_text_list=None,
    lookahead_text_list=None,
    config=None,
):
    """Select character profiles with local-only evidence.

    The previous/lookahead windows are used only for scoring. They are not
    returned, so callers can safely inject only character profiles into prompts.
    """
    if not characters:
        return {"strong": [], "candidates": []}

    current_lines = _dict_values(current_text_dict)
    previous_lines = _text_list(previous_text_list)
    lookahead_lines = _text_list(lookahead_text_list)
    current_text = "\n".join(current_lines)

    normalized_characters = [item for item in characters if isinstance(item, dict)]
    marker_counts = _build_trait_marker_counts(normalized_characters)

    scored = []
    for index, character in enumerate(normalized_characters):
        name_keywords = _collect_name_keywords(character)
        speech_markers = _extract_trait_markers(character.get("speech_quirks"))
        pronoun_markers = _extract_trait_markers(character.get("pronouns"))

        score = 0
        reasons = []

        current_score = _best_current_name_score(current_text, name_keywords)
        if current_score:
            score += current_score
            reasons.append("current_name")

        previous_score = _best_previous_name_score(previous_lines, name_keywords)
        if previous_score:
            score += previous_score
            reasons.append("previous_name")

        lookahead_score = _best_lookahead_name_score(lookahead_lines, name_keywords)
        if lookahead_score:
            score += lookahead_score
            reasons.append("lookahead_name")

        speech_score = _trait_score(current_text, speech_markers, marker_counts["speech_quirks"], 50, 20)
        if speech_score:
            score += speech_score
            reasons.append("speech_quirk")

        pronoun_score = _trait_score(current_text, pronoun_markers, marker_counts["pronouns"], 25, 8)
        if pronoun_score:
            score += pronoun_score
            reasons.append("pronoun")

        if score <= 0:
            continue

        scored.append(
            {
                "character": character,
                "score": score,
                "reasons": reasons,
                "order": index,
            }
        )

    scored.sort(key=lambda item: (-item["score"], item["order"]))

    min_strong_score = _int_config(config, "character_recall_min_strong_score", DEFAULT_MIN_STRONG_SCORE)
    min_candidate_score = _int_config(config, "character_recall_min_candidate_score", DEFAULT_MIN_CANDIDATE_SCORE)
    max_strong = _int_config(config, "character_recall_max_strong", DEFAULT_MAX_STRONG)
    max_candidates = _int_config(config, "character_recall_max_candidates", DEFAULT_MAX_CANDIDATES)

    strong = [item for item in scored if item["score"] >= min_strong_score][:max(0, max_strong)]
    strong_ids = {id(item["character"]) for item in strong}
    candidates = [
        item
        for item in scored
        if id(item["character"]) not in strong_ids and item["score"] >= min_candidate_score
    ][:max(0, max_candidates)]

    return {"strong": strong, "candidates": candidates}


def _dict_values(value):
    if isinstance(value, dict):
        return [str(item or "") for item in value.values()]
    return _text_list(value)


def _text_list(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item or "") for item in value]
    return [str(value)]


def _int_config(config, key, default):
    try:
        if isinstance(config, dict):
            value = config.get(key, default)
        elif hasattr(config, "get"):
            value = config.get(key, default)
        else:
            value = getattr(config, key, default)
        return int(value)
    except (TypeError, ValueError):
        return default


def _collect_name_keywords(character):
    keywords = []

    for field_name, weight in (
        ("original_name", 100),
        ("translated_name", 80),
        ("name", 90),
    ):
        for keyword in _split_name_field(character.get(field_name)):
            keywords.append((keyword, weight))
            for derived in _derive_source_name_aliases(keyword):
                keywords.append((derived, max(85, weight - 10)))

    for field_name in ("alias", "aliases", "nicknames", "other_names"):
        for keyword in _split_alias_field(character.get(field_name)):
            keywords.append((keyword, 90))
            for derived in _derive_source_name_aliases(keyword):
                keywords.append((derived, 85))

    result = []
    seen = set()
    for keyword, weight in keywords:
        keyword = _clean_keyword(keyword)
        if not _usable_name_keyword(keyword):
            continue
        marker = keyword.lower()
        if marker in seen:
            continue
        seen.add(marker)
        result.append((keyword, weight))
    return result


def _split_name_field(value):
    text = str(value or "").strip()
    if not text:
        return []
    if "[Separator]" in text:
        return text.split("[Separator]")
    if " " in text or "." in text:
        return re.split(r"[ .]", text)
    return [text]


def _split_alias_field(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_split_alias_field(item))
        return result
    text = str(value or "").strip()
    if not text:
        return []
    if "[Separator]" in text:
        return text.split("[Separator]")
    return re.split(r"[,;|/，、；／\n]+", text)


def _clean_keyword(value):
    return str(value or "").strip().replace("[Separator]", "")


def _usable_name_keyword(keyword):
    if not keyword:
        return False
    if len(keyword) >= 2:
        return True
    return keyword.isascii() and keyword.isalnum() and len(keyword) >= 2


def _derive_source_name_aliases(value):
    """Conservatively derive source-side aliases from Japanese names.

    This is intentionally narrow: it mainly covers names like 御空マヒル,
    where the source often later uses only マヒル or マヒルさん.
    """
    text = _clean_keyword(value)
    if not text:
        return []

    candidates = []
    stripped = _strip_common_japanese_honorific(text)
    if stripped and stripped != text:
        candidates.append(stripped)

    for candidate in (text, stripped):
        if not candidate:
            continue
        candidates.extend(_derive_kana_tail_aliases(candidate))

    result = []
    seen = set()
    for candidate in candidates:
        candidate = _clean_keyword(candidate)
        if not _usable_derived_alias(candidate):
            continue
        marker = candidate.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        result.append(candidate)
    return result


def _strip_common_japanese_honorific(text):
    for suffix in COMMON_JA_HONORIFICS:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _derive_kana_tail_aliases(text):
    aliases = []
    if "・" in text or "＝" in text or "=" in text:
        return aliases
    matches = list(re.finditer(r"[\u4e00-\u9fff々〆ヵヶ]+([\u3040-\u309f\u30a0-\u30ffー]{2,})$", text))
    if matches:
        tail = matches[-1].group(1)
        if tail != text:
            aliases.append(tail)
    return aliases


def _usable_derived_alias(keyword):
    if not _usable_name_keyword(keyword):
        return False
    if len(keyword) < 2:
        return False
    return bool(re.search(r"[\u3040-\u309f\u30a0-\u30ff]", keyword))


def _contains(text, keyword):
    if not text or not keyword:
        return False
    if keyword.isascii():
        return keyword.lower() in text.lower()
    return keyword in text


def _best_current_name_score(text, name_keywords):
    best = 0
    for keyword, weight in name_keywords:
        if _contains(text, keyword):
            best = max(best, weight)
    return best


def _best_previous_name_score(previous_lines, name_keywords):
    best = 0
    total = len(previous_lines)
    for index, line in enumerate(previous_lines):
        if not _line_has_name(line, name_keywords):
            continue
        distance = total - index
        if distance <= 10:
            best = max(best, 65)
        elif distance <= 25:
            best = max(best, 45)
        else:
            best = max(best, 25)
    return best


def _best_lookahead_name_score(lookahead_lines, name_keywords):
    best = 0
    for index, line in enumerate(lookahead_lines):
        if not _line_has_name(line, name_keywords):
            continue
        distance = index + 1
        if distance <= 4:
            best = max(best, 45)
        else:
            best = max(best, 25)
    return best


def _line_has_name(line, name_keywords):
    return any(_contains(line, keyword) for keyword, _ in name_keywords)


def _build_trait_marker_counts(characters):
    counters = {"pronouns": Counter(), "speech_quirks": Counter()}
    for character in characters:
        for key in counters:
            markers = set(_extract_trait_markers(character.get(key)))
            counters[key].update(markers)
    return counters


def _extract_trait_markers(value):
    text = str(value or "").strip()
    if not text:
        return []

    markers = []
    quote_pattern = r"[「『“\"']([^」』”\"']{1,16})[」』”\"']"
    markers.extend(match.strip() for match in re.findall(quote_pattern, text) if match.strip())

    normalized = text.replace("[Separator]", "\n")
    for segment in re.split(r"[,;|/，、；／\n]+", normalized):
        segment = segment.strip()
        if not segment:
            continue
        if ":" in segment:
            segment = segment.rsplit(":", 1)[-1].strip()
        if "：" in segment:
            segment = segment.rsplit("：", 1)[-1].strip()
        segment = _strip_parenthetical_hint(segment)
        if _usable_trait_marker(segment):
            markers.append(segment)

    result = []
    seen = set()
    for marker in markers:
        marker = marker.strip()
        if not _usable_trait_marker(marker):
            continue
        if marker in seen:
            continue
        seen.add(marker)
        result.append(marker)
    return result


def _strip_parenthetical_hint(value):
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\([^)]{1,32}\)", "", text).strip()
    text = re.sub(r"（[^）]{1,32}）", "", text).strip()
    return text


def _usable_trait_marker(marker):
    marker = str(marker or "").strip()
    if not marker:
        return False
    if len(marker) > 16:
        return False
    lowered = marker.lower()
    noisy_words = (
        "pronoun",
        "first person",
        "second person",
        "speech",
        "quirk",
        "第一人称",
        "第二人称",
        "口癖",
        "语尾",
        "語尾",
        "自称",
    )
    return not any(word in lowered for word in noisy_words)


def _trait_score(text, markers, counts, unique_score, shared_score):
    best = 0
    for marker in markers:
        if not _contains(text, marker):
            continue
        if counts.get(marker, 0) <= 1:
            best = max(best, unique_score)
        else:
            best = max(best, shared_score)
    return best
