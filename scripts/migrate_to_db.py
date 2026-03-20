"""
Battleship — One-time JSON → SQLite migration
Run: python3 scripts/migrate_to_db.py

Safe to run multiple times (uses INSERT OR IGNORE throughout).
"""
import json
import sys
from pathlib import Path

VAULT = Path(__file__).parent.parent
sys.path.insert(0, str(VAULT))
import scripts.db as db  # noqa: E402

REMINDERS_FILE     = VAULT / "brand" / "Marketing" / "reminders.json"
IDEAS_FILE         = VAULT / "brand" / "Marketing" / "ideas-bank.json"
CONTENT_FILE       = VAULT / "clients" / "content_review.json"
EMAIL_QUEUE_FILE   = VAULT / "clients" / "email_queue.json"
PHOTO_FILE         = VAULT / "clients" / "photo_review_state.json"
REVIEW_STATE_FILE  = VAULT / "brand" / "Marketing" / "review_state.json"


# ── Stage mapping ──────────────────────────────────────────────────────────────

STATUS_TO_STAGE = {
    "pending_review": "content_review",
    "approved":       "fb_queue",
    "posted":         "posted",
    "rejected":       "archived",
    "pending":        "content_review",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"  ⚠️  Could not read {path.name}: {e}")
        return default


def _coerce_dt(val: str | None) -> str | None:
    """Accept both ISO datetime and bare date strings."""
    if not val:
        return None
    if "T" not in val:
        return val + "T00:00:00"
    return val


# ── Migrations ─────────────────────────────────────────────────────────────────

def migrate_reminders():
    print("📌 Reminders...")
    data = _load(REMINDERS_FILE, {"reminders": [], "pivot_notes": []})
    n = 0
    for r in data.get("reminders", []):
        created = _coerce_dt(r.get("created_at") or r.get("created")) or db._now()
        db.insert_reminder({
            "id":          r["id"],
            "added_by":    r.get("added_by", "bot"),
            "type":        r.get("type", "other"),
            "title":       r.get("title", ""),
            "description": r.get("description", ""),
            "priority":    r.get("priority", "medium"),
            "status":      r.get("status", "pending"),
            "content_url": r.get("content_url"),
            "done_at":     _coerce_dt(r.get("done_at")),
            "pivoted_at":  _coerce_dt(r.get("pivoted_at")),
            "created_at":  created,
        })
        n += 1

    p = 0
    import sqlite3
    with db._conn() as con:
        for pn in data.get("pivot_notes", []):
            rid = pn.get("reminder_id", "")
            note = pn.get("note", "")
            created = _coerce_dt(pn.get("created_at")) or db._now()
            try:
                con.execute(
                    "INSERT OR IGNORE INTO pivot_notes (reminder_id, note, created_at) "
                    "VALUES (?,?,?)", (rid, note, created)
                )
                p += 1
            except sqlite3.IntegrityError:
                pass  # reminder_id FK missing — skip orphaned pivot note

    print(f"   {n} reminders, {p} pivot notes migrated")


def migrate_ideas():
    print("💡 Ideas bank...")
    data = _load(IDEAS_FILE, {"ideas": []})
    n = 0
    for idea in data.get("ideas", []):
        status = idea.get("status", "draft")
        # Normalise: developed → green_lit for DB purposes
        if status == "developed":
            status = "green_lit"

        tags = idea.get("tags", [])
        if isinstance(tags, list):
            tags = json.dumps(tags)

        db.upsert_idea({
            "id":             idea["id"],
            "title":          idea.get("title", ""),
            "angle":          idea.get("angle", ""),
            "copy":           idea.get("copy", ""),
            "status":         status,
            "source":         idea.get("source", "marketing_bot"),
            "notes":          idea.get("notes", ""),
            "tags":           tags,
            "photo_id":       idea.get("photo_id"),
            "developed_into": idea.get("developed_into"),
            "added_at":       idea.get("added", idea.get("created", "2026-03-01")),
            "green_lit_at":   idea.get("green_lit_at") or idea.get("green_lit"),
            "created_at":     _coerce_dt(idea.get("created", idea.get("added"))) or db._now(),
        })
        n += 1
    print(f"   {n} ideas migrated")


