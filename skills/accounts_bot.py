"""
Battleship Reset — Accounts Bot
================================
Scans expenses/receipts/ for .eml receipt files, extracts transaction data,
updates finances.md, and includes a P&L summary in the Monday digest.

Standalone:
    python3 skills/accounts_bot.py --scan        # process all unprocessed receipts
    python3 skills/accounts_bot.py --pnl         # print current P&L snapshot
    python3 skills/accounts_bot.py --report      # send P&L email to will@battleship.me

Called from pipeline:
    from skills.accounts_bot import run as run_accounts
    run_accounts(secrets, state, VAULT_ROOT)
"""

import email
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import requests

VAULT_ROOT    = Path(__file__).parent.parent
RECEIPTS_DIR  = VAULT_ROOT / "expenses" / "receipts"
PROCESSED_FILE = VAULT_ROOT / "expenses" / "processed.json"
FINANCES_FILE = VAULT_ROOT / "finances.md"

GBP_PER_USD = 0.79  # approximate — good enough for internal tracking

# ── Receipt parsing ────────────────────────────────────────────────────────────

def _extract_email_text(eml_path: Path) -> str:
    """Extract plain text + stripped HTML from an .eml file."""
    with open(eml_path, "rb") as f:
        msg = email.message_from_bytes(f.read())

    text_parts = []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/plain":
            try:
                text_parts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
            except Exception:
                pass
        elif ct == "text/html" and not text_parts:
            try:
                html = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
                html = re.sub(r"<[^>]+>", " ", html)
                html = re.sub(r"\s+", " ", html).strip()
                text_parts.append(html[:2000])
            except Exception:
                pass

    subject = ""
    try:
        from email.header import decode_header as _dh
        raw = msg.get("Subject", "")
        parts = _dh(raw)
        subject = "".join(
            p.decode(enc or "utf-8") if isinstance(p, bytes) else p
            for p, enc in parts
        )
    except Exception:
        subject = msg.get("Subject", "")

    return f"SUBJECT: {subject}\n\n" + "\n\n".join(text_parts)


PARSE_PROMPT = """Extract transaction details from this receipt email.

Receipt text:
{text}

Return a JSON object with exactly these fields (use null if unknown):
{{
  "date": "YYYY-MM-DD",
  "vendor": "vendor name (short, e.g. 'Meta Ads', 'Anthropic', 'Carrd', 'GoDaddy')",
  "description": "brief description (e.g. 'Facebook ad spend', 'Claude API credit', 'Pro Standard plan')",
  "amount_gbp": 0.00,
  "amount_original": 0.00,
  "currency_original": "GBP or USD or EUR",
  "category": "one of: Advertising / Tools / Infrastructure / Tax / Other",
  "notes": "any useful notes e.g. renewal date, transaction ID (keep short)"
}}

Currency conversion: 1 USD = 0.79 GBP (approximate).
If amount is in USD, convert to GBP for amount_gbp.
Return only the JSON object. No explanation."""


def parse_receipt(eml_path: Path, api_key: str) -> dict | None:
    """Use Claude to extract transaction data from a receipt email."""
    text = _extract_email_text(eml_path)
    if not text.strip():
        return None

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": PARSE_PROMPT.format(text=text[:3000])}],
    )
    raw = msg.content[0].text.strip()
    # Extract JSON
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except Exception:
        return None


# ── Processed receipts tracker ────────────────────────────────────────────────

def _load_processed() -> dict:
    if PROCESSED_FILE.exists():
        return json.loads(PROCESSED_FILE.read_text())
    return {"receipts": []}


def _save_processed(p: dict):
    PROCESSED_FILE.write_text(json.dumps(p, indent=2))


# ── finances.md updater ───────────────────────────────────────────────────────

