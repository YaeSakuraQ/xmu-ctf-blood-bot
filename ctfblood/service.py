"""Polling, blood detection, persistence and rate-limited sending."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

from .api import CTFClient
from .config import Settings
from .detector import find_candidates, validate_snapshot
from .messages import format_event, format_status
from .models import BloodEvent, Candidate, Snapshot
from .notifier import Notifier
from .store import Store

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _after(seconds: float) -> str:
    return (datetime.now() + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


class BloodService:
    def __init__(
        self,
        settings: Settings,
        client: CTFClient,
        store: Store,
        notifier: Notifier,
        *,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.settings = settings
        self.client = client
        self.store = store
        self.notifier = notifier
        self._clock = clock
        self.last_poll_at: str | None = None
        self.last_error: str = ""
        self._warned: set[str] = set()

    # ------------------------------------------------------------------ setup
    async def load_race_info(self) -> None:
        try:
            base = await self.client.fetch_base()
        except Exception as exc:  # noqa: BLE001 - startup information is best-effort
            logger.warning("读取赛事基础信息失败: %s", exc)
            return
        race_id = self.settings.race_id
        name = str(base.get("race_name") or "")
        if name:
            self.store.set_meta(f"race_name:{race_id}", name)
        for key in ("start_time", "end_time"):
            value = str(base.get(key) or "")
            if value:
                self.store.set_meta(f"{key}:{race_id}", value)

    async def close(self) -> None:
        await self.client.close()
        self.store.close()

    # ------------------------------------------------------------------- poll
    async def poll_once(self) -> int:
        snapshot = await self.client.fetch_snapshot()
        now = self._clock()
        self.last_poll_at = now
        self.last_error = ""
        self._log_warnings(snapshot)

        if snapshot.reward_mode != 1:
            return 0

        state = self.store.get_state(self.settings.race_id)
        fingerprint = snapshot.fingerprint

        if state and state.get("fingerprint") and state["fingerprint"] != fingerprint:
            logger.warning(
                "题目顺序/数量发生变化，跳过本轮以重建基线（%s -> %s）",
                str(state["fingerprint"])[:8],
                fingerprint[:8],
            )
            self.store.set_state(
                self.settings.race_id,
                fingerprint=fingerprint,
                total_score=snapshot.total_score,
                total_solved=snapshot.total_solved,
                drop_streak=0,
                last_poll_at=now,
            )
            return 0

        initialized = self.store.get_meta(f"initialized:{self.settings.race_id}") == "1"
        if not initialized:
            return await self._first_poll(snapshot, now)

        streak = self._drop_streak(snapshot, state)
        if streak >= 2:
            await self._handle_reset(snapshot)
            return 0

        announced = self.store.announced_keys(self.settings.race_id)
        candidates = find_candidates(snapshot, announced, self.settings.blood_levels)
        added = 0
        for candidate in candidates:
            event = await self._build_event(candidate, catchup=False)
            if self.store.add(event):
                added += 1
                logger.info(
                    "发现新血: %s血 %s/%s by %s",
                    candidate.blood,
                    candidate.challenge.direction,
                    candidate.challenge.name,
                    candidate.team.name,
                )

        # While a drop is pending confirmation, keep the previous baseline so
        # the second poll still compares against the pre-drop score.
        baseline_score = snapshot.total_score
        baseline_solved = snapshot.total_solved
        if streak and state:
            baseline_score = int(state.get("total_score") or 0)
            baseline_solved = int(state.get("total_solved") or 0)

        self.store.set_state(
            self.settings.race_id,
            fingerprint=fingerprint,
            total_score=baseline_score,
            total_solved=baseline_solved,
            drop_streak=streak,
            last_poll_at=now,
        )
        return added

    async def _first_poll(self, snapshot: Snapshot, now: str) -> int:
        """Initialise a race, optionally back-filling bloods already on screen."""

        race_id = self.settings.race_id
        candidates = find_candidates(snapshot, set(), self.settings.blood_levels)
        catchup = self.settings.catchup_mode == "announce"

        if candidates and catchup:
            for candidate in candidates:
                event = await self._build_event(candidate, catchup=True)
                self.store.add(event)
            logger.info("首次轮询：补报 %d 条已有血事件", len(candidates))
        else:
            for candidate in candidates:
                event = BloodEvent(
                    race_id=race_id,
                    challenge_id=candidate.challenge.challenge_id,
                    challenge_name=candidate.challenge.name,
                    direction=candidate.challenge.direction,
                    blood=candidate.blood,
                    team_id=candidate.team.team_id,
                    team_name=candidate.team.name,
                    solve_time=None,
                    score=candidate.challenge.score,
                    time_exact=False,
                    catchup=False,
                    detected_at=now,
                )
                self.store.add(event, status="sent", catchup=False, message="[baseline]", now=now)
            if candidates:
                logger.info("首次轮询：静默基线 %d 条已有血事件", len(candidates))

        self.store.set_meta(f"initialized:{race_id}", "1")
        self.store.set_state(
            race_id,
            fingerprint=snapshot.fingerprint,
            total_score=snapshot.total_score,
            total_solved=snapshot.total_solved,
            drop_streak=0,
            last_poll_at=now,
        )
        return 0

    async def _handle_reset(self, snapshot: Snapshot) -> None:
        logger.warning("检测到赛事数据重置，清空播报状态并重新基线")
        self.store.clear_race(self.settings.race_id)
        text = "【CTF播报】检测到赛事数据重置，已清空播报状态并重新基线。"
        try:
            await self.notifier.send(text)
        except Exception as exc:  # noqa: BLE001 - a notice failure must not stop polling
            logger.warning("发送重置公告失败: %s", exc)

    def _drop_streak(self, snapshot: Snapshot, state: dict[str, object] | None) -> int:
        if not state:
            return 0
        previous_score = int(state.get("total_score") or 0)
        previous_solved = int(state.get("total_solved") or 0)
        dropped = (
            (previous_score > 0 and snapshot.total_score < previous_score * 0.5)
            or (previous_solved > 0 and snapshot.total_solved < previous_solved * 0.5)
        )
        if dropped:
            return int(state.get("drop_streak") or 0) + 1
        return 0

    async def _build_event(self, candidate: Candidate, *, catchup: bool) -> BloodEvent:
        solve = None
        try:
            solve = await self.client.fetch_solve(
                candidate.team.team_id,
                candidate.challenge.challenge_id,
            )
        except Exception as exc:  # noqa: BLE001 - announcement still has value with approximate time
            logger.warning("读取单队解题时间失败，使用检测时间: %s", exc)

        return BloodEvent(
            race_id=self.settings.race_id,
            challenge_id=candidate.challenge.challenge_id,
            challenge_name=candidate.challenge.name,
            direction=candidate.challenge.direction,
            blood=candidate.blood,
            team_id=candidate.team.team_id,
            team_name=candidate.team.name,
            solve_time=solve.create_time if solve else None,
            score=solve.score if solve else candidate.challenge.score,
            time_exact=solve is not None,
            catchup=catchup,
        )

    # ------------------------------------------------------------------- send
    async def send_once(self) -> bool:
        row = self.store.next_pending(self.settings.race_id)
        if row is None:
            return False

        text = format_event(row.to_event())
        try:
            await self.notifier.send(text)
        except Exception as exc:  # noqa: BLE001 - retry with backoff
            attempts = row.attempts + 1
            delay = min(2**attempts, 60)
            status = self.store.mark_failed(
                (row.race_id, row.challenge_id, row.blood),
                str(exc),
                next_attempt_at=_after(delay),
                max_attempts=self.settings.max_send_attempts,
            )
            logger.warning(
                "发送失败（%s，第 %d 次，%.0fs 后重试）: %s",
                status,
                attempts,
                delay,
                exc,
            )
            if status == "failed" and self.settings.send_admin_errors:
                try:
                    await self.notifier.send_admin(
                        f"CTF播报发送失败：{row.challenge_name} {row.blood}血 {row.team_name}\n{exc}"
                    )
                except Exception:  # noqa: BLE001 - admin notice is best-effort
                    pass
            return False

        self.store.mark_sent((row.race_id, row.challenge_id, row.blood), text)
        logger.info("已发送: %s血 %s/%s by %s", row.blood, row.direction, row.challenge_name, row.team_name)
        return True

    # --------------------------------------------------------------- scheduler
    async def poll_job(self) -> None:
        try:
            await self.poll_once()
        except Exception as exc:  # noqa: BLE001 - APScheduler must keep the job alive
            self.last_error = str(exc)
            logger.warning("轮询失败: %s", exc)
            logger.debug("轮询异常详情", exc_info=True)

    async def send_job(self) -> None:
        try:
            await self.send_once()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            logger.warning("发送任务失败: %s", exc)
            logger.debug("发送异常详情", exc_info=True)

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        """Standalone loop used by the CLI; NoneBot uses the two jobs above."""

        stop = stop or asyncio.Event()
        await self.load_race_info()
        while not stop.is_set():
            await self.poll_job()
            while await self.send_once():
                await asyncio.sleep(self.settings.send_interval)
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.settings.poll_interval)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------ status
    def status_text(self, *, bot_ready: bool) -> str:
        race_id = self.settings.race_id
        race_name = (
            self.settings.race_name
            or self.store.get_meta(f"race_name:{race_id}")
            or "未获取"
        )
        return format_status(
            race_name=race_name,
            race_id=race_id,
            poll_interval=self.settings.poll_interval,
            send_interval=self.settings.send_interval,
            counts=self.store.counts(race_id),
            last_poll=self.last_poll_at,
            last_error=self.last_error or None,
            bot_ready=bot_ready,
        )

    def _log_warnings(self, snapshot: Snapshot) -> None:
        for warning in validate_snapshot(snapshot):
            if warning not in self._warned:
                self._warned.add(warning)
                logger.warning("榜单自检: %s", warning)
