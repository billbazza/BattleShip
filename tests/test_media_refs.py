import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import scripts.db as db


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    fake_db = tmp_path / "battleship.db"
    monkeypatch.setattr(db, "DB_FILE", fake_db)
    db.init_db()
    return fake_db


def test_normalize_media_ref_converts_current_and_legacy_absolute_paths():
    current = db.VAULT_ROOT / "brand" / "output" / "idea_card_test.jpg"
    legacy = "/Users/will/Obsidian-Vaults/BattleShip-Vault/brand/output/idea_card_test.jpg"

    assert db.normalize_media_ref(current) == "brand/output/idea_card_test.jpg"
    assert db.normalize_media_ref(legacy) == "brand/output/idea_card_test.jpg"


def test_resolve_media_path_maps_legacy_and_relative_refs_to_current_repo():
    rel = "SOVEREIGN/products/live/claude-code-ai-agent.pdf"
    legacy = f"/Users/will/Obsidian-Vaults/BattleShip-Vault/{rel}"

    assert db.resolve_media_path(rel) == db.VAULT_ROOT / rel
    assert db.resolve_media_path(legacy) == db.VAULT_ROOT / rel


def test_insert_post_stores_repo_relative_image_path(isolated_db):
    absolute = str(db.VAULT_ROOT / "brand" / "output" / "post_card_test.jpg")
    db.insert_post({
        "id": "cr_test123",
        "theme": "Test",
        "content": "Body",
        "stage": "content_review",
        "image_path": absolute,
    })

    row = db.get_post("cr_test123")
    assert row["image_path"] == "brand/output/post_card_test.jpg"

    with sqlite3.connect(isolated_db) as con:
        stored = con.execute("SELECT image_path FROM content_posts WHERE id='cr_test123'").fetchone()[0]
    assert stored == "brand/output/post_card_test.jpg"


def test_legacy_rows_are_normalized_when_read(isolated_db):
    legacy_image = "/Users/will/Obsidian-Vaults/BattleShip-Vault/brand/random-snaps/image.jpg"
    legacy_pdf = "/Users/will/Obsidian-Vaults/BattleShip-Vault/SOVEREIGN/products/live/test.pdf"

    with sqlite3.connect(isolated_db) as con:
        con.execute(
            "INSERT INTO content_posts (id, theme, content, stage, image_path, created_at) VALUES (?,?,?,?,?,datetime('now'))",
            ("cr_legacy", "Legacy", "Body", "content_review", legacy_image),
        )
        con.execute(
            "INSERT INTO guides (id, title, slug, pdf_path) VALUES (?,?,?,?)",
            ("guide_legacy", "Legacy Guide", "legacy-guide", legacy_pdf),
        )
        con.commit()

    post = db.get_post("cr_legacy")
    guide = db.get_guide("guide_legacy")
    assert post["image_path"] == "brand/random-snaps/image.jpg"
    assert guide["pdf_path"] == "SOVEREIGN/products/live/test.pdf"

    with sqlite3.connect(isolated_db) as con:
        stored_post = con.execute("SELECT image_path FROM content_posts WHERE id='cr_legacy'").fetchone()[0]
        stored_guide = con.execute("SELECT pdf_path FROM guides WHERE id='guide_legacy'").fetchone()[0]

    assert stored_post == "brand/random-snaps/image.jpg"
    assert stored_guide == "SOVEREIGN/products/live/test.pdf"
