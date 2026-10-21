#!/usr/bin/env python3
"""Read-only probe for the XMU cyber-range public CTF scoreboard.

This script only performs GET requests against the public screen API.
It does not log in, submit flags, or modify any data.

Usage:
    python3 probe_ctf_rank.py --race <RACE_ID> --viewer-key <KEY>
    python3 probe_ctf_rank.py --race <RACE_ID> --viewer-key <KEY> --details
    python3 probe_ctf_rank.py --race <RACE_ID> --viewer-key <KEY> --json > snapshot.json

Environment fallbacks:
    CTF_BASE_URL, CTF_RACE_ID, CTF_VIEWER_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def http_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "ctf-rank-probe/0.1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:200]!r}") from exc
        raise RuntimeError(
            f"HTTP {exc.code}: {payload.get('code')} {payload.get('message')}"
        ) from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON response from {url}: {body[:200]!r}") from exc


def api(base: str, path: str, **params: str) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    url = f"{base.rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"
    payload = http_json(url)
    if payload.get("code") != "AD-000000":
        raise RuntimeError(f"API error: {payload.get('code')} {payload.get('message')}")
    return payload.get("data") or {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.getenv("CTF_BASE_URL", "http://127.0.0.1"))
    parser.add_argument("--race", default=os.getenv("CTF_RACE_ID", ""))
    parser.add_argument("--viewer-key", default=os.getenv("CTF_VIEWER_KEY", ""))
    parser.add_argument("--details", action="store_true", help="also fetch per-team solve timelines")
    parser.add_argument("--json", action="store_true", help="dump raw snapshot instead of a summary")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    if not args.race or not args.viewer_key:
        parser.error("--race and --viewer-key are required (or set CTF_RACE_ID / CTF_VIEWER_KEY)")

    base_info = api(
        args.base,
        f"/api/ct/public/jeopardy_race/race/{args.race}/base/",
        viewer_key=args.viewer_key,
    )
    rank = api(
        args.base,
        f"/api/ct/public/jeopardy_race/race/{args.race}/rank/",
        page="1",
        per_page="1000",
        viewer_key=args.viewer_key,
    )

    if args.json:
        json.dump({"base": base_info, "rank": rank}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    challenges = rank.get("checker_detail") or []
    teams = rank.get("rank_detail") or []
    print(f"赛事: {base_info.get('race_name')}")
    print(f"时间: {base_info.get('start_time')} — {base_info.get('end_time')}")
    print(f"队伍: {len(teams)}  题目: {len(challenges)}  血奖模式: {rank.get('reward_mode')}")
    print()

    if teams and len(teams[0].get("checker_score") or []) != len(challenges):
        print("WARN: checker_score length != checker_detail length; schema may have changed", file=sys.stderr)
        return 2

    bloods: list[tuple[str, str, int, str, str]] = []  # (challenge, direction, blood, team, team_id)
    total_solved = 0
    for idx, challenge in enumerate(challenges):
        solvers = []
        for team in teams:
            cell = (team.get("checker_score") or [])[idx]
            if cell.get("is_solved"):
                total_solved += 1
                solvers.append((cell.get("rank", 0), team.get("name"), team.get("resource_id")))
        solvers.sort(key=lambda x: (x[0] == 0, x[0]))
        top = [s for s in solvers if 1 <= s[0] <= 3]
        for rank_no, name, team_id in top:
            bloods.append((challenge.get("name", "?"), challenge.get("direction", "?"), rank_no, name or "?", team_id or ""))
        if top:
            label = {1: "一血", 2: "二血", 3: "三血"}
            cells = "  ".join(f"{label[r]}:{n}" for r, n, _ in top)
            print(f"[{challenge.get('direction')}] {challenge.get('name')} (score={challenge.get('score')})  {cells}")

    print()
    print(f"已解出记录: {total_solved}  血事件: {len(bloods)}")

    if args.details and bloods:
        print()
        print("精确解题时间（按需拉取）:")
        cache: dict[str, list[dict[str, Any]]] = {}
        for challenge_name, direction, blood, team_name, team_id in bloods:
            if team_id not in cache:
                data = api(
                    args.base,
                    f"/api/ct/public/jeopardy_race/race/{args.race}/rank/{team_id}/",
                    viewer_key=args.viewer_key,
                )
                cache[team_id] = data if isinstance(data, list) else []
            record = next(
                (x for x in cache[team_id] if (x.get("checkpoint") or {}).get("name") == challenge_name),
                None,
            )
            when = record.get("create_time") if record else "?"
            score = record.get("score") if record else "?"
            print(f"  {blood}血 [{direction}] {challenge_name} - {team_name} @ {when} (score={score})")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
