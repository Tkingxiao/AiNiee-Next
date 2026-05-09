from __future__ import annotations

import os
import platform
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PhotoshopLocation:
    available: bool
    executable_path: str = ""
    source: str = ""
    checked_at: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _available(path: str | Path, source: str) -> PhotoshopLocation | None:
    candidate = Path(path)
    if candidate.exists():
        return PhotoshopLocation(
            available=True,
            executable_path=str(candidate),
            source=source,
            checked_at=_now_iso(),
            message="Photoshop executable found.",
        )
    return None


def _from_environment() -> PhotoshopLocation | None:
    configured = os.environ.get("PHOTOSHOP_PATH", "").strip().strip("\"'")
    if not configured:
        return None
    return _available(configured, "env:PHOTOSHOP_PATH")


def _from_app_paths_registry() -> PhotoshopLocation | None:
    if platform.system().lower() != "windows":
        return None
    try:
        import winreg
    except ImportError:
        return None

    subkey = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Photoshop.exe"
    for hive, source in (
        (winreg.HKEY_LOCAL_MACHINE, "registry:HKLM/App Paths"),
        (winreg.HKEY_CURRENT_USER, "registry:HKCU/App Paths"),
    ):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                for value_name in ("", "Path"):
                    try:
                        value, _value_type = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    candidate = Path(str(value))
                    if value_name == "Path":
                        candidate = candidate / "Photoshop.exe"
                    location = _available(candidate, source)
                    if location is not None:
                        return location
        except OSError:
            continue
    return None


def _from_adobe_registry() -> PhotoshopLocation | None:
    if platform.system().lower() != "windows":
        return None
    try:
        import winreg
    except ImportError:
        return None

    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Adobe\Photoshop", "registry:HKLM/Adobe Photoshop"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Adobe\Photoshop", "registry:HKCU/Adobe Photoshop"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Adobe\Photoshop", "registry:HKLM/WOW6432Node Adobe Photoshop"),
    ]
    for hive, subkey, source in roots:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                versions: list[str] = []
                index = 0
                while True:
                    try:
                        versions.append(winreg.EnumKey(key, index))
                        index += 1
                    except OSError:
                        break
            for version in sorted(versions, reverse=True):
                try:
                    with winreg.OpenKey(hive, f"{subkey}\\{version}") as version_key:
                        for value_name in ("ApplicationPath", "InstallPath", "Path"):
                            try:
                                install_path, _value_type = winreg.QueryValueEx(version_key, value_name)
                            except OSError:
                                continue
                            location = _available(Path(str(install_path)) / "Photoshop.exe", source)
                            if location is not None:
                                return location
                except OSError:
                    continue
        except OSError:
            continue
    return None


def _program_files_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name, fallback in (
        ("ProgramFiles", r"C:\Program Files"),
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        value = os.environ.get(env_name, fallback)
        if value:
            roots.append(Path(value))
    return roots


def _from_program_files() -> PhotoshopLocation | None:
    if platform.system().lower() != "windows":
        return None
    for root in _program_files_roots():
        adobe_root = root / "Adobe"
        if not adobe_root.exists():
            continue
        try:
            candidates = sorted(adobe_root.glob("Adobe Photoshop */Photoshop.exe"), reverse=True)
        except OSError:
            candidates = []
        for candidate in candidates:
            location = _available(candidate, "scan:Program Files Adobe")
            if location is not None:
                return location
    for version in ("2026", "2025", "2024", "2023", "2022", "2021"):
        for root in _program_files_roots():
            location = _available(root / "Adobe" / f"Adobe Photoshop {version}" / "Photoshop.exe", "scan:known Program Files path")
            if location is not None:
                return location
    return None


def _from_macos_applications() -> PhotoshopLocation | None:
    if platform.system().lower() != "darwin":
        return None
    roots = [Path("/Applications"), Path.home() / "Applications"]
    for root in roots:
        if not root.exists():
            continue
        try:
            apps = sorted(
                [
                    *root.glob("Adobe Photoshop*.app/Contents/MacOS/*"),
                    *root.glob("Adobe Photoshop*/*.app/Contents/MacOS/*"),
                ],
                reverse=True,
            )
        except OSError:
            apps = []
        for candidate in apps:
            if "photoshop" not in candidate.name.lower():
                continue
            location = _available(candidate, "scan:macOS Applications")
            if location is not None:
                return location
    return None


def find_photoshop_location() -> PhotoshopLocation:
    for finder in (
        _from_environment,
        _from_app_paths_registry,
        _from_adobe_registry,
        _from_program_files,
        _from_macos_applications,
    ):
        location = finder()
        if location is not None:
            return location
    return PhotoshopLocation(
        available=False,
        checked_at=_now_iso(),
        message="Photoshop executable was not found. PSD export can still generate JSX scripts.",
    )
