from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_config() -> dict:
    candidates = []
    explicit = os.environ.get("RZAI_PATH_CONFIG") or os.environ.get("PATH_CONFIG")
    if explicit:
        candidates.append(Path(os.path.expandvars(os.path.expanduser(explicit))))
    candidates.append(PROJECT_ROOT / "path-config.json")

    for path in candidates:
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid path config JSON at {path}: {exc}") from exc
    return {}


CONFIG = _load_config()


def config_value(*keys: str, default: str = ""):
    node = CONFIG
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return default if node is None else node


def _expand(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(str(value or "")))


def project_path(value: str | os.PathLike | None, default: str | os.PathLike) -> Path:
    text = _expand(str(value or default))
    path = Path(text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def config_path(section: str, key: str, default: str | os.PathLike) -> Path:
    return project_path(config_value(section, key, default=""), default)


def auth_profile(name: str, default_folder: str) -> Path:
    env_name = f"RZAI_{name.upper()}_PROFILE_ROOT"
    return project_path(os.environ.get(env_name) or config_value("profiles", name, default=""), Path("auth") / default_folder)


def auth_output(name: str, default_file: str) -> Path:
    env_name = f"RZAI_{name.upper()}_CREDS_FILE"
    return project_path(os.environ.get(env_name) or config_value("authOutputs", name, default=""), Path("auth") / default_file)


def runtime_path(section: str, key: str, default_file: str) -> Path:
    return config_path(section, key, Path(default_file))


def desktop_path(filename: str = "") -> Path:
    root = os.environ.get("USERPROFILE") or str(Path.home())
    desktop = Path(root) / "Desktop"
    return desktop / filename if filename else desktop


def chat2api_root() -> Path:
    value = os.environ.get("CHAT2API_ROOT") or config_value("chat2api", "root", default="")
    if value:
        return project_path(value, value)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "chat2api"
    return Path.home() / "AppData" / "Roaming" / "chat2api"


def yandex_user_data_root() -> Path:
    value = os.environ.get("YANDEX_USER_DATA_DIR") or config_value("browser", "yandexUserDataDir", default="")
    if value:
        return project_path(value, value)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Yandex" / "YandexBrowser" / "User Data"
    return Path.home() / "AppData" / "Local" / "Yandex" / "YandexBrowser" / "User Data"


def _path_from_env_root(env_name: str, *parts: str) -> Path | None:
    root = os.environ.get(env_name)
    if not root:
        return None
    return Path(root, *parts)


def _unique(values: Iterable[str | os.PathLike | None]) -> list[Path | str]:
    result: list[Path | str] = []
    seen = set()
    for value in values:
        if not value:
            continue
        text = _expand(str(value))
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        if any(separator in text for separator in ("/", "\\")):
            result.append(project_path(text, text))
        else:
            result.append(text)
    return result


def browser_candidates(include_yandex: bool = False) -> list[Path | str]:
    candidates: list[str | Path | None] = [
        os.environ.get("BROWSER_PATH"),
        os.environ.get("EDGE_PATH"),
        os.environ.get("CHROME_PATH"),
        config_value("browser", "executable", default=""),
    ]
    if include_yandex:
        candidates.extend(
            [
                config_value("browser", "yandexExecutable", default=""),
                _path_from_env_root("LOCALAPPDATA", "Yandex", "YandexBrowser", "Application", "browser.exe"),
            ]
        )
    candidates.extend(
        [
            _path_from_env_root("ProgramFiles(x86)", "Microsoft", "Edge", "Application", "msedge.exe"),
            _path_from_env_root("ProgramFiles", "Microsoft", "Edge", "Application", "msedge.exe"),
            _path_from_env_root("LOCALAPPDATA", "Microsoft", "Edge", "Application", "msedge.exe"),
            _path_from_env_root("ProgramFiles", "Google", "Chrome", "Application", "chrome.exe"),
            _path_from_env_root("ProgramFiles(x86)", "Google", "Chrome", "Application", "chrome.exe"),
            _path_from_env_root("LOCALAPPDATA", "Google", "Chrome", "Application", "chrome.exe"),
        ]
    )
    return _unique(candidates)


def node_candidates() -> list[Path | str]:
    return _unique(
        [
            os.environ.get("NODE"),
            os.environ.get("NODE_EXE"),
            config_value("node", "executable", default=""),
            shutil.which("node"),
            "node",
        ]
    )


def powershell_executable() -> str:
    candidates = _unique(
        [
            os.environ.get("POWERSHELL_EXE"),
            config_value("powershell", "executable", default=""),
            shutil.which("powershell"),
            shutil.which("pwsh"),
            _path_from_env_root("SystemRoot", "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
            "powershell",
        ]
    )
    try:
        return str(resolve_executable(candidates))
    except FileNotFoundError:
        return "powershell"


def resolve_executable(candidates: Iterable[str | os.PathLike], explicit: str = "") -> Path:
    values = [explicit] if explicit else []
    values.extend(candidates)
    for value in values:
        if not value:
            continue
        text = _expand(str(value))
        path = Path(text)
        if path.is_absolute():
            if path.exists():
                return path
            continue
        found = shutil.which(text)
        if found:
            return Path(found)
        if path.exists():
            return path.resolve()
    raise FileNotFoundError(
        "Required executable was not found. Set it in path-config.json or pass an explicit path."
    )
