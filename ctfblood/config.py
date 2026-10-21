"""Configuration for the CTF blood broadcast bot.

All settings are read from environment variables (or a local ``.env`` file).
Keeping configuration out of the code makes the same image usable for the
rehearsal race and the production race.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


def _get(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.getenv(name, default)
    if value is None or (required and not str(value).strip()):
        raise ConfigError(f"缺少环境变量 {name}，请参考 .env.example 配置")
    return str(value).strip()


def _get_int(name: str, default: int) -> int:
    raw = _get(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数，当前为 {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = _get(name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是数字，当前为 {raw!r}") from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name, "true" if default else "false").lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"{name} 必须是 true/false，当前为 {raw!r}")


def _get_levels(name: str, default: str = "1,2,3") -> tuple[int, ...]:
    raw = _get(name, default)
    levels: list[int] = []
    for part in raw.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            level = int(part)
        except ValueError as exc:
            raise ConfigError(f"{name} 只能是 1,2,3 的逗号分隔列表，当前为 {raw!r}") from exc
        if level not in (1, 2, 3):
            raise ConfigError(f"{name} 中的血位只能是 1/2/3，当前包含 {level}")
        if level not in levels:
            levels.append(level)
    if not levels:
        raise ConfigError(f"{name} 不能为空")
    return tuple(sorted(levels))


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Immutable so a reload creates a new object."""

    base_url: str
    race_id: str
    viewer_key: str
    group_id: int
    poll_interval: float = 2.0
    send_interval: float = 1.0
    request_timeout: float = 5.0
    catchup_mode: str = "announce"
    blood_levels: tuple[int, ...] = (1, 2, 3)
    dry_run: bool = False
    db_path: str = "data/ctf_blood.sqlite3"
    max_send_attempts: int = 5
    send_admin_errors: bool = True
    race_name: str = ""

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ConfigError("CTF_BASE_URL 必须以 http:// 或 https:// 开头")
        if self.poll_interval < 0.5:
            raise ConfigError("CTF_POLL_INTERVAL 不能小于 0.5 秒")
        if self.send_interval < 0.5:
            raise ConfigError("CTF_SEND_INTERVAL 不能小于 0.5 秒")
        if self.catchup_mode not in {"announce", "silent"}:
            raise ConfigError("CTF_CATCHUP_MODE 只能是 announce 或 silent")
        if not self.blood_levels:
            raise ConfigError("CTF_BLOOD_LEVELS 不能为空")

    @property
    def announcements_path(self) -> str:
        return f"/api/ct/public/jeopardy_race/race/{self.race_id}/rank/"

    @property
    def race_path(self) -> str:
        return f"/api/ct/public/jeopardy_race/race/{self.race_id}/"

    @property
    def base_info_path(self) -> str:
        return f"{self.race_path}base/"

    @property
    def team_path(self) -> str:
        return f"{self.race_path}rank/"

    def ensure_db_dir(self) -> None:
        Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Load settings from ``.env`` + environment variables."""

    load_dotenv(override=False)
    settings = Settings(
        base_url=_get("CTF_BASE_URL", required=True).rstrip("/"),
        race_id=_get("CTF_RACE_ID", required=True),
        viewer_key=_get("CTF_VIEWER_KEY", required=True),
        group_id=_get_int("CTF_GROUP_ID", 0),
        poll_interval=_get_float("CTF_POLL_INTERVAL", 2.0),
        send_interval=_get_float("CTF_SEND_INTERVAL", 1.0),
        request_timeout=_get_float("CTF_REQUEST_TIMEOUT", 5.0),
        catchup_mode=_get("CTF_CATCHUP_MODE", "announce").lower(),
        blood_levels=_get_levels("CTF_BLOOD_LEVELS"),
        dry_run=_get_bool("CTF_DRY_RUN", False),
        db_path=_get("CTF_DB_PATH", "data/ctf_blood.sqlite3"),
        max_send_attempts=_get_int("CTF_MAX_SEND_ATTEMPTS", 5),
        send_admin_errors=_get_bool("CTF_SEND_ADMIN_ERRORS", True),
        race_name=_get("CTF_RACE_NAME", ""),
    )
    if settings.group_id <= 0:
        raise ConfigError("CTF_GROUP_ID 必须是有效的 QQ 群号")
    settings.ensure_db_dir()
    return settings
