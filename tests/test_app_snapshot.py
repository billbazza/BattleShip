import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import scripts.app as app_module  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    audit_log = tmp_path / "snapshot_access.log"
    monkeypatch.setattr(app_module, "SNAPSHOT_AUDIT_LOG", audit_log)
    monkeypatch.setattr(app_module, "_build_business_context", lambda: {"title": "Snapshot"})
    monkeypatch.setattr(
        app_module,
        "render_template_string",
        lambda template, **ctx: f"snapshot:{ctx['is_snapshot']}:{ctx['snapshot_ts']}",
    )
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def _valid_signature(secret: str, expires: int) -> str:
    return app_module._snapshot_signature(expires, secret)


def test_snapshot_denies_missing_signature_and_logs(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        app_module,
        "_runtime_env",
        lambda: {app_module.SNAPSHOT_SECRET_ENV: "secret-1"},
    )

    response = client.get("/snapshot", base_url="http://localhost:5100")

    assert response.status_code == 403
    log_entry = json.loads(app_module.SNAPSHOT_AUDIT_LOG.read_text().strip())
    assert log_entry["allowed"] is False
    assert log_entry["reason"] == "missing_signature"


def test_snapshot_denies_remote_host_when_remote_access_disabled(client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_runtime_env",
        lambda: {app_module.SNAPSHOT_SECRET_ENV: "secret-1"},
    )
    expires = int(datetime.now(timezone.utc).timestamp()) + 60
    sig = _valid_signature("secret-1", expires)

    response = client.get(
        f"/snapshot?expires={expires}&sig={sig}",
        base_url="https://webhook.battleshipreset.com",
    )

    assert response.status_code == 404
    log_entry = json.loads(app_module.SNAPSHOT_AUDIT_LOG.read_text().strip())
    assert log_entry["allowed"] is False
    assert log_entry["reason"] == "remote_disabled"


def test_snapshot_denies_expired_signature_and_logs(client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_runtime_env",
        lambda: {app_module.SNAPSHOT_SECRET_ENV: "secret-1"},
    )
    expires = int(datetime.now(timezone.utc).timestamp()) - 60
    sig = _valid_signature("secret-1", expires)

    response = client.get(
        f"/snapshot?expires={expires}&sig={sig}",
        base_url="http://localhost:5100",
    )

    assert response.status_code == 403
    lines = app_module.SNAPSHOT_AUDIT_LOG.read_text().strip().splitlines()
    log_entry = json.loads(lines[-1])
    assert log_entry["allowed"] is False
    assert log_entry["reason"] == "expired"


def test_snapshot_allows_signed_request_and_logs(client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_runtime_env",
        lambda: {app_module.SNAPSHOT_SECRET_ENV: "secret-1"},
    )
    expires = int(datetime.now(timezone.utc).timestamp()) + 60
    sig = _valid_signature("secret-1", expires)

    response = client.get(
        f"/snapshot?expires={expires}&sig={sig}",
        base_url="http://localhost:5100",
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True).startswith("snapshot:True:")
    lines = app_module.SNAPSHOT_AUDIT_LOG.read_text().strip().splitlines()
    log_entry = json.loads(lines[-1])
    assert log_entry["allowed"] is True
    assert log_entry["reason"] == "authorized"