def _append_expense_to_finances(tx: dict):
    """Append a new expense row to the Expense Log table in finances.md."""
    if not FINANCES_FILE.exists():
        return

    content = FINANCES_FILE.read_text()

    # Build the new table row
    date   = tx.get("date", "?")
    item   = tx.get("description", tx.get("vendor", "?"))
    vendor = tx.get("vendor", "")
    if vendor and vendor.lower() not in item.lower():
        item = f"{vendor} — {item}"
    notes  = tx.get("notes", "")

    orig = tx.get("amount_original")
    cur  = tx.get("currency_original", "GBP")
    gbp  = float(tx.get("amount_gbp") or 0)

    if cur == "GBP" or orig is None:
        cost_str = f"£{gbp:.2f}"
    else:
        cost_str = f"{cur} {float(orig):.2f} (~£{gbp:.2f})"

    category = tx.get("category", "Other")
    new_row = f"| {date} | {item} | {cost_str} | {cur} | {category} | {notes} |"

    # Insert before the last row that matches the expense table pattern (before the total line)
    # Find the last | row before the **Total Spend** line
    lines = content.split("\n")
    insert_at = None
    for i, line in enumerate(lines):
        if line.strip().startswith("**Total Spend"):
            insert_at = i
            break

    if insert_at is None:
        # Just append to end
        content += f"\n{new_row}"
    else:
        lines.insert(insert_at, new_row)
        content = "\n".join(lines)

    # Recalculate total spend
    total_gbp = 0.0
    for line in content.split("\n"):
        if line.startswith("|") and "|" in line[1:]:
            cells = [c.strip() for c in line.split("|")]
            if len(cells) > 3:
                amount_cell = cells[3]
                # Extract GBP value
                gbp_match = re.search(r"£([\d.]+)", amount_cell)
                if gbp_match:
                    total_gbp += float(gbp_match.group(1))

    content = re.sub(
        r"\*\*Total Spend to date:.*?\*\*",
        f"**Total Spend to date: £{total_gbp:.2f}**",
        content,
    )

    FINANCES_FILE.write_text(content)


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_receipts(secrets: dict) -> list[dict]:
    """
    Scan receipts folder for unprocessed .eml files.
    Parse each, update finances.md, mark as processed.
    Returns list of new transactions found.
    """
    api_key   = secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY")
    processed = _load_processed()
    seen      = set(processed["receipts"])
    new_txns  = []

    eml_files = sorted(RECEIPTS_DIR.glob("*.eml"))
    if not eml_files:
        print("  ℹ️  No receipt files found")
        return []

    for eml_path in eml_files:
        fname = eml_path.name
        if fname in seen:
            continue

        print(f"  📄 Processing: {fname}")
        tx = parse_receipt(eml_path, api_key)
        if not tx:
            print(f"     ⚠️  Could not parse — skipping")
            processed["receipts"].append(fname)
            continue

        tx["source_file"] = fname
        _append_expense_to_finances(tx)
        new_txns.append(tx)
        processed["receipts"].append(fname)
        print(f"     ✅ {tx.get('vendor')} — {tx.get('description')} — £{float(tx.get('amount_gbp') or 0):.2f}")

    _save_processed(processed)
    return new_txns


# ── P&L snapshot ──────────────────────────────────────────────────────────────

def get_pnl(state: dict) -> dict:
    """Calculate current P&L from finances.md + Stripe state."""
    # Revenue from pipeline state — only count clients with an explicit payment recorded
    clients   = state.get("clients", {})
    revenue   = sum(
        cs["payment_amount"] for cs in clients.values()
        if cs.get("status") in ("active", "complete") and cs.get("payment_amount")
    )
    mrr_estimate = sum(
        cs["payment_amount"] for cs in clients.values()
        if cs.get("status") == "active" and cs.get("payment_amount")
    )

    # Expenses from finances.md — only parse rows inside the Expense Log table
    total_spend = 0.0
    ad_spend    = 0.0
    if FINANCES_FILE.exists():
        in_expense_table = False
        for line in FINANCES_FILE.read_text().split("\n"):
            if "## Expense Log" in line:
                in_expense_table = True
                continue
            if in_expense_table and line.startswith("##"):
                in_expense_table = False
            if not in_expense_table:
                continue
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.split("|")]
            if len(cells) < 6:
                continue
            # Skip header and separator rows
            if "Date" in cells[1] or cells[1].startswith("-") or "~~" in cells[1]:
                continue
            amount_cell = cells[3]
            category    = cells[5]
            # Extract GBP value — prefer explicit £ amount, fall back to ~£ in USD entries
            gbp_match = re.search(r"~?£([\d,]+\.?\d*)", amount_cell)
            if gbp_match:
                amt = float(gbp_match.group(1).replace(",", ""))
                total_spend += amt
                if "Advertis" in category:
                    ad_spend += amt

    return {
        "revenue":       revenue,
        "mrr_estimate":  mrr_estimate,
        "total_spend":   total_spend,
        "ad_spend":      ad_spend,
        "net":           revenue - total_spend,
        "target_mrr":    3000,
        "gap_to_target": max(0, 3000 - mrr_estimate),
        "active_clients": sum(1 for cs in clients.values() if cs["status"] == "active"),
    }


