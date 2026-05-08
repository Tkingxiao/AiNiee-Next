from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont


_REPO_ROOT = Path(__file__).resolve().parents[3]

_FONT_CANDIDATES = {
    "source han sans sc": [
        "manga-translator-ui-main/fonts/msyh.ttc",
        "manga-translator-ui-main/fonts/Arial-Unicode-Regular.ttf",
        "manga-translator-ui-main/fonts/NotoSansMonoCJK-VF.ttf.ttc",
    ],
    "dialogue_default": [
        "manga-translator-ui-main/fonts/anime_ace.ttf",
        "manga-translator-ui-main/fonts/comic shanns 2.ttf",
        "manga-translator-ui-main/fonts/Arial-Unicode-Regular.ttf",
    ],
    "ms gothic": [
        "manga-translator-ui-main/fonts/msgothic.ttc",
        "manga-translator-ui-main/fonts/Arial-Unicode-Regular.ttf",
    ],
}

_FALLBACK_FONTS = [
    "manga-translator-ui-main/fonts/msyh.ttc",
    "manga-translator-ui-main/fonts/Arial-Unicode-Regular.ttf",
    "manga-translator-ui-main/fonts/NotoSansMonoCJK-VF.ttf.ttc",
    "manga-translator-ui-main/fonts/anime_ace.ttf",
]

_FONT_SUFFIXES = {".ttf", ".ttc", ".otf"}
_PREVIEW_TEXT = "漫画对白 Aa 123"

_BUILTIN_FONT_LABELS = {
    "manga-translator-ui-main/fonts/msyh.ttc": "Microsoft YaHei",
    "manga-translator-ui-main/fonts/Arial-Unicode-Regular.ttf": "Arial Unicode MS",
    "manga-translator-ui-main/fonts/NotoSansMonoCJK-VF.ttf.ttc": "Noto Sans Mono CJK",
    "manga-translator-ui-main/fonts/anime_ace.ttf": "Anime Ace",
    "manga-translator-ui-main/fonts/comic shanns 2.ttf": "Comic Shanns",
    "manga-translator-ui-main/fonts/msgothic.ttc": "MS Gothic",
}


@dataclass(frozen=True, slots=True)
class FontCatalogEntry:
    font_id: str
    display_name: str
    css_family: str
    source: str
    available: bool
    path_or_url: str
    scripts: tuple[str, ...] = ("latin", "cjk")
    preview_text: str = _PREVIEW_TEXT
    family: str = ""
    style: str = ""
    postscript_name: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["scripts"] = list(self.scripts)
        return payload


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "font"


def _path_hash(path: Path) -> str:
    return hashlib.sha1(str(path).lower().encode("utf-8", errors="ignore")).hexdigest()[:10]


def _css_family(display_name: str) -> str:
    escaped = display_name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}", sans-serif'


def _clean_display_name(value: str) -> str:
    stem = Path(value).stem if value else ""
    cleaned = re.sub(r"[_-]+", " ", stem).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "Unknown Font"


