# Battleship — Feature Roadmap

*10 improvements identified March 2026. Build in order of impact.*

---

## 1. Win detection + celebration emails
**Impact:** Retention — clients feel seen in real-time
**Files:** `scripts/battleship_pipeline.py`

After Claude generates the tracker update, a second pass scans for PB signals and fires a short celebration email within minutes of check-in receipt.

```python
WIN_SIGNALS = [
    (r"new.*(?:best|record|max|pb)", "personal best"),
    (r"(?:lifted|pressed|squatted|deadlifted).*(?:first time|never before)", "first lift"),
    (r"(?:ran|walked|hit)\s+[\d,]+\s*steps.*(?:most|ever|best)", "step record"),
    (r"lost\s+[\d.]+\s*(?:kg|lbs|pounds|stone)", "weight drop"),
    (r"waist.*(?:down|smaller|lost)", "waist drop"),
]

def _detect_wins(parsed: dict, tracker_text: str) -> list[str]:
    combined = (parsed.get("free_text", "") + " " + tracker_text).lower()
    return [label for pattern, label in WIN_SIGNALS if re.search(pattern, combined)]
```

WIN_PROMPT asks Claude to write 3–4 sentences: warm, references the specific win, closes with what this means for the next 4 weeks. Email key stored as `win_wk{week}` in emails_sent.

---

## 2. Re-engagement for silent clients
**Impact:** Retention — recovers ~30–40% of clients who go quiet
**Files:** `scripts/battleship_pipeline.py`

New function `send_reengagement_emails()` called from `main()`. Two tiers:
- Day 10–16 silent → gentle nudge ("life gets in the way, just checking in")
- Day 17+ silent → personal note ("I noticed you went quiet, want to make sure you're ok")

```python
def send_reengagement_emails(state: dict, secrets: dict):
    today = datetime.now(timezone.utc).date()
    for slug, cs in state["clients"].items():
        if cs["status"] != "active":
            continue
        last_checkin = cs.get("last_checkin_received")
        days_silent = (today - datetime.fromisoformat(last_checkin).date()).days if last_checkin else 0
        week = cs.get("current_week", 1)
        if 10 <= days_silent < 17 and f"reengage_w{week}" not in cs.get("emails_sent", []):
            _send_reengage_nudge(cs, days_silent, "gentle", secrets)
        elif days_silent >= 17 and f"reengage_w{week}_2" not in cs.get("emails_sent", []):
            _send_reengage_nudge(cs, days_silent, "personal", secrets)
```

Both emails end with one clear CTA: "just reply with one word about how you're doing."

---

## 3. WhatsApp nudges via Twilio
**Impact:** Engagement — check-in response rates (email ~30%, WhatsApp ~98%)
**Files:** `scripts/whatsapp.py` (new), `scripts/battleship_pipeline.py`
**Cost:** ~£1/month + £0.05/message

New file `scripts/whatsapp.py`:
```python
from twilio.rest import Client

def send_whatsapp(to_number: str, message: str, secrets: dict):
    client = Client(secrets["TWILIO_ACCOUNT_SID"], secrets["TWILIO_AUTH_TOKEN"])
    client.messages.create(
        from_=f"whatsapp:{secrets['TWILIO_WHATSAPP_FROM']}",
        to=f"whatsapp:{to_number}",
        body=message
    )
```

Triggered in `send_weekly_checkin_requests()` after email send, if `cs["phone"]` is set. Phone number added as optional field to Tally intake form ("For WhatsApp reminders"). Stored as `cs["phone"]` in state.

---

## 4. Progress photo prompts + Week 12 comparison
**Impact:** Retention + Phase 2 conversion — visual proof is the #1 "it's working" signal
**Files:** `education-lessons/prompts/` (new folder), `scripts/battleship_pipeline.py`

Prompt files:
- `education-lessons/prompts/progress-photo-week4.md`
- `education-lessons/prompts/progress-photo-week8.md`
- `education-lessons/prompts/progress-photo-week12.md`

Appended to coach message at Weeks 4, 8, 12. Week 12 prompt references the Week 1 and Week 4 photos explicitly. The WEEK12_CLOSE_PROMPT is updated to reference photo comparison in the Phase 2 pitch.

```python
PHOTO_WEEKS = {4: "week4", 8: "week8", 12: "final"}

# In _process_single_checkin():
if week in PHOTO_WEEKS and f"photo_prompt_{PHOTO_WEEKS[week]}" not in cs.get("emails_sent", []):
    photo_content = (VAULT_ROOT / f"education-lessons/prompts/progress-photo-{PHOTO_WEEKS[week]}.md").read_text()
    body += f"\n\n---\n{photo_content}"
    cs["emails_sent"].append(f"photo_prompt_{PHOTO_WEEKS[week]}")
```

---

## 5. Waist measurement tracking
**Impact:** Retention — prevents early dropout when scale doesn't move but waist is dropping
**Files:** `scripts/battleship_pipeline.py`, Google Form (manual update)

Add "Waist measurement this week (cm, at navel, empty stomach)" to Google Form.

Pipeline changes:
- Parse `waist_cm` from check-in response
- Add Waist column to tracker table header
- CHECKIN_PROMPT updated: if waist dropping while weight flat, Claude explicitly calls this out as fat loss
- Win detection: waist drop ≥ 0.5cm triggers win email

