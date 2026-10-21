from __future__ import annotations

from dataclasses import replace

from ctfblood.messages import (
    format_blood_table,
    format_digest,
    format_event,
    format_rank,
    format_status,
    safe_text,
)

from .conftest import make_cell, make_challenge, make_snapshot, make_team


def test_format_event(event) -> None:
    text = format_event(event)
    assert "🏆 一血" in text
    assert "Web · easysql" in text
    assert "队伍：A队" in text
    assert "时间：10:42:13" in text
    assert "得分：105" in text


def test_format_catchup_and_approximate_time(event) -> None:
    text = format_event(replace(event, catchup=True, time_exact=False))
    assert "（补报）" in text
    assert "约 10:42:13" in text


def test_safe_text_strips_control_and_truncates() -> None:
    assert safe_text("A\nB", 10) == "A B"
    assert safe_text("x" * 50, 10).endswith("…")
    assert len(safe_text("x" * 50, 10)) == 10
    assert safe_text("", 10) == "未知"


def test_format_rank_order() -> None:
    challenge = make_challenge()
    teams = (
        make_team("t1", "A队", (make_cell(1, True),), score=100),
        make_team("t2", "B队", (make_cell(0, False),), score=300),
    )
    snapshot = make_snapshot((challenge,), teams)
    text = format_rank(snapshot, limit=2)
    assert "1. B队  300 分 / 0 题" in text
    assert "2. A队  100 分 / 1 题" in text


def test_format_blood_table() -> None:
    challenge = make_challenge()
    teams = (
        make_team("t1", "A队", (make_cell(1, True),)),
        make_team("t2", "B队", (make_cell(2, True),)),
    )
    snapshot = make_snapshot((challenge,), teams)
    from ctfblood.detector import blood_table

    text = format_blood_table(blood_table(snapshot))
    assert "Web · easysql" in text
    assert "一血 A队" in text
    assert "二血 B队" in text


def test_format_status() -> None:
    text = format_status(
        race_name="新生赛",
        race_id="r1",
        poll_interval=2,
        send_interval=1,
        counts={"sent": 3, "pending": 1, "failed": 0},
        last_poll="10:00:00",
        last_error=None,
        bot_ready=True,
    )
    assert "赛事：新生赛" in text
    assert "已发送：3  待发送：1  失败：0" in text
    assert "Bot：已连接" in text


def test_format_digest(event) -> None:
    text = format_digest([event, replace(event, blood=2, team_name="B队")])
    assert text.startswith("【血报 · 10:42:13】")
    assert "一血" in text and "二血" in text
    assert "B队" in text
