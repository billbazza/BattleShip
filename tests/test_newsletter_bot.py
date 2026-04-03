"""
Tests for skills/newsletter_bot.py
Run: python3 -m pytest tests/test_newsletter_bot.py -v
"""

import json
import sys
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
from skills.newsletter_bot import (
    _load_state,
    _save_state,
    _should_send_today,
    _generate_issue,
    _get_subscriber_count,
    _create_and_send_post,
    DEFAULT_AFFILIATE_SLOTS,
    INSIGHT_THEMES,
    STATE_FILE,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_state_file(tmp_path, monkeypatch):
    """Redirect STATE_FILE to a temp file so tests don't touch real state."""
    fake_state = tmp_path / "newsletter_state.json"
    monkeypatch.setattr("skills.newsletter_bot.STATE_FILE", fake_state)
    return fake_state


@pytest.fixture
def blank_state():
    return {
        "last_send_date":   None,
        "issue_number":     0,
        "subscriber_count": 0,
        "issues":           [],
        "affiliate_slots":  DEFAULT_AFFILIATE_SLOTS,
        "theme_index":      0,
    }


@pytest.fixture
def fake_secrets():
    return {
        "ANTHROPIC_API_KEY":        "sk-test-key",
        "BEEHIIV_API_KEY":          "bh-test-key",
        "BEEHIIV_PUBLICATION_ID":   "pub_test123",
    }


# ── State ──────────────────────────────────────────────────────────────────────

class TestStateManagement:
    def test_load_state_missing_file_returns_defaults(self):
        state = _load_state()
        assert state["issue_number"] == 0
        assert state["subscriber_count"] == 0
        assert state["issues"] == []
        assert len(state["affiliate_slots"]) == 3

    def test_save_and_reload_state(self, blank_state):
        blank_state["issue_number"] = 7
        blank_state["subscriber_count"] = 342
        _save_state(blank_state)
        reloaded = _load_state()
        assert reloaded["issue_number"] == 7
        assert reloaded["subscriber_count"] == 342

    def test_corrupt_state_file_returns_defaults(self, isolate_state_file):
        isolate_state_file.write_text("not valid json {{{{")
        state = _load_state()
        assert state["issue_number"] == 0


# ── Schedule ───────────────────────────────────────────────────────────────────

class TestSchedule:
    def test_should_send_on_tuesday(self, blank_state):
        # Find a Tuesday
        today = datetime.now(timezone.utc)
        days_to_tuesday = (1 - today.weekday()) % 7
        tuesday = today + timedelta(days=days_to_tuesday)
        with patch("skills.newsletter_bot.datetime") as mock_dt:
            mock_dt.now.return_value = tuesday
            mock_dt.fromisoformat = datetime.fromisoformat
            assert _should_send_today(blank_state) is True

    def test_should_not_send_on_non_tuesday(self, blank_state):
        # Find a Wednesday
        today = datetime.now(timezone.utc)
        days_to_wednesday = (2 - today.weekday()) % 7
        wednesday = today + timedelta(days=days_to_wednesday)
        with patch("skills.newsletter_bot.datetime") as mock_dt:
            mock_dt.now.return_value = wednesday
            mock_dt.fromisoformat = datetime.fromisoformat
            assert _should_send_today(blank_state) is False

    def test_should_not_send_if_already_sent_today(self, blank_state):
        today = datetime.now(timezone.utc)
        days_to_tuesday = (1 - today.weekday()) % 7
        tuesday = today + timedelta(days=days_to_tuesday)
        blank_state["last_send_date"] = tuesday.strftime("%Y-%m-%d")
        with patch("skills.newsletter_bot.datetime") as mock_dt:
            mock_dt.now.return_value = tuesday
            mock_dt.fromisoformat = datetime.fromisoformat
            assert _should_send_today(blank_state) is False


# ── Content generation ─────────────────────────────────────────────────────────

class TestContentGeneration:
    def _mock_claude_response(self, content: str):
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=content)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        return mock_client

    def test_generate_issue_returns_subject_preview_html(self, fake_secrets):
        valid_json = json.dumps({
            "subject":       "How compound systems beat single big bets",
            "preview":       "The maths most operators never run",
            "insight_title": "Small streams, permanent infrastructure",
            "insight_body":  "First paragraph.\n\nSecond paragraph.",
            "build_log":     "Shipped the newsletter bot this week. First dry run.",
            "cta_text":      "If you're rebuilding your body alongside the business: battleshipreset.com",
        })
        mock_client = self._mock_claude_response(valid_json)

        with patch("skills.newsletter_bot.anthropic.Anthropic", return_value=mock_client):
            subject, preview, html, fb_post = _generate_issue(
                issue_number=1,
                theme=INSIGHT_THEMES[0],
                affiliate_slots=DEFAULT_AFFILIATE_SLOTS,
                secrets=fake_secrets,
            )

        assert subject == "How compound systems beat single big bets"
        assert preview == "The maths most operators never run"
        assert "Small streams, permanent infrastructure" in html
        assert "First paragraph." in html
        assert "battleshipreset.com" in html
        assert "The Operator" in html

    def test_generate_issue_includes_all_affiliate_slots(self, fake_secrets):
        valid_json = json.dumps({
            "subject":       "Test subject",
            "preview":       "Test preview",
            "insight_title": "Test insight",
            "insight_body":  "Body text.",
            "build_log":     "Build log text.",
            "cta_text":      "CTA text.",
        })
        mock_client = self._mock_claude_response(valid_json)

        with patch("skills.newsletter_bot.anthropic.Anthropic", return_value=mock_client):
            _, _, html, _ = _generate_issue(1, INSIGHT_THEMES[0],
                                             DEFAULT_AFFILIATE_SLOTS, fake_secrets)

        for slot in DEFAULT_AFFILIATE_SLOTS:
            assert slot["url"] in html

    def test_generate_issue_strips_markdown_fences(self, fake_secrets):
        valid_json = json.dumps({
            "subject": "Subject", "preview": "Preview",
            "insight_title": "Title", "insight_body": "Body.",
            "build_log": "Log.", "cta_text": "CTA.",
        })
        fenced = f"```json\n{valid_json}\n```"
        mock_client = self._mock_claude_response(fenced)

        with patch("skills.newsletter_bot.anthropic.Anthropic", return_value=mock_client):
            subject, _, _, _ = _generate_issue(1, INSIGHT_THEMES[0],
                                                DEFAULT_AFFILIATE_SLOTS, fake_secrets)
        assert subject == "Subject"

    def test_generate_issue_raises_on_invalid_json(self, fake_secrets):
        mock_client = self._mock_claude_response("this is not json at all")
        with patch("skills.newsletter_bot.anthropic.Anthropic", return_value=mock_client):
            with pytest.raises(json.JSONDecodeError):
                _generate_issue(1, INSIGHT_THEMES[0],
                                 DEFAULT_AFFILIATE_SLOTS, fake_secrets)


