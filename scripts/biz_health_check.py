#!/usr/bin/env python3
"""
Battleship — Business Manager Health Check
==========================================
Checks all critical systems and returns a pass/fail report.

Usage:
    python3 scripts/biz_health_check.py
    python3 scripts/biz_health_check.py --quiet   # minimal output

Returns exit code 0 if all pass, 1 if any failures.
"""

import json
import sqlite3
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

VAULT_ROOT  = Path(__file__).parent.parent
DB_FILE     = VAULT_ROOT / "clients" / "battleship.db"
LOG_FILE    = VAULT_ROOT / "logs" / "pipeline.log"
BASE_URL    = "http://localhost:5100"

EXPECTED_TABLES = {
    "ideas", "content_posts", "fb_queue_settings",
    "reminders", "bot_state",
}

ROUTES_TO_CHECK = [
    "/",
    "/business",
    "/api/fb-queue/settings",
]

ERROR_SIGNATURES = [
    "Internal Server Error",
    "Traceback (most recent",
    "jinja2",
    "UndefinedError",
    "KeyError",
    "TemplateError",
]

LAUNCHD_JOBS = [
    "com.battleship.dashboard",
    "com.battleship.tunnel",
    "com.battleship.pipeline",
]


# ── Checks ─────────────────────────────────────────────────────────────────────

def _check_route(path: str) -> tuple[bool, str]:
    """GET a route; return (ok, message)."""
    url = BASE_URL + path
    try:
        req  = urllib.request.Request(url, headers={"User-Agent": "biz-health-check/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            status = r.status
            if status != 200:
                return False, f"{path} → HTTP {status}"
            # For HTML routes check for error signatures
            if path in ("/", "/business"):
                body = r.read(65536).decode("utf-8", errors="replace")
                for sig in ERROR_SIGNATURES:
                    if sig in body:
                        return False, f"{path} → contains '{sig}' in response"
            return True, f"{path} → 200 OK"
    except urllib.error.HTTPError as e:
        return False, f"{path} → HTTP {e.code}"
    except Exception as e:
        return False, f"{path} → {type(e).__name__}: {e}"


def _check_db() -> tuple[bool, str]:
    """Verify DB is accessible and has expected tables."""
    if not DB_FILE.exists():
        return False, f"DB file not found: {DB_FILE}"
    try:
        con = sqlite3.connect(str(DB_FILE))
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        con.close()
        found = {r[0] for r in rows}
        missing = EXPECTED_TABLES - found
        if missing:
            return False, f"DB missing tables: {', '.join(sorted(missing))}"
        return True, f"DB OK ({len(found)} tables)"
    except Exception as e:
        return False, f"DB error: {e}"


def _check_launchd() -> list[tuple[bool, str]]:
    """Check each LaunchAgent is loaded."""
    results = []
    try:
        proc = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=10
        )
        loaded = proc.stdout
        for job in LAUNCHD_JOBS:
            if job in loaded:
                results.append((True, f"{job} running"))
            else:
                results.append((False, f"{job} NOT running"))
    except Exception as e:
        for job in LAUNCHD_JOBS:
            results.append((False, f"{job} — launchctl error: {e}"))
    return results


def _check_pipeline_log() -> tuple[bool, str]:
    """Check pipeline log for errors in the last 24 hours."""
    if not LOG_FILE.exists():
        return True, "Pipeline log not found (never run — OK for first boot)"
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        # Read last 200 lines — pipeline runs hourly so this is plenty
        lines  = LOG_FILE.read_text(errors="replace").splitlines()[-200:]
        errors = []
        for line in lines:
            lo = line.lower()
            if any(k in lo for k in ("error", "traceback", "exception", "❌", "failed:")):
                # Exclude expected/safe messages
                if any(s in line for s in (
                    "skipping", "not set", "No key", "no credentials",
                    "already sent", "never run", "(no queued",
                )):
                    continue
                errors.append(line.strip()[:120])
        if errors:
            sample = errors[-1]
            return False, f"Pipeline log has {len(errors)} error line(s) (24h). Last: {sample}"
        return True, "Pipeline log clean (24h)"
    except Exception as e:
        return False, f"Pipeline log read error: {e}"


# ── Main ───────────────────────────────────────────────────────────────────────

def run_health_check(quiet: bool = False) -> dict:
    """
    Run all checks and return a dict:
        {all_pass: bool, failures: [str], summary: str, checks: [dict]}
    """
    checks  = []
    failures = []

    def _record(ok: bool, label: str):
        checks.append({"ok": ok, "label": label})
        if not ok:
            failures.append(label)
        if not quiet:
            icon = "  ✓" if ok else "  ✗"
            print(f"{icon}  {label}")

    # 1. HTTP routes
    for route in ROUTES_TO_CHECK:
        ok, msg = _check_route(route)
        _record(ok, msg)

    # 2. DB
    ok, msg = _check_db()
    _record(ok, msg)

    # 3. LaunchAgents
    for ok, msg in _check_launchd():
        _record(ok, msg)

    # 4. Pipeline log
    ok, msg = _check_pipeline_log()
    _record(ok, msg)

    all_pass = len(failures) == 0
    if failures:
        summary = f"FAIL — {len(failures)} issue(s): " + "; ".join(failures[:3])
        if len(failures) > 3:
            summary += f" (+{len(failures)-3} more)"
    else:
        summary = "PASS — all checks green"

    return {
        "run_at":   datetime.now(timezone.utc).isoformat()[:16],
        "all_pass": all_pass,
        "failures": failures,
        "summary":  summary,
        "checks":   checks,
    }


if __name__ == "__main__":
    quiet = "--quiet" in sys.argv or "-q" in sys.argv

    if not quiet:
        print(f"\nBattleship Health Check — {datetime.now().strftime('%d %b %Y %H:%M')}")
        print("=" * 52)

    result = run_health_check(quiet=quiet)

    if not quiet:
        print("=" * 52)
        print(f"\n  {result['summary']}\n")

    sys.exit(0 if result["all_pass"] else 1)