```python
# In CHECKIN_PROMPT:
"""WAIST: {waist_cm}cm (prev: {prev_waist}cm, delta: {waist_delta:+.1f}cm)
If waist is dropping even when weight is flat — explicitly celebrate this.
Waist loss = fat loss. This is the real metric."""
```

---

## 6. Weekly digest email to Will
**Impact:** Operations — Monday morning push replaces ad-hoc dashboard checks
**Files:** `scripts/battleship_pipeline.py`

New function `send_weekly_digest()` called from `main()`. Fires Monday only (weekday check). Shows: all active clients, current week, days since last check-in, ⚠️ SILENT flag (>10 days), ★ P2 flag.

```python
def send_weekly_digest(state: dict, secrets: dict):
    if datetime.now(timezone.utc).weekday() != 0:
        return
    week_key = datetime.now(timezone.utc).strftime("%Y-%W")
    if "digest_" + week_key in state.get("sent_digests", []):
        return
    # ... build summary, send to will@battleship.me
    state.setdefault("sent_digests", []).append("digest_" + week_key)
```

---

## 7. Referral ask at Week 8
**Impact:** Acquisition — word-of-mouth from satisfied Week 8 client converts at ~60%
**Files:** `education-lessons/referral/week8-referral-ask.md` (new), `scripts/battleship_pipeline.py`

Appended to Week 8 coach message. Short, direct, non-pushy. "Forward this email" or link to battleshipreset.com. No referral code needed at this stage — just friction-free ask.

```python
# In _process_single_checkin(), week == 8:
if week == 8 and "referral_ask" not in cs.get("emails_sent", []):
    referral_content = (VAULT_ROOT / "education-lessons/referral/week8-referral-ask.md").read_text()
    body += f"\n\n---\n{referral_content}"
    cs["emails_sent"].append("referral_ask")
```

---

## 8. Testimonial capture at Week 11
**Impact:** Marketing + Phase 2 conversion — Week 11 stories are the best social proof
**Files:** `education-lessons/testimonial/week11-testimonial.md` (new), `scripts/battleship_pipeline.py`

Sent as a separate short email at Week 11 (not buried in coach message). Asks: "What's actually changed? What would you tell Week 1 you?" Reply stored as `cs["testimonial"]`. Dashboard shows ★ Testimonial badge.

```python
# In process_inbound_emails(), detect testimonial replies:
if cs.get("emails_sent") and "testimonial_ask" in cs["emails_sent"] and not cs.get("testimonial"):
    cs["testimonial"] = body_text
    cs["testimonial_received_at"] = datetime.utcnow().isoformat()
```

---

## 9. Client progress portal (token-authenticated)
**Impact:** Perceived value + engagement — something to bookmark, check, share
**Files:** `scripts/app.py`

New route `/progress/<token>` — publicly accessible via token URL, no login. Shows: name, current week badge, progress tracker, this week's sessions, next check-in link. Token generated at enrolment, included in onboarding email.

```python
@app.route("/progress/<token>")
def client_portal(token):
    state = load_state()
    cs = next((c for c in state["clients"].values() if c.get("portal_token") == token), None)
    if not cs:
        return "Not found", 404
    # render tracker + current week session + next check-in CTA
```

Portal URL format: `https://webhook.battleshipreset.com/progress/{token}`

---

## 10. Automated Phase 2 Stripe link on detection
**Impact:** Revenue — closes deal while client is still in the buying moment
**Files:** `scripts/battleship_pipeline.py`, `~/.battleship.env`

When `process_inbound_emails()` detects Phase 2 keywords, immediately send Stripe payment link rather than just flagging for manual action. Guard: `cs["phase2_stripe_sent"]` prevents double-send.

```python
if detected_phase2 and not cs.get("phase2_stripe_sent"):
    send_email(
        cs["email"],
        f"Phase 2 — you're in, {cs['name'].split()[0]}",
        PHASE2_EMAIL.format(name=..., stripe_link=secrets["STRIPE_PHASE2_LINK"]),
        secrets
    )
    cs["phase2_stripe_sent"] = True
    cs["phase2_stripe_sent_at"] = datetime.utcnow().isoformat()
```

Add to `~/.battleship.env`: `STRIPE_PHASE2_LINK=https://buy.stripe.com/...`

---

## Build order

| Priority | Feature | Effort | Impact |
|----------|---------|--------|--------|
| 1 | #2 Re-engagement emails | Low | High — stops silent churn |
| 2 | #6 Weekly digest to Will | Low | High — ops visibility |
| 3 | #10 Phase 2 auto-Stripe | Low | High — closes revenue |
| 4 | #5 Waist tracking | Medium | High — retention |
| 5 | #1 Win detection | Medium | High — retention |
| 6 | #7 Referral ask | Low | High — acquisition |
| 7 | #8 Testimonial capture | Low | Medium — marketing |
| 8 | #4 Photo prompts | Low | Medium — Phase 2 conversion |
| 9 | #3 WhatsApp | Medium | High — but needs Twilio setup |
| 10 | #9 Client portal | High | Medium — nice to have |