# ── Beehiiv API ───────────────────────────────────────────────────────────────

class TestBeehiivAPI:
    def test_get_subscriber_count_no_credentials_returns_zero(self):
        assert _get_subscriber_count({}) == 0

    def test_get_subscriber_count_parses_response(self, fake_secrets):
        mock_response = MagicMock()
        mock_response.json.return_value = {"total_results": 487}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            count = _get_subscriber_count(fake_secrets)
        assert count == 487

    def test_get_subscriber_count_handles_http_error(self, fake_secrets):
        import httpx
        with patch("httpx.get", side_effect=httpx.HTTPError("500")):
            count = _get_subscriber_count(fake_secrets)
        assert count == 0

    def test_create_and_send_dry_run_saves_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("skills.newsletter_bot.VAULT_ROOT", tmp_path)
        (tmp_path / "logs").mkdir()
        post_id = _create_and_send_post(
            subject="Test subject",
            html_body="<p>Test body</p>",
            secrets={},
            dry_run=True,
        )
        assert post_id == "dry_run_post_id"
        saved = tmp_path / "logs" / "newsletter_dry_run.html"
        assert saved.exists()
        assert "Test subject" in saved.read_text()
        assert "Test body" in saved.read_text()

    def test_create_and_send_stages_to_db(self, fake_secrets):
        """Non-dry-run mode stages to dashboard DB queue and returns an eq_ id."""
        result = _create_and_send_post("Subject", "<p>Body</p>", fake_secrets, dry_run=False)
        assert result is not None
        assert result.startswith("eq_")

    def test_create_and_send_returns_none_on_db_failure(self, fake_secrets):
        """Returns None if DB staging throws."""
        with patch("scripts.db.insert_email", side_effect=Exception("DB down")):
            result = _create_and_send_post("Subject", "<p>Body</p>", fake_secrets, dry_run=False)
        assert result is None

    def test_send_to_beehiiv_posts_and_returns_post_id(self, fake_secrets):
        """send_to_beehiiv() publishes directly to Beehiiv and returns post_id."""
        from skills.newsletter_bot import send_to_beehiiv
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"id": "post_abc123"}}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response):
            post_id = send_to_beehiiv("Subject", "<p>Body</p>", fake_secrets)
        assert post_id == "post_abc123"

    def test_send_to_beehiiv_no_pub_id_returns_none(self, fake_secrets):
        secrets = {k: v for k, v in fake_secrets.items()
                   if k != "BEEHIIV_PUBLICATION_ID"}
        from skills.newsletter_bot import send_to_beehiiv
        result = send_to_beehiiv("Subject", "<p>Body</p>", secrets)
        assert result is None


