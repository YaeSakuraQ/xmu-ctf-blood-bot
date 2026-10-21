"""The scheduled new-challenge notice for the 2026 XMU freshman contest."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .notifier import Notifier
from .store import Store

logger = logging.getLogger(__name__)

SHANGHAI = ZoneInfo("Asia/Shanghai")
START = datetime(2026, 10, 24, 13, 30, tzinfo=SHANGHAI)
END = datetime(2026, 10, 24, 16, 30, tzinfo=SHANGHAI)
RACE_ID = "c31c2221ce8a052461d3600ebbb32ff5"
META_KEY = "notice:2026-10-24-1330-new-challenges"

MESSAGE = """【新题上线通知】
10 月 24 日 13:30，以下 14 道题目已加入比赛，请刷新题目列表查看：

Crypto（2）：Echo Key、RmStA
Misc（3）：Song of Symbols、ezWord、ezQrcode
Pwn（3）：fakecalc、Misprinted Label、gifts
Reverse（3）：Folded Echo、DNA、The Number Cabinet
Web（3）：morefile、Login Ledger、The Secret Parcel

祝大家比赛顺利！"""


async def send_new_challenges_notice(
    *,
    race_id: str,
    store: Store,
    notifier: Notifier,
    dry_run: bool,
    now: datetime | None = None,
) -> bool:
    """Send once during the contest, retrying on later ticks if delivery fails."""

    now = now or datetime.now(SHANGHAI)
    if race_id != RACE_ID or dry_run or not START <= now < END:
        return False
    if store.get_meta(META_KEY) == "sent":
        return False

    try:
        await notifier.send(MESSAGE)
    except Exception as exc:  # noqa: BLE001 - next scheduler tick retries
        logger.warning("新题通知发送失败，稍后重试: %s", exc)
        return False

    store.set_meta(META_KEY, "sent")
    logger.info("已发送 10 月 24 日 13:30 新题通知")
    return True
