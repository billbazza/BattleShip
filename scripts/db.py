"""
Battleship — SQLite database layer
===================================
Single source of truth for: ideas, content_posts, email_queue,
photo_candidates, reminders, pivot_notes, fb_queue_settings, bot_state.

All other modules import from here — sqlite3 is never imported elsewhere.
"""
import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import os

VAULT_ROOT = Path(__file__).parent.parent
DB_FILE    = VAULT_ROOT / "clients" / "battleship.db"

POST_DAYS  = {0, 2, 4}   # Mon=0, Wed=2, Fri=4
ACTIVE_POST_STAGE_RANK = {
    "posted": 4,
    "fb_queue": 3,
    "content_review": 2,
    "awaiting_graphic": 1,
    "marketing_review": 0,
}
_MEDIA_FIELDS_BY_TABLE = {
    "content_posts": ("image_path",),
    "photo_candidates": ("path",),
    "guides": ("pdf_path",),
}


# ── Connection ─────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_FILE))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    angle           TEXT NOT NULL DEFAULT '',
    copy            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'draft',
    source          TEXT NOT NULL DEFAULT 'marketing_bot',
    notes           TEXT NOT NULL DEFAULT '',
    tags            TEXT NOT NULL DEFAULT '[]',
    photo_id        TEXT,
    developed_into  TEXT,
    added_at        TEXT NOT NULL DEFAULT (date('now')),
    green_lit_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);