# ── Full run (integration-style) ───────────────────────────────────────────────

class TestRun:
    def test_run_skips_on_non_tuesday(self, fake_secrets, capsys):
        from skills.newsletter_bot import run

        today = datetime.now(timezone.utc)
        days_to_wednesday = (2 - today.weekday()) % 7
        wednesday = today + timedelta(days=days_to_wednesday)

        with patch("skills.newsletter_bot.datetime") as mock_dt:
            mock_dt.now.return_value = wednesday
            mock_dt.fromisoformat = datetime.fromisoformat
            with patch("skills.newsletter_bot._get_subscriber_count", return_value=0):
                run(fake_secrets)

        out = capsys.readouterr().out
        assert "Newsletter sends Tuesdays" in out

    def test_run_dry_run_saves_file_and_updates_state(self, fake_secrets,
                                                       tmp_path, monkeypatch):
        from skills.newsletter_bot import run

        monkeypatch.setattr("skills.newsletter_bot.VAULT_ROOT", tmp_path)
        (tmp_path / "logs").mkdir()
        (tmp_path / "clients").mkdir()

        valid_json = json.dumps({
            "subject": "Dry run subject", "preview": "Preview text",
            "insight_title": "The title", "insight_body": "Body text.",
            "build_log": "Log text.", "cta_text": "CTA text.",
        })
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=valid_json)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg

        with patch("skills.newsletter_bot.anthropic.Anthropic", return_value=mock_client):
            with patch("skills.newsletter_bot._get_subscriber_count", return_value=42):
                run(fake_secrets, dry_run=True, force=True)

        state = _load_state()
        assert state["issue_number"] == 1
        assert state["issues"][0]["subject"] == "Dry run subject"
        assert state["issues"][0]["dry_run"] is True
        assert state["subscriber_count"] == 42

    def test_run_handles_generation_failure_gracefully(self, fake_secrets,
                                                        capsys):
        from skills.newsletter_bot import run

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API down")

        with patch("skills.newsletter_bot.anthropic.Anthropic", return_value=mock_client):
            with patch("skills.newsletter_bot._get_subscriber_count", return_value=0):
                run(fake_secrets, dry_run=True, force=True)

        out = capsys.readouterr().out
        assert "failed" in out.lower()
        # State should not have advanced
        state = _load_state()
        assert state["issue_number"] == 0
