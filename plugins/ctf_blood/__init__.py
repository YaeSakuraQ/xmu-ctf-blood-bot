"""CTF blood broadcast plugin (NoneBot2 + OneBot v11).

Load order: ``bot.py`` initialises NoneBot, loads
``nonebot_plugin_apscheduler`` and then this plugin. The plugin owns one
:class:`~ctfblood.service.BloodService` instance and registers two scheduler
jobs: a 2-second poll and a 1-second sender.
"""

from __future__ import annotations

import logging

import nonebot
from nonebot import require
from nonebot.log import logger
from nonebot.log import logger as nb_logger
from nonebot.plugin import PluginMetadata

from ctfblood.api import CTFClient
from ctfblood.announcement import send_new_challenges_notice
from ctfblood.config import Settings, load_settings
from ctfblood.service import BloodService
from ctfblood.store import Store

from .notifier import NoneBotNotifier


class _LoguruHandler(logging.Handler):
    """Forward ``ctfblood`` stdlib logs into NoneBot's loguru sink."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = nb_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        nb_logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def _bridge_core_logging() -> None:
    core = logging.getLogger("ctfblood")
    if any(isinstance(handler, _LoguruHandler) for handler in core.handlers):
        return
    core.addHandler(_LoguruHandler())
    core.setLevel(logging.INFO)
    core.propagate = False
    # httpx logs the full URL at INFO, including viewer_key.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


_bridge_core_logging()

__plugin_meta__ = PluginMetadata(
    name="CTF 血报",
    description="轮询实训平台公开大屏榜单，把一/二/三血实时播报到 QQ 群",
    usage="/ctf status | /ctf rank [N] | /ctf blood [关键词] | /ctf test | /ctf reload",
    type="application",
    config=None,
    supported_adapters={"~onebot.v11"},
)

scheduler = require("nonebot_plugin_apscheduler").scheduler
driver = nonebot.get_driver()

_settings: Settings | None = None
_service: BloodService | None = None
_store: Store | None = None


def get_settings() -> Settings:
    if _settings is None:
        raise RuntimeError("CTF 血报插件尚未初始化")
    return _settings


def get_service() -> BloodService:
    if _service is None:
        raise RuntimeError("CTF 血报插件尚未初始化")
    return _service


def get_store() -> Store:
    if _store is None:
        raise RuntimeError("CTF 血报插件尚未初始化")
    return _store


def _add_jobs(service: BloodService, settings: Settings) -> None:
    scheduler.add_job(
        service.poll_job,
        "interval",
        seconds=settings.poll_interval,
        id="ctf_blood_poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=5,
    )
    scheduler.add_job(
        service.send_job,
        "interval",
        seconds=settings.send_interval,
        id="ctf_blood_send",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=5,
    )
    scheduler.add_job(
        _new_challenges_job,
        "interval",
        seconds=15,
        id="ctf_new_challenges_notice",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


async def _new_challenges_job() -> None:
    service = get_service()
    await send_new_challenges_notice(
        race_id=service.settings.race_id,
        store=service.store,
        notifier=service.notifier,
        dry_run=service.settings.dry_run,
    )


def _remove_jobs() -> None:
    for job_id in ("ctf_blood_poll", "ctf_blood_send", "ctf_new_challenges_notice"):
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)


async def _build(settings: Settings) -> tuple[BloodService, Store]:
    store = Store(settings.db_path)
    client = CTFClient(settings)
    notifier = NoneBotNotifier(settings.group_id, dry_run=settings.dry_run)
    service = BloodService(settings, client, store, notifier)
    await service.load_race_info()
    return service, store


@driver.on_startup
async def _startup() -> None:
    global _settings, _service, _store

    _settings = load_settings()
    _service, _store = await _build(_settings)
    _add_jobs(_service, _settings)

    logger.info(
        "CTF 血报已启动: race={} group={} poll={}s send={}s dry_run={}".format(
            _settings.race_id,
            _settings.group_id,
            _settings.poll_interval,
            _settings.send_interval,
            _settings.dry_run,
        )
    )
    if _settings.dry_run:
        logger.warning("CTF_DRY_RUN=true，只打印不发送 QQ 消息")


@driver.on_shutdown
async def _shutdown() -> None:
    _remove_jobs()
    if _service is not None:
        await _service.close()


async def reload_service() -> str:
    """Reload ``.env`` and rebuild the client/store/jobs (used by /ctf reload)."""

    global _settings, _service, _store

    new_settings = load_settings(reload_file=True)
    new_service, new_store = await _build(new_settings)

    old_service = _service
    _remove_jobs()
    _settings, _service, _store = new_settings, new_service, new_store
    _add_jobs(new_service, new_settings)

    if old_service is not None:
        try:
            await old_service.close()
        except Exception as exc:  # noqa: BLE001 - old resources are best-effort
            logger.warning("关闭旧服务失败: {}", exc)

    logger.info("CTF 血报已重载: race={} group={}", new_settings.race_id, new_settings.group_id)
    return (
        f"已重载：race={new_settings.race_id} group={new_settings.group_id} "
        f"poll={new_settings.poll_interval:g}s dry_run={new_settings.dry_run}"
    )


from . import commands as _commands  # noqa: E402,F401  (registers handlers)
