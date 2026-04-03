"""
Tests for skills/marketing_bot.py
Run: python3 -m pytest tests/test_marketing_bot.py -v
"""

import sys
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from skills import marketing_bot


class FixedThursday(datetime):
    @classmethod
    def now(cls, tz=None):
        dt = cls(2026, 4, 2, 12, 0, 0, tzinfo=timezone.utc)
        return dt if tz else dt.replace(tzinfo=None)


class FixedMonday(datetime):
    @classmethod
    def now(cls, tz=None):
        dt = cls(2026, 3, 30, 9, 0, 0, tzinfo=timezone.utc)
        return dt if tz else dt.replace(tzinfo=None)


def test_campaign_week_derives_from_start_not_stored_value(monkeypatch):
    strategy = {
        "campaign_start": "2026-03-15T09:49:57.561005+00:00",
        "campaign_week": 2,
    }
    monkeypatch.setattr(marketing_bot, "datetime", FixedThursday)
    assert marketing_bot._campaign_week(strategy) == 3


def test_get_current_arc_guidance_returns_derived_week(monkeypatch):
    strategy = {
        "campaign_start": "2026-03-15T09:49:57.561005+00:00",
        "campaign_week": 2,
        "arc_phase_index": 0,
        "funnel": {},
    }
    monkeypatch.setattr(marketing_bot, "datetime", FixedThursday)
    monkeypatch.setattr(marketing_bot, "_load_strategy", lambda: strategy)

    guidance = marketing_bot.get_current_arc_guidance()

    assert guidance["week"] == 3
    assert guidance["theme"] == "Why Everything Else Failed"


def test_send_weekly_strategy_uses_derived_week_and_real_funnel_rates(monkeypatch):
    strategy = {
        "campaign_start": "2026-03-15T09:49:57.561005+00:00",
        "campaign_week": 2,
        "arc_phase_index": 0,
        "funnel": {
            "impressions": 1000,
            "clicks": 100,
            "quiz_starts": 0,
            "diagnosed": 50,
            "paid": 25,
            "retained_week4": 10,
        },
        "flags_sent": [],
    }
    captured = {}

    monkeypatch.setattr(marketing_bot, "datetime", FixedMonday)
    monkeypatch.setattr(marketing_bot, "_load_strategy", lambda: strategy)
    monkeypatch.setattr(marketing_bot, "_save_strategy", lambda s: None)
    monkeypatch.setattr(marketing_bot, "update_funnel_from_state", lambda state, strat: None)
    monkeypatch.setattr(marketing_bot, "update_funnel_from_fb", lambda secrets, strat: None)
    monkeypatch.setattr(marketing_bot, "generate_copy", lambda format, usp_id=None, secrets=None: f"{usp_id or 'default'}-{format}")

    def fake_render_internal_email(title, subtitle, sections):
        captured["subtitle"] = subtitle
        captured["sections"] = sections
        return "<html>weekly strategy</html>"

    def fake_send_email(secrets, to, subject, plain_body, html_body):
        captured["subject"] = subject
        captured["plain_body"] = plain_body
        captured["html_body"] = html_body

    fake_pipeline = types.ModuleType("scripts.battleship_pipeline")
    fake_pipeline.render_internal_email = fake_render_internal_email
    fake_pipeline.send_email = fake_send_email
    monkeypatch.setitem(sys.modules, "scripts.battleship_pipeline", fake_pipeline)

    marketing_bot.send_weekly_strategy(secrets={}, state={"clients": {}})

    assert "Campaign week 3" in captured["plain_body"]
    assert "1000 impressions → 100 clicks → 50 quiz → 25 paid → 10 retained" in captured["plain_body"]
    assert "CTR: 10.0% | Click → quiz: 50.0% | Quiz → paid: 50.0% | Paid retention: 40.0%" in captured["plain_body"]
    assert captured["subtitle"] == "Campaign Week 3"