CREATE TABLE IF NOT EXISTS content_posts (
    id                   TEXT PRIMARY KEY,
    idea_id              TEXT REFERENCES ideas(id),
    theme                TEXT NOT NULL DEFAULT '',
    content              TEXT NOT NULL DEFAULT '',
    stage                TEXT NOT NULL DEFAULT 'marketing_review',
    source               TEXT NOT NULL DEFAULT 'facebook_bot',
    image_path           TEXT NOT NULL DEFAULT '',
    scheduled_for        TEXT,
    fb_post_id           TEXT NOT NULL DEFAULT '',
    send_back_comment    TEXT,
    graphic_requested_at TEXT,
    reviewed_at          TEXT,
    posted_at            TEXT,
    edited               INTEGER NOT NULL DEFAULT 0,
    arc_phase            INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_posts_stage      ON content_posts(stage);
CREATE INDEX IF NOT EXISTS idx_posts_scheduled  ON content_posts(scheduled_for);

CREATE TABLE IF NOT EXISTS fb_queue_settings (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    paused      INTEGER NOT NULL DEFAULT 0,
    paused_at   TEXT,
    resumed_at  TEXT,
    post_days   TEXT NOT NULL DEFAULT '[0,2,4]'
);
INSERT OR IGNORE INTO fb_queue_settings (id, paused) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS reminders (
    id          TEXT PRIMARY KEY,
    added_by    TEXT NOT NULL DEFAULT 'bot',
    type        TEXT NOT NULL DEFAULT 'other',
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    priority    TEXT NOT NULL DEFAULT 'medium',
    status      TEXT NOT NULL DEFAULT 'pending',
    content_url TEXT,
    done_at     TEXT,
    pivoted_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status);

CREATE TABLE IF NOT EXISTS pivot_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id TEXT NOT NULL REFERENCES reminders(id),
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_queue (
    id          TEXT PRIMARY KEY,
    to_addr     TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    html_body   TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    source      TEXT NOT NULL DEFAULT 'pipeline',
    client_acct TEXT,
    reason      TEXT NOT NULL DEFAULT '',
    client_name TEXT NOT NULL DEFAULT '',
    sent_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_email_status ON email_queue(status);

CREATE TABLE IF NOT EXISTS photo_candidates (
    id              TEXT PRIMARY KEY,
    filename        TEXT NOT NULL DEFAULT '',
    path            TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    caption_hint    TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'random-snaps',
    review_source   TEXT,
    reviewed_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_photo_status ON photo_candidates(status);

CREATE TABLE IF NOT EXISTS bot_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS guides (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    slug            TEXT NOT NULL DEFAULT '',
    price_pence     INTEGER NOT NULL DEFAULT 799,
    status          TEXT NOT NULL DEFAULT 'draft',
    pdf_path        TEXT NOT NULL DEFAULT '',
    stripe_link     TEXT NOT NULL DEFAULT '',
    ls_product_id   TEXT NOT NULL DEFAULT '',
    buy_url         TEXT NOT NULL DEFAULT '',
    total_sales     INTEGER NOT NULL DEFAULT 0,
    total_revenue   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    published_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_guides_status ON guides(status);

CREATE TABLE IF NOT EXISTS guide_sales (
    id              TEXT PRIMARY KEY,
    guide_id        TEXT NOT NULL REFERENCES guides(id),
    order_id        TEXT NOT NULL DEFAULT '',
    customer_email  TEXT NOT NULL DEFAULT '',
    amount_pence    INTEGER NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'GBP',
    source          TEXT NOT NULL DEFAULT 'stripe',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_guide_sales_guide ON guide_sales(guide_id);
"""


def init_db():
    """Create all tables + run migrations. Safe to call on every startup."""
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as con:
        con.executescript(_SCHEMA)
        # Migrations — SQLite has no ADD COLUMN IF NOT EXISTS
        _migrate_add_column(con, "content_posts", "arc_phase", "INTEGER NOT NULL DEFAULT 0")
        con.execute("CREATE INDEX IF NOT EXISTS idx_posts_arc_phase ON content_posts(arc_phase)")
        # Backfill: existing posts without an explicit arc_phase get 0 (phase 1)
        con.execute("UPDATE content_posts SET arc_phase = 0 WHERE arc_phase IS NULL")
        _archive_duplicate_active_posts(con)
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_one_active_per_idea "
            "ON content_posts(idea_id) "
            "WHERE idea_id IS NOT NULL AND idea_id != '' AND stage != 'archived'"
        )


def _migrate_add_column(con, table: str, column: str, col_def: str):
    """Safely add a column to an existing table, ignoring if it already exists."""
    try:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except sqlite3.OperationalError:
        pass  # column already exists


def _post_stage_rank(stage: str) -> int:
    return ACTIVE_POST_STAGE_RANK.get(stage or "", -1)


def _post_recency_value(post: dict | sqlite3.Row) -> str:
    return (
        post["posted_at"]
        or post["scheduled_for"]
        or post["reviewed_at"]
        or post["created_at"]
        or ""
    )


def _archive_duplicate_active_posts(con):
    """Collapse existing duplicate active posts per idea before adding the unique index."""
    rows = con.execute(
        "SELECT * FROM content_posts "
        "WHERE idea_id IS NOT NULL AND idea_id != '' AND stage != 'archived'"
    ).fetchall()
    by_idea: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_idea.setdefault(row["idea_id"], []).append(row)

    for idea_id, posts in by_idea.items():
        if len(posts) < 2:
            continue
        keep = max(
            posts,
            key=lambda post: (_post_stage_rank(post["stage"]), _post_recency_value(post), post["id"]),
        )
        for post in posts:
            if post["id"] == keep["id"]:
                continue
            con.execute(
                "UPDATE content_posts SET stage='archived' WHERE id=?",
                (post["id"],),
            )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:8]


def _as_posix_rel(path: Path) -> str:
    return path.as_posix().lstrip("/")


def normalize_media_ref(value: str | os.PathLike | None) -> str:
    """Store repo-owned media references as repo-relative keys, not absolute paths."""
    if value in (None, ""):
        return ""

    raw = str(value).strip()
    if not raw:
        return ""

    candidate = Path(raw).expanduser()

    if candidate.is_absolute():
        try:
            return _as_posix_rel(candidate.resolve(strict=False).relative_to(VAULT_ROOT.resolve()))
        except ValueError:
            pass

        marker = f"{VAULT_ROOT.name}/"
        marker_idx = raw.replace("\\", "/").find(marker)
        if marker_idx >= 0:
            return raw.replace("\\", "/")[marker_idx + len(marker):].lstrip("/")

        return raw

    normalized = raw.replace("\\", "/").lstrip("./")
    if normalized.startswith(VAULT_ROOT.name + "/"):
        normalized = normalized[len(VAULT_ROOT.name) + 1:]
    return normalized


def resolve_media_path(value: str | os.PathLike | None) -> Path | None:
    """Resolve a stored media reference to an absolute filesystem path at runtime."""
    if value in (None, ""):
        return None

    raw = str(value).strip()
    if not raw:
        return None

    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        normalized = normalize_media_ref(raw)
        if normalized != raw:
            return VAULT_ROOT / normalized
        return candidate

    return VAULT_ROOT / normalize_media_ref(raw)


def to_brand_asset_path(value: str | os.PathLike | None) -> str:
    """Return the path segment expected by `/brand/<path:...>` or empty if not a brand asset."""
    rel = normalize_media_ref(value)
    if not rel.startswith("brand/"):
        return ""
    return rel[len("brand/"):]


def _normalize_media_fields(fields: dict, table: str) -> dict:
    media_fields = _MEDIA_FIELDS_BY_TABLE.get(table, ())
    if not media_fields:
        return fields

    normalized = dict(fields)
    for key in media_fields:
        if key in normalized:
            normalized[key] = normalize_media_ref(normalized[key])
    return normalized


def _normalize_row_media_refs(table: str, row: dict) -> dict:
    media_fields = _MEDIA_FIELDS_BY_TABLE.get(table, ())
    if not row or not media_fields:
        return row

    normalized = dict(row)
    dirty = False
    for key in media_fields:
        if key not in normalized:
            continue
        value = normalized.get(key, "")
        new_value = normalize_media_ref(value)
        if new_value != value:
            normalized[key] = new_value
            dirty = True

    if dirty and normalized.get("id"):
        sets = ", ".join(f"{key}=?" for key in media_fields if key in normalized)
        values = [normalized[key] for key in media_fields if key in normalized]
        with _conn() as con:
            con.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*values, normalized["id"]])

    return normalized


# ── Ideas ──────────────────────────────────────────────────────────────────────

def get_ideas(status: str | None = None) -> list[dict]:
    with _conn() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM ideas WHERE status=? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM ideas ORDER BY created_at DESC"
            ).fetchall()
    return _rows_to_list(rows)


def get_idea(idea_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
    return _row_to_dict(row)


def upsert_idea(fields: dict):
    if "id" not in fields:
        fields["id"] = _new_id("idea_")
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "id")
    sql = (f"INSERT INTO ideas ({cols}) VALUES ({placeholders}) "
           f"ON CONFLICT(id) DO UPDATE SET {updates}")
    with _conn() as con:
        con.execute(sql, list(fields.values()))


def update_idea(idea_id: str, fields: dict):
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with _conn() as con:
        con.execute(f"UPDATE ideas SET {sets} WHERE id=?", [*fields.values(), idea_id])


def set_idea_status(idea_id: str, status: str, extra: dict | None = None):
    fields = {"status": status, **(extra or {})}
    sets = ", ".join(f"{k}=?" for k in fields)
    with _conn() as con:
        con.execute(f"UPDATE ideas SET {sets} WHERE id=?",
                    [*fields.values(), idea_id])


def delete_ideas_not_in(keep_ids: list[str]) -> int:
    """Delete all ideas whose IDs are not in the keep_ids list. Returns count deleted."""
    with _conn() as con:
        placeholders = ",".join("?" * len(keep_ids)) if keep_ids else "''"
        result = con.execute(
            f"DELETE FROM ideas WHERE id NOT IN ({placeholders})",
            keep_ids if keep_ids else []
        )
        return result.rowcount


# ── Content Posts ──────────────────────────────────────────────────────────────

def get_posts(stage: str | None = None) -> list[dict]:
    with _conn() as con:
        if stage:
            rows = con.execute(
                "SELECT * FROM content_posts WHERE stage=? ORDER BY scheduled_for ASC, created_at DESC",
                (stage,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM content_posts ORDER BY created_at DESC"
            ).fetchall()
    return [_normalize_row_media_refs("content_posts", dict(r)) for r in rows]


def count_pending_posts_for_arc(arc_phase: int) -> int:
    """Count posts in a given arc_phase that haven't been posted or archived yet."""
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS cnt FROM content_posts "
            "WHERE arc_phase=? AND stage NOT IN ('posted', 'archived')",
            (arc_phase,)
        ).fetchone()
    return row["cnt"] if row else 0


def get_post(post_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM content_posts WHERE id=?", (post_id,)).fetchone()
    return _normalize_row_media_refs("content_posts", _row_to_dict(row))


def get_active_post_for_idea(idea_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM content_posts "
            "WHERE idea_id=? AND stage != 'archived' "
            "ORDER BY "
            "CASE stage "
            "WHEN 'posted' THEN 4 "
            "WHEN 'fb_queue' THEN 3 "
            "WHEN 'content_review' THEN 2 "
            "WHEN 'awaiting_graphic' THEN 1 "
            "WHEN 'marketing_review' THEN 0 "
            "ELSE -1 END DESC, "
            "COALESCE(posted_at, scheduled_for, reviewed_at, created_at) DESC, "
            "created_at DESC, id DESC "
            "LIMIT 1",
            (idea_id,),
        ).fetchone()
    return _normalize_row_media_refs("content_posts", _row_to_dict(row)) if row else None


def insert_post(fields: dict):
    fields = _normalize_media_fields(fields, "content_posts")
    if "id" not in fields:
        fields["id"] = _new_id("cr_")
    if "created_at" not in fields:
        fields["created_at"] = _now()
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    with _conn() as con:
        try:
            con.execute(f"INSERT INTO content_posts ({cols}) VALUES ({placeholders})",
                        list(fields.values()))
        except sqlite3.IntegrityError:
            if fields.get("idea_id") and fields.get("stage") != "archived":
                row = con.execute(
                    "SELECT * FROM content_posts WHERE idea_id=? AND stage != 'archived' LIMIT 1",
                    (fields["idea_id"],),
                ).fetchone()
                if row:
                    return _normalize_row_media_refs("content_posts", dict(row))
            raise
        row = con.execute("SELECT * FROM content_posts WHERE id=?", (fields["id"],)).fetchone()
    return _normalize_row_media_refs("content_posts", dict(row)) if row else None


def ensure_active_post(fields: dict, update_existing: dict | None = None) -> tuple[dict, bool]:
    """Return the single active post for an idea, creating it if missing."""
    idea_id = (fields.get("idea_id") or "").strip()
    if not idea_id:
        raise ValueError("ensure_active_post requires idea_id")

    existing = get_active_post_for_idea(idea_id)
    if existing:
        updates = {}
        for key, value in (update_existing or {}).items():
            if value is None:
                continue
            if key == "image_path":
                if value and existing.get("image_path") != value:
                    updates[key] = value
            elif not existing.get(key) and value not in ("", None):
                updates[key] = value
        if updates:
            update_post(existing["id"], updates)
            existing = get_post(existing["id"]) or existing
        return existing, False

    post = insert_post(fields)
    if post:
        return post, True
    existing = get_active_post_for_idea(idea_id)
    if existing:
        return existing, False
    raise sqlite3.IntegrityError(f"Failed to create active post for idea {idea_id}")


def update_post(post_id: str, fields: dict):
    fields = _normalize_media_fields(fields, "content_posts")
    sets = ", ".join(f"{k}=?" for k in fields)
    with _conn() as con:
        con.execute(f"UPDATE content_posts SET {sets} WHERE id=?",
                    [*fields.values(), post_id])


def advance_post_stage(post_id: str, new_stage: str, extra: dict | None = None):
    fields = {"stage": new_stage, **(extra or {})}
    update_post(post_id, fields)


# ── FB Queue settings + schedule ───────────────────────────────────────────────

def get_queue_settings() -> dict:
    with _conn() as con:
        row = con.execute("SELECT * FROM fb_queue_settings WHERE id=1").fetchone()
    return _row_to_dict(row)


def set_queue_paused(paused: bool):
    now = _now()
    if paused:
        with _conn() as con:
            con.execute("UPDATE fb_queue_settings SET paused=1, paused_at=? WHERE id=1", (now,))
    else:
        with _conn() as con:
            con.execute("UPDATE fb_queue_settings SET paused=0, resumed_at=? WHERE id=1", (now,))
        recalculate_schedule()


def recalculate_schedule(from_date: date | None = None):
    """Reassign Mon/Wed/Fri slots for BSR queued posts from from_date onwards.
    SOVEREIGN posts (source='sovereign') keep their own schedule and are skipped."""
    start = from_date or date.today()
    posts = get_posts(stage="fb_queue")
    # Only reschedule BSR posts — sovereign posts manage their own dates
    bsr_posts = [p for p in posts if p.get("source") != "sovereign"]
    bsr_posts.sort(key=lambda p: p.get("scheduled_for") or "9999")

    d = start
    with _conn() as con:
        for post in bsr_posts:
            while d.weekday() not in POST_DAYS:
                d += timedelta(days=1)
            con.execute("UPDATE content_posts SET scheduled_for=? WHERE id=?",
                        (d.isoformat(), post["id"]))
            d += timedelta(days=1)


def next_available_slot(from_date: date | None = None) -> str:
    """Return the next Mon/Wed/Fri date not already taken in the fb_queue."""
    with _conn() as con:
        taken = {r[0] for r in con.execute(
            "SELECT scheduled_for FROM content_posts WHERE stage='fb_queue'"
        ).fetchall() if r[0]}

    d = from_date or date.today()
    while True:
        if d.weekday() in POST_DAYS and d.isoformat() not in taken:
            return d.isoformat()
        d += timedelta(days=1)


# ── Reminders ──────────────────────────────────────────────────────────────────

def get_reminder(rem_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM reminders WHERE id=?", (rem_id,)).fetchone()
    return _row_to_dict(row) or None


def get_reminders(status: str = "pending") -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM reminders WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
    return _rows_to_list(rows)


def get_all_reminders() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM reminders ORDER BY created_at DESC").fetchall()
    return _rows_to_list(rows)


def insert_reminder(fields: dict) -> str:
    rid = fields.get("id") or _new_id("rem_")
    fields["id"] = rid
    if "created_at" not in fields:
        fields["created_at"] = _now()
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    with _conn() as con:
        con.execute(f"INSERT OR IGNORE INTO reminders ({cols}) VALUES ({placeholders})",
                    list(fields.values()))
    return rid


def dismiss_reminder(rem_id: str):
    with _conn() as con:
        con.execute("UPDATE reminders SET status='done', done_at=? WHERE id=?",
                    (_now(), rem_id))


def pivot_reminder(rem_id: str, note: str):
    now = _now()
    with _conn() as con:
        con.execute("UPDATE reminders SET status='pivoted', pivoted_at=? WHERE id=?",
                    (now, rem_id))
        con.execute("INSERT INTO pivot_notes (reminder_id, note, created_at) VALUES (?,?,?)",
                    (rem_id, note, now))


def get_pivot_notes(limit: int = 10) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT p.*, r.title as reminder_title FROM pivot_notes p "
            "LEFT JOIN reminders r ON p.reminder_id=r.id "
            "ORDER BY p.created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return _rows_to_list(rows)


# ── Email Queue ────────────────────────────────────────────────────────────────

def get_pending_emails() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM email_queue WHERE status='pending' ORDER BY created_at ASC"
        ).fetchall()
    return _rows_to_list(rows)


def insert_email(fields: dict) -> str:
    eid = fields.get("id") or _new_id("eq_")
    fields["id"] = eid
    if "created_at" not in fields:
        fields["created_at"] = _now()
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    with _conn() as con:
        con.execute(f"INSERT OR IGNORE INTO email_queue ({cols}) VALUES ({placeholders})",
                    list(fields.values()))
    return eid


def mark_email_sent(eq_id: str):
    with _conn() as con:
        con.execute("UPDATE email_queue SET status='sent', sent_at=? WHERE id=?",
                    (_now(), eq_id))


def mark_email_rejected(eq_id: str):
    with _conn() as con:
        con.execute("UPDATE email_queue SET status='rejected' WHERE id=?", (eq_id,))


# ── Photo Candidates ───────────────────────────────────────────────────────────

def get_photo_candidate(photo_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM photo_candidates WHERE id=?", (photo_id,)).fetchone()
    return _normalize_row_media_refs("photo_candidates", _row_to_dict(row)) or None


def get_pending_photos() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM photo_candidates WHERE status='pending' ORDER BY created_at DESC"
        ).fetchall()
    return [_normalize_row_media_refs("photo_candidates", dict(r)) for r in rows]


def insert_photo_candidate(fields: dict) -> str:
    fields = _normalize_media_fields(fields, "photo_candidates")
    pid = fields.get("id") or _new_id("ph_")
    fields["id"] = pid
    if "created_at" not in fields:
        fields["created_at"] = _now()
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    with _conn() as con:
        con.execute(f"INSERT OR IGNORE INTO photo_candidates ({cols}) VALUES ({placeholders})",
                    list(fields.values()))
    return pid


def set_photo_status(photo_id: str, status: str, review_source: str = "dashboard"):
    with _conn() as con:
        con.execute(
            "UPDATE photo_candidates SET status=?, reviewed_at=?, review_source=? WHERE id=?",
            (status, _now(), review_source, photo_id)
        )


# ── Bot State ──────────────────────────────────────────────────────────────────

def get_bot_state(key: str) -> str | None:
    with _conn() as con:
        row = con.execute("SELECT value FROM bot_state WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_bot_state(key: str, value: str):
    with _conn() as con:
        con.execute(
            "INSERT INTO bot_state (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, _now())
        )


# ── Bot Learnings ──────────────────────────────────────────────────────────────
# Rolling log of Will's decisions — pivot notes, dismissals, tech completions.
# Each bot reads its own slice on every run to inform prompts.

def record_learning(source: str, learning_type: str, text: str, context: str = ""):
    """Append a learning to the rolling bot_learnings log (max 50 entries)."""
    import json as _json
    raw = get_bot_state("bot_learnings") or "[]"
    try:
        learnings = _json.loads(raw)
    except Exception:
        learnings = []
    learnings.append({
        "source":  source,        # e.g. 'marketing_bot', 'facebook_bot', 'tech_bot', 'manual'
        "type":    learning_type, # e.g. 'pivot', 'dismiss', 'tech_done', 'send_back'
        "text":    text,
        "context": context,
        "added_at": _now(),
    })
    set_bot_state("bot_learnings", _json.dumps(learnings[-50:]))


def get_learnings(source: str | None = None) -> list[dict]:
    """Return learnings, optionally filtered by source bot."""
    import json as _json
    raw = get_bot_state("bot_learnings") or "[]"
    try:
        learnings = _json.loads(raw)
    except Exception:
        return []
    if source:
        return [l for l in learnings if l.get("source") == source]
    return learnings


# ── Guides ─────────────────────────────────────────────────────────────────────

def upsert_guide(fields: dict):
    fields = _normalize_media_fields(fields, "guides")
    if "id" not in fields:
        fields["id"] = _new_id("guide_")
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "id")
    sql = (f"INSERT INTO guides ({cols}) VALUES ({placeholders}) "
           f"ON CONFLICT(id) DO UPDATE SET {updates}")
    with _conn() as con:
        con.execute(sql, list(fields.values()))


def get_guides(status: str | None = None) -> list[dict]:
    with _conn() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM guides WHERE status=? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM guides ORDER BY created_at DESC"
            ).fetchall()
    return [_normalize_row_media_refs("guides", dict(r)) for r in rows]


def get_guide(guide_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM guides WHERE id=?", (guide_id,)).fetchone()
    return _normalize_row_media_refs("guides", _row_to_dict(row))


def insert_guide_sale(fields: dict) -> str:
    if "id" not in fields:
        fields["id"] = _new_id("gsale_")
    if "created_at" not in fields:
        fields["created_at"] = _now()
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    with _conn() as con:
        con.execute(f"INSERT INTO guide_sales ({cols}) VALUES ({placeholders})",
                    list(fields.values()))
    # Increment guide totals
    guide_id = fields.get("guide_id", "")
    amount = fields.get("amount_pence", 0)
    if guide_id:
        with _conn() as con:
            con.execute(
                "UPDATE guides SET total_sales = total_sales + 1, "
                "total_revenue = total_revenue + ? WHERE id = ?",
                (amount, guide_id)
            )
    return fields["id"]


def get_guide_sales(guide_id: str | None = None) -> list[dict]:
    with _conn() as con:
        if guide_id:
            rows = con.execute(
                "SELECT * FROM guide_sales WHERE guide_id=? ORDER BY created_at DESC",
                (guide_id,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM guide_sales ORDER BY created_at DESC"
            ).fetchall()
    return _rows_to_list(rows)


def get_guide_revenue_total() -> int:
    """Return total revenue in pence across all guides."""
    with _conn() as con:
        row = con.execute("SELECT COALESCE(SUM(total_revenue), 0) AS total FROM guides").fetchone()
    return row["total"] if row else 0


# ── Init on import ─────────────────────────────────────────────────────────────

init_db()