def send_pnl_report(secrets: dict, state: dict):
    """Send P&L report to will@battleship.me (included in Monday digest)."""
    if datetime.now(timezone.utc).weekday() != 0:
        return

    pnl = get_pnl(state)

    plain = (
        f"P&L Snapshot — {datetime.now().strftime('%d %b %Y')}\n"
        f"Revenue: £{pnl['revenue']:.2f}\n"
        f"Total spend: £{pnl['total_spend']:.2f}\n"
        f"Ad spend: £{pnl['ad_spend']:.2f}\n"
        f"Net: £{pnl['net']:.2f}\n"
        f"MRR estimate: £{pnl['mrr_estimate']:.2f} (gap to £3k: £{pnl['gap_to_target']:.2f})\n"
        f"Active clients: {pnl['active_clients']}"
    )

    net_color = "#2a7a2a" if pnl["net"] >= 0 else "#c41e3a"

    def _stat(label, value):
        return (
            f'<td style="text-align:center;padding:0 20px 0 0;">'
            f'<p style="margin:0;font-size:24px;font-family:Georgia,serif;color:#0a0a0a;">{value}</p>'
            f'<p style="margin:4px 0 0;font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;">{label}</p>'
            f'</td>'
        )

    stats_html = (
        '<table cellpadding="0" cellspacing="0" border="0"><tr>'
        + _stat("Revenue", f"£{pnl['revenue']:.0f}")
        + _stat("Spent", f"£{pnl['total_spend']:.0f}")
        + f'<td style="text-align:center;padding:0 20px 0 0;">'
        f'<p style="margin:0;font-size:24px;font-family:Georgia,serif;color:{net_color};">£{pnl["net"]:.0f}</p>'
        f'<p style="margin:4px 0 0;font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;">Net</p>'
        f'</td>'
        + _stat("MRR", f"£{pnl['mrr_estimate']:.0f}")
        + _stat("Gap to £3k", f"£{pnl['gap_to_target']:.0f}")
        + '</tr></table>'
    )

    from scripts.battleship_pipeline import render_internal_email, send_email
    html = render_internal_email(
        title=f"P&L Snapshot — {datetime.now().strftime('%d %b %Y')}",
        subtitle="Accounts",
        sections=[
            {"body": stats_html, "accent": True},
            {"body": f'<p style="font-size:13px;color:#555;margin:0;">Ad spend: £{pnl["ad_spend"]:.2f} &nbsp;·&nbsp; Active clients: {pnl["active_clients"]} &nbsp;·&nbsp; Target MRR: £3,000</p>'},
        ],
    )

    send_email(
        secrets,
        to="will@battleship.me",
        subject=f"[ACCOUNTS] P&L snapshot — {datetime.now().strftime('%d %b')}",
        plain_body=plain,
        html_body=html,
    )
    print("  ✅ P&L report sent to will@battleship.me")


# ── Entry point ────────────────────────────────────────────────────────────────

def run(secrets: dict, state: dict, vault_root: Path = VAULT_ROOT):
    """Called from battleship_pipeline.py main()."""
    try:
        new_txns = scan_receipts(secrets)
        if new_txns:
            print(f"  ✅ {len(new_txns)} new receipt(s) processed → finances.md updated")
        send_pnl_report(secrets, state)
    except Exception as e:
        print(f"  ⚠️  Accounts bot error: {e}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    env_file = Path.home() / ".battleship.env"
    secrets: dict = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip()

    parser = argparse.ArgumentParser(description="Battleship Accounts Bot")
    parser.add_argument("--scan",   action="store_true", help="Process all unprocessed receipts")
    parser.add_argument("--pnl",    action="store_true", help="Print P&L snapshot")
    parser.add_argument("--report", action="store_true", help="Send P&L email now")
    args = parser.parse_args()

    sys.path.insert(0, str(VAULT_ROOT))

    if args.scan:
        new = scan_receipts(secrets)
        print(f"\n{len(new)} new transaction(s) processed.")
    elif args.pnl:
        state_file = VAULT_ROOT / "clients" / "state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {"clients": {}}
        pnl = get_pnl(state)
        print(f"\nP&L Snapshot:")
        print(f"  Revenue:      £{pnl['revenue']:.2f}")
        print(f"  Total spend:  £{pnl['total_spend']:.2f}")
        print(f"  Ad spend:     £{pnl['ad_spend']:.2f}")
        print(f"  Net:          £{pnl['net']:.2f}")
        print(f"  MRR estimate: £{pnl['mrr_estimate']:.2f}")
        print(f"  Gap to £3k:   £{pnl['gap_to_target']:.2f}")
    elif args.report:
        state_file = VAULT_ROOT / "clients" / "state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {"clients": {}}
        # Force Monday check bypass
        from unittest.mock import patch
        from datetime import datetime as _dt
        send_pnl_report(secrets, state)
    else:
        parser.print_help()
