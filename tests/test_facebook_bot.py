"""
Tests for skills/facebook_bot.py
Run: python3 -m pytest tests/test_facebook_bot.py -v
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from skills import facebook_bot


@pytest.fixture(autouse=True)
def isolate_schedule_file(tmp_path, monkeypatch):
    fake_schedule = tmp_path / "facebook_schedule.json"
    monkeypatch.setattr("skills.facebook_bot.SCHEDULE_FILE", fake_schedule)
    return fake_schedule


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = cls(2026, 4, 3, 9, 0, 0, tzinfo=timezone.utc)
        if tz is None:
            return fixed.replace(tzinfo=None)
        return fixed.astimezone(tz)


def test_recorded_queue_post_blocks_fresh_generation_same_day():
    date_key = "2026-04-03"

    assert facebook_bot.record_posted_date(date_key) is True
    assert facebook_bot.was_posted_on(date_key) is True

    with patch("skills.facebook_bot.datetime", FixedDateTime), \
         patch("skills.facebook_bot._claude", side_effect=AssertionError("should not generate")):
        facebook_bot.post_scheduled_content({"FB_PAGE_ACCESS_TOKEN": "", "FB_PAGE_ID": ""})


def test_record_posted_date_is_idempotent():
    date_key = "2026-04-03"

    assert facebook_bot.record_posted_date(date_key) is True
    assert facebook_bot.record_posted_date(date_key) is False

    schedule = facebook_bot._load_schedule()
    assert schedule["posted_dates"] == [date_key]
