"""Command-line helpers for local testing.

The production path is the NoneBot plugin; this CLI exists so the polling and
detection logic can be exercised without QQ/NapCat:

    python -m ctfblood.cli probe --race <id> --viewer-key <key>
    python -m ctfblood.cli once
    python -m ctfblood.cli run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from .api import CTFClient
from .config import Settings, load_settings
from .detector import blood_table
from .messages import BLOOD_LABEL, safe_text
from .notifier import DryRunNotifier
from .service import BloodService
from .store import Store

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # httpx logs the full URL at INFO, including viewer_key.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def _probe(settings: Settings, limit: int) -> int:
    client = CTFClient(settings)
    try:
        base = await client.fetch_base()
        snapshot = await client.fetch_snapshot()
    finally:
        await client.close()

    print(f"赛事: {base.get('race_name') or settings.race_id}")
    print(f"时间: {base.get('start_time')} — {base.get('end_time')}")
    print(
        f"队伍: {len(snapshot.teams)}  题目: {len(snapshot.challenges)}  "
        f"血奖模式: {snapshot.reward_mode}"
    )

    table = blood_table(snapshot)
    if not table:
        print("\n当前没有血。")
        return 0

    print(f"\n血况（最多 {limit} 题）:")
    client = CTFClient(settings)
    cache: dict[str, dict[str, str]] = {}
    try:
        for challenge, winners in table[:limit]:
            print(f"[{challenge.direction}] {challenge.name} (score={challenge.score})")
            for blood, team in winners:
                if team.team_id not in cache:
                    records = await client.fetch_team_solves(team.team_id)
                    cache[team.team_id] = {record.challenge_id: record.create_time for record in records}
                when = cache[team.team_id].get(challenge.challenge_id, "?")
                print(f"  {BLOOD_LABEL.get(blood, blood)} {safe_text(team.name, 30)} @ {when}")
    finally:
        await client.close()
    return 0


async def _once(settings: Settings) -> int:
    client = CTFClient(settings)
    store = Store(settings.db_path)
    notifier = DryRunNotifier()
    service = BloodService(settings, client, store, notifier)
    try:
        await service.load_race_info()
        found = await service.poll_once()
        sent = 0
        while await service.send_once():
            sent += 1
        counts = store.counts(settings.race_id)
        print(
            f"本轮发现 {found} 条，发送 {sent} 条；"
            f"累计 sent={counts.get('sent', 0)} pending={counts.get('pending', 0)} "
            f"failed={counts.get('failed', 0)}"
        )
    finally:
        await service.close()
    return 0


async def _run(settings: Settings) -> int:
    client = CTFClient(settings)
    store = Store(settings.db_path)
    service = BloodService(settings, client, store, DryRunNotifier())
    try:
        await service.run_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        await service.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ctfblood.cli", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="只读打印当前血况")
    probe.add_argument("--base", default=os.getenv("CTF_BASE_URL", ""))
    probe.add_argument("--race", default=os.getenv("CTF_RACE_ID", ""))
    probe.add_argument("--viewer-key", default=os.getenv("CTF_VIEWER_KEY", ""))
    probe.add_argument("--limit", type=int, default=10)

    sub.add_parser("once", help="跑一轮检测+打印（dry-run）")
    sub.add_parser("run", help="持续轮询（dry-run）")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "probe":
        missing = [name for name, value in (
            ("--base", args.base), ("--race", args.race), ("--viewer-key", args.viewer_key)
        ) if not value]
        if missing:
            parser.error(f"缺少参数: {', '.join(missing)}")
        settings = Settings(
            base_url=args.base.rstrip("/"),
            race_id=args.race,
            viewer_key=args.viewer_key,
            group_id=1,
            race_name="",
        )
        return asyncio.run(_probe(settings, args.limit))

    settings = load_settings()
    if args.command == "once":
        return asyncio.run(_once(settings))
    return asyncio.run(_run(settings))


if __name__ == "__main__":
    sys.exit(main())