def _normalize_font_query(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    first_family = text.split(",", 1)[0].strip()
    first_family = first_family.strip("\"'")
    return re.sub(r"\s+", " ", first_family).lower()


def _font_id(source: str, display_name: str, path: Path) -> str:
    return f"{source}:{_slug(display_name)}:{_path_hash(path)}"


def _font_entry(
    *,
    source: str,
    path: Path,
    display_name: str,
    family: str = "",
    style: str = "",
    postscript_name: str = "",
) -> FontCatalogEntry | None:
    if not path.exists() or path.suffix.lower() not in _FONT_SUFFIXES:
        return None
    name = display_name.strip() or family.strip() or _clean_display_name(path.name)
    return FontCatalogEntry(
        font_id=_font_id(source, name, path),
        display_name=name,
        css_family=_css_family(name),
        source=source,
        available=True,
        path_or_url=str(path),
        family=family or name,
        style=style,
        postscript_name=postscript_name,
    )


def _builtin_font_entries() -> list[FontCatalogEntry]:
    entries: list[FontCatalogEntry] = []
    seen: set[Path] = set()
    relative_paths = [*_FALLBACK_FONTS, *[path for paths in _FONT_CANDIDATES.values() for path in paths]]
    for relative_path in relative_paths:
        path = (_REPO_ROOT / relative_path).resolve()
        if path in seen:
            continue
        seen.add(path)
        entry = _font_entry(
            source="builtin",
            path=path,
            display_name=_BUILTIN_FONT_LABELS.get(relative_path, _clean_display_name(relative_path)),
        )
        if entry is not None:
            entries.append(entry)
    return entries


def _fc_list_system_fonts() -> list[FontCatalogEntry]:
    try:
        result = subprocess.run(
            ["fc-list", "--format", "%{file}\t%{family}\t%{style}\n"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []

    entries: list[FontCatalogEntry] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        path = Path(parts[0]).expanduser()
        families = [item.strip() for item in parts[1].split(",") if item.strip()]
        style = parts[2].strip() if len(parts) > 2 else ""
        display_name = families[0] if families else _clean_display_name(path.name)
        entry = _font_entry(
            source="system",
            path=path,
            display_name=display_name,
            family=display_name,
            style=style,
        )
        if entry is not None:
            entries.append(entry)
    return entries


def _windows_registry_fonts() -> list[FontCatalogEntry]:
    if platform.system().lower() != "windows":
        return []
    try:
        import winreg
    except ImportError:
        return []

    entries: list[FontCatalogEntry] = []
    font_root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    registry_roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    ]
    for hive, subkey in registry_roots:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                count = winreg.QueryInfoKey(key)[1]
                for index in range(count):
                    name, value, _value_type = winreg.EnumValue(key, index)
                    file_name = str(value)
                    path = Path(file_name)
                    if not path.is_absolute():
                        path = font_root / file_name
                    display_name = re.sub(r"\s*\((TrueType|OpenType|Collection)\)\s*$", "", str(name)).strip()
                    entry = _font_entry(source="system", path=path, display_name=display_name)
                    if entry is not None:
                        entries.append(entry)
        except OSError:
            continue
    return entries


def _scan_font_directory(directory: Path, source: str) -> list[FontCatalogEntry]:
    if not directory.exists():
        return []
    entries: list[FontCatalogEntry] = []
    try:
        for path in directory.rglob("*"):
            if len(entries) >= 600:
                break
            if path.suffix.lower() not in _FONT_SUFFIXES:
                continue
            entry = _font_entry(source=source, path=path, display_name=_clean_display_name(path.name))
            if entry is not None:
                entries.append(entry)
    except OSError:
        return entries
    return entries


def _common_system_font_dirs() -> list[Path]:
    home = Path.home()
    system_name = platform.system().lower()
    if system_name == "darwin":
        return [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            home / "Library" / "Fonts",
        ]
    if system_name == "windows":
        return [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    return [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        home / ".local" / "share" / "fonts",
        home / ".fonts",
    ]


def _system_font_entries() -> list[FontCatalogEntry]:
    entries = _windows_registry_fonts()
    if not entries:
        entries = _fc_list_system_fonts()
    if not entries:
        for directory in _common_system_font_dirs():
            entries.extend(_scan_font_directory(directory, source="system"))
    return entries


def _project_font_entries(project_path: Path | None) -> list[FontCatalogEntry]:
    if project_path is None:
        return []
    entries: list[FontCatalogEntry] = []
    for relative in ("fonts", "assets/fonts", "mangaProject/fonts"):
        entries.extend(_scan_font_directory(project_path / relative, source="project"))
    return entries


def _dedupe_entries(entries: list[FontCatalogEntry]) -> tuple[FontCatalogEntry, ...]:
    by_id: dict[str, FontCatalogEntry] = {}
    by_path: set[str] = set()
    for entry in entries:
        path_key = str(entry.path_or_url).lower()
        if path_key in by_path:
            continue
        by_path.add(path_key)
        by_id[entry.font_id] = entry
    return tuple(
        sorted(
            by_id.values(),
            key=lambda item: (
                {"builtin": 0, "project": 1, "system": 2}.get(item.source, 9),
                item.display_name.lower(),
            ),
        )
    )


@lru_cache(maxsize=8)
def _font_catalog_cached(project_path_text: str = "") -> tuple[FontCatalogEntry, ...]:
    project_path = Path(project_path_text) if project_path_text else None
    return _dedupe_entries([*_builtin_font_entries(), *_project_font_entries(project_path), *_system_font_entries()])


def list_font_catalog(project_path: Path | str | None = None) -> tuple[FontCatalogEntry, ...]:
    project_path_text = str(Path(project_path).resolve()) if project_path else ""
    return _font_catalog_cached(project_path_text)


def _catalog_lookup(project_path: Path | str | None = None) -> dict[str, FontCatalogEntry]:
    lookup: dict[str, FontCatalogEntry] = {}
    for entry in list_font_catalog(project_path):
        values = [
            entry.font_id,
            entry.display_name,
            entry.family,
            entry.postscript_name,
            entry.css_family,
        ]
        for value in values:
            normalized = _normalize_font_query(value)
            if normalized and normalized not in lookup:
                lookup[normalized] = entry
        if entry.font_id not in lookup:
            lookup[entry.font_id] = entry
    return lookup


@lru_cache(maxsize=1)
def list_available_fonts() -> tuple[Path, ...]:
    return tuple(Path(entry.path_or_url) for entry in list_font_catalog() if entry.path_or_url)


def resolve_requested_font_path(
    font_family: str = "",
    font_prediction: str = "",
    font_id: str = "",
    project_path: Path | str | None = None,
) -> Path | None:
    lookup = _catalog_lookup(project_path)
    for raw_query in (font_id, font_family, font_prediction):
        if not raw_query:
            continue
        if str(raw_query) in lookup:
            return Path(lookup[str(raw_query)].path_or_url)
        normalized_query = _normalize_font_query(str(raw_query))
        if normalized_query in lookup:
            return Path(lookup[normalized_query].path_or_url)

    normalized = _normalize_font_query(str(font_family or font_prediction or ""))
    for key, candidates in _FONT_CANDIDATES.items():
        if normalized and (key in normalized or normalized in key):
            for relative_path in candidates:
                absolute_path = _REPO_ROOT / relative_path
                if absolute_path.exists():
                    return absolute_path
    return None


def resolve_font_path(
    font_family: str = "",
    font_prediction: str = "",
    font_id: str = "",
    project_path: Path | str | None = None,
) -> Path | None:
    requested = resolve_requested_font_path(
        font_family=font_family,
        font_prediction=font_prediction,
        font_id=font_id,
        project_path=project_path,
    )
    if requested is not None:
        return requested

    for relative_path in _FALLBACK_FONTS:
        absolute_path = _REPO_ROOT / relative_path
        if absolute_path.exists():
            return absolute_path
    return None


def load_font(
    size: int,
    font_family: str = "",
    font_prediction: str = "",
    font_id: str = "",
    project_path: Path | str | None = None,
):
    font_path = resolve_font_path(
        font_family=font_family,
        font_prediction=font_prediction,
        font_id=font_id,
        project_path=project_path,
    )
    if font_path is not None:
        try:
            return ImageFont.truetype(str(font_path), max(10, int(size)))
        except OSError:
            pass
    return ImageFont.load_default()
