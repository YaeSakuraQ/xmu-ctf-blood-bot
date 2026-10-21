from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ctfblood.announcement import MESSAGE, META_KEY, RACE_ID, send_new_challenges_notice
from ctfblood.store import Store


class FakeNotifier:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        if self.fail:
            raise RuntimeError("QQ disconnected")
        self.sent.append(message)


@pytest.mark.asyncio
async def test_new_challenge_notice_is_timed_and_persistent(tmp_path):
    db_path = tmp_path / "notice.sqlite3"
    store = Store(str(db_path))
    notifier = FakeNotifier()
    tz = ZoneInfo("Asia/Shanghai")

    async def tick(hour, minute, *, race_id=RACE_ID, dry_run=False):
        return await send_new_challenges_notice(
            race_id=race_id,
            store=store,
            notifier=notifier,
            dry_run=dry_run,
            now=datetime(2026, 10, 24, hour, minute, tzinfo=tz),
        )

    try:
        assert await tick(13, 29) is False
        assert await tick(13, 30, race_id="other-race") is False
        assert await tick(13, 30, dry_run=True) is False
        notifier.fail = True
        assert await tick(13, 30) is False
        assert store.get_meta(META_KEY) == ""

        notifier.fail = False
        assert await tick(13, 31) is True
        assert notifier.sent == [MESSAGE]
        assert await tick(13, 32) is False
    finally:
        store.close()

    reopened = Store(str(db_path))
    try:
        assert await send_new_challenges_notice(
            race_id=RACE_ID,
            store=reopened,
            notifier=notifier,
            dry_run=False,
            now=datetime(2026, 10, 24, 14, 0, tzinfo=tz),
        ) is False
        assert notifier.sent == [MESSAGE]
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_new_challenge_notice_expires_after_contest(tmp_path):
    store = Store(str(tmp_path / "notice.sqlite3"))
    notifier = FakeNotifier()
    try:
        assert await send_new_challenges_notice(
            race_id=RACE_ID,
            store=store,
            notifier=notifier,
            dry_run=False,
            now=datetime(2026, 10, 24, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        ) is False
        assert notifier.sent == []
    finally:
        store.close()