def migrate_content_posts():
    print("📝 Content posts...")
    data = _load(CONTENT_FILE, {"posts": []})
    n = 0
    for post in data.get("posts", []):
        old_status = post.get("status", "pending_review")
        stage = STATUS_TO_STAGE.get(old_status, "content_review")

        # If "approved" but already has a post_id it's really posted
        if old_status == "approved" and post.get("post_id"):
            stage = "posted"

        db.insert_post({
            "id":           post["id"],
            "idea_id":      post.get("idea_id") or None,
            "theme":        post.get("theme", ""),
            "content":      post.get("content", ""),
            "stage":        stage,
            "source":       post.get("source", "facebook_bot"),
            "image_path":   post.get("image_path", ""),
            "scheduled_for": post.get("scheduled_for"),
            "fb_post_id":   post.get("post_id", ""),
            "reviewed_at":  _coerce_dt(post.get("reviewed_at")),
            "posted_at":    _coerce_dt(post.get("posted_at")),
            "edited":       1 if post.get("edited") else 0,
            "created_at":   post.get("created", db._now()),
        })
        n += 1
    print(f"   {n} posts migrated")


def migrate_email_queue():
    print("📬 Email queue...")
    data = _load(EMAIL_QUEUE_FILE, {"emails": []})
    n = 0
    for e in data.get("emails", []):
        db.insert_email({
            "id":          e["id"],
            "to_addr":     e.get("to", e.get("to_addr", "")),
            "subject":     e.get("subject", ""),
            "body":        e.get("body", ""),
            "status":      e.get("status", "pending"),
            "reason":      e.get("reason", ""),
            "client_name": e.get("client_name", ""),
            "sent_at":     _coerce_dt(e.get("sent_at")),
            "created_at":  _coerce_dt(e.get("created_at")) or db._now(),
        })
        n += 1
    print(f"   {n} emails migrated")


def migrate_photo_candidates():
    print("📸 Photo candidates...")
    data = _load(PHOTO_FILE, {"candidates": []})
    BRAND_PREFIX = str(VAULT / "brand") + "/"
    n = 0
    for c in data.get("candidates", []):
        path = c.get("path", "")
        url = ""
        if path.startswith(BRAND_PREFIX):
            url = "/brand/" + path[len(BRAND_PREFIX):]

        db.insert_photo_candidate({
            "id":           c["id"],
            "filename":     c.get("filename", ""),
            "path":         path,
            "url":          url,
            "status":       c.get("status", "pending"),
            "caption_hint": c.get("caption_hint", ""),
            "source":       c.get("source", "random-snaps"),
            "review_source": c.get("review_source"),
            "reviewed_at":  _coerce_dt(c.get("reviewed_at")),
            "created_at":   _coerce_dt(c.get("created_at") or c.get("created")) or db._now(),
        })
        n += 1
    print(f"   {n} photo candidates migrated")


def migrate_bot_state():
    print("🤖 Bot state...")
    data = _load(REVIEW_STATE_FILE, {})
    for k, v in data.items():
        db.set_bot_state(k, str(v))
    print(f"   {len(data)} keys migrated")


def assign_queued_slots():
    """Ensure fb_queue posts have scheduled_for dates."""
    from datetime import date as _date
    queued = [p for p in db.get_posts(stage="fb_queue") if not p.get("scheduled_for")]
    if queued:
        print(f"   Assigning slots to {len(queued)} unscheduled queued posts...")
        db.recalculate_schedule(from_date=_date.today())


# ── Entry point ────────────────────────────────────────────────────────────────

def migrate():
    print("\n🗄  Battleship JSON → SQLite migration\n")
    db.init_db()
    migrate_reminders()
    migrate_ideas()
    migrate_content_posts()
    migrate_email_queue()
    migrate_photo_candidates()
    migrate_bot_state()
    assign_queued_slots()
    print(f"\n✅ Migration complete → {db.DB_FILE}\n")
    print("Next steps:")
    print("  1. Verify data looks correct: python3 scripts/migrate_to_db.py --verify")
    print("  2. Restart the dashboard: launchctl stop/start com.battleship.dashboard")
    print("  3. JSON files are kept as backups — delete manually when happy\n")


def verify():
    """Quick count check across all tables."""
    print("\n📊 Database contents:\n")
    import sqlite3
    with db._conn() as con:
        for table in ["ideas", "content_posts", "email_queue",
                      "photo_candidates", "reminders", "pivot_notes", "bot_state"]:
            n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:25} {n:4} rows")

        print("\n  Content posts by stage:")
        rows = con.execute(
            "SELECT stage, COUNT(*) as n FROM content_posts GROUP BY stage ORDER BY n DESC"
        ).fetchall()
        for r in rows:
            print(f"    {r['stage']:25} {r['n']:4}")

        print("\n  Ideas by status:")
        rows = con.execute(
            "SELECT status, COUNT(*) as n FROM ideas GROUP BY status ORDER BY n DESC"
        ).fetchall()
        for r in rows:
            print(f"    {r['status']:25} {r['n']:4}")
    print()


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        migrate()
        verify()
