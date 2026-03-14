"""
Battleship Reset — Facebook Ads Bot
=====================================
Automates campaign creation, daily performance monitoring, and budget optimisation
via the Meta Marketing API.

SETUP REQUIRED (one-time):
  ~/.battleship.env:
    FB_AD_ACCOUNT_ID=<number from Ads Manager — no "act_" prefix>
    FB_USER_TOKEN=<user access token with ads_management + ads_read scopes>

  Meta app (Battleship-Reset) needs these permissions:
    ads_management, ads_read, business_management

USAGE:
  # Launch smoke test (£7/day for 7 days):
  python3 skills/facebook_ads_bot.py --smoke-test

  # Run daily optimisation (called by pipeline):
  python3 skills/facebook_ads_bot.py --optimise

  # Show current campaign performance:
  python3 skills/facebook_ads_bot.py --report
"""

import requests
import json
import sys
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

GRAPH_BASE = "https://graph.facebook.com/v22.0"
VAULT_ROOT  = Path("/Users/will/Obsidian-Vaults/BattleShip-Vault")
ENV_FILE    = Path.home() / ".battleship.env"

# ── Performance thresholds ────────────────────────────────────────────────────
# Evaluated only after 500+ impressions — no premature pausing

MIN_CTR         = 0.008   # 0.8% — pause if below (cold UK traffic norm is ~1%)
MAX_CPR         = 30.0    # £30 cost-per-result — pause if above
SCALE_CTR       = 0.025   # 2.5% — scale budget if at or above
SCALE_CPR       = 15.0    # £15 cost-per-result — scale if at or below
BUDGET_SCALE    = 1.25    # increase budget by 25% per scaling step
MIN_IMPRESSIONS = 500     # don't act on data below this threshold

# ── Ad copy — Will's story ─────────────────────────────────────────────────────
AD_COPY = {
    "headline": "The Battleship Reset",
    "body": (
        "I was 47, fitness age 55, blood pressure heading the wrong way, "
        "and a holiday photo in August 2024 made it impossible to ignore anymore.\n\n"
        "I didn't join a gym. I started walking.\n\n"
        "20km a day, every single day. Month 5 I added weights at lunch. "
        "9 months later: fitness age 17, blood pressure normal, all the weight gone.\n\n"
        "I've turned what I did into a structured 12-week programme for men 40-60 "
        "who want to actually sort it out. Not a crash diet. Not a bootcamp. "
        "A reset that works with your life.\n\n"
        "Fill in a short form and I'll send you a personalised report."
    ),
    "link": "https://tally.so/r/rjK752",
    "cta": "LEARN_MORE",
}

# Image to use for the ad — cliff path photo is the best option
DEFAULT_IMAGE = str(VAULT_ROOT / "brand/random-snaps/IMG_0448.jpeg")


# ── API helpers ───────────────────────────────────────────────────────────────

def _get(endpoint: str, params: dict, token: str) -> dict:
    r = requests.get(
        f"{GRAPH_BASE}/{endpoint}",
        params={"access_token": token, **params},
        timeout=20,
    )
    if not r.ok:
        print(f"  FB API error: {r.status_code} {r.text[:300]}")
    r.raise_for_status()
    return r.json()


def _post(endpoint: str, data: dict, token: str) -> dict:
    r = requests.post(
        f"{GRAPH_BASE}/{endpoint}",
        data={"access_token": token, **data},
        timeout=20,
    )
    if not r.ok:
        print(f"  FB API error: {r.status_code} {r.text[:300]}")
    r.raise_for_status()
    return r.json()


# ── Campaign creation ─────────────────────────────────────────────────────────

def create_campaign(ad_account_id: str, name: str, token: str) -> dict:
    """Create a PAUSED traffic campaign."""
    return _post(f"act_{ad_account_id}/campaigns", {
        "name": name,
        "objective": "OUTCOME_TRAFFIC",
        "status": "PAUSED",
        "special_ad_categories": "[]",
    }, token)


def create_adset(ad_account_id: str, campaign_id: str, name: str,
                 daily_budget_pence: int, token: str) -> dict:
    """Create an ad set targeting UK men 40-60 for 7 days."""
    targeting = json.dumps({
        "geo_locations": {"countries": ["GB"]},
        "age_min": 40,
        "age_max": 60,
        "genders": [1],  # 1 = male
        "flexible_spec": [{
            "interests": [
                {"id": "6003107902433", "name": "Fitness and wellness"},
                {"id": "6003020834693", "name": "Weight loss"},
                {"id": "6002910373627", "name": "Health"},
                {"id": "6003348604981", "name": "Physical exercise"},
            ]
        }]
    })
    start = datetime.now(timezone.utc)
    end   = start + timedelta(days=7)
    return _post(f"act_{ad_account_id}/adsets", {
        "name":              name,
        "campaign_id":       campaign_id,
        "daily_budget":      daily_budget_pence,
        "billing_event":     "IMPRESSIONS",
        "optimization_goal": "LINK_CLICKS",
        "targeting":         targeting,
        "start_time":        start.strftime("%Y-%m-%dT%H:%M:%S+0000"),
        "end_time":          end.strftime("%Y-%m-%dT%H:%M:%S+0000"),
        "status":            "PAUSED",
    }, token)


def upload_image(ad_account_id: str, image_path: str, token: str) -> str:
    """Upload an image file and return its hash."""
    with open(image_path, "rb") as f:
        r = requests.post(
            f"{GRAPH_BASE}/act_{ad_account_id}/adimages",
            files={"filename": (Path(image_path).name, f)},
            data={"access_token": token},
            timeout=30,
        )
        if not r.ok:
            print(f"  Image upload error: {r.status_code} {r.text[:300]}")
        r.raise_for_status()
    images = r.json().get("images", {})
    for _, info in images.items():
        return info["hash"]
    raise RuntimeError("Image upload returned no hash")


def create_ad_creative(ad_account_id: str, page_id: str, headline: str,
                       body: str, image_hash: str, link: str,
                       cta: str, token: str) -> dict:
    """Create an ad creative."""
    story_spec = json.dumps({
        "page_id": page_id,
        "link_data": {
            "image_hash": image_hash,
            "link":       link,
            "message":    body,
            "name":       headline,
            "call_to_action": {
                "type":  cta,
                "value": {"link": link},
            },
        },
    })
    return _post(f"act_{ad_account_id}/adcreatives", {
        "name":              f"BSR — {headline}",
        "object_story_spec": story_spec,
    }, token)


def create_ad(ad_account_id: str, adset_id: str, creative_id: str,
              name: str, token: str) -> dict:
    """Create the ad (starts PAUSED — activated when campaign goes ACTIVE)."""
    return _post(f"act_{ad_account_id}/ads", {
        "name":     name,
        "adset_id": adset_id,
        "creative": json.dumps({"creative_id": creative_id}),
        "status":   "PAUSED",
    }, token)


def activate_campaign(campaign_id: str, token: str):
    return _post(campaign_id, {"status": "ACTIVE"}, token)


def pause_ad(ad_id: str, token: str):
    return _post(ad_id, {"status": "PAUSED"}, token)


def update_adset_budget(adset_id: str, new_daily_pence: int, token: str):
    return _post(adset_id, {"daily_budget": new_daily_pence}, token)


# ── Smoke test launcher ───────────────────────────────────────────────────────

def launch_smoke_test(ad_account_id: str, page_id: str,
                      image_path: str, daily_budget_gbp: float,
                      token: str) -> dict:
    """Launch the first smoke-test campaign and return IDs."""
    daily_pence = int(daily_budget_gbp * 100)
    name_ts     = datetime.now().strftime("%b %Y")

    print(f"\n  🚀 Launching BSR smoke test — £{daily_budget_gbp:.0f}/day for 7 days...")

    campaign = create_campaign(ad_account_id, f"BSR Smoke Test — {name_ts}", token)
    cid = campaign["id"]
    print(f"  📋 Campaign: {cid}")

    adset = create_adset(ad_account_id, cid, "UK Men 40-60", daily_pence, token)
    asid  = adset["id"]
    print(f"  🎯 Ad set: {asid}")

    img_hash = upload_image(ad_account_id, image_path, token)
    print(f"  🖼  Image hash: {img_hash}")

    creative = create_ad_creative(
        ad_account_id, page_id,
        AD_COPY["headline"], AD_COPY["body"],
        img_hash, AD_COPY["link"], AD_COPY["cta"], token,
    )
    crid = creative["id"]
    print(f"  🎨 Creative: {crid}")

    ad = create_ad(ad_account_id, asid, crid, "Will's story — v1", token)
    adid = ad["id"]
    print(f"  ✅ Ad: {adid}")

    activate_campaign(cid, token)
    print(f"  ▶️  Campaign ACTIVE")

    return {"campaign_id": cid, "adset_id": asid, "ad_id": adid}


# ── Performance monitoring ────────────────────────────────────────────────────

def get_ads_with_insights(ad_account_id: str, token: str) -> list[dict]:
    """Return all active/paused ads with 7-day performance data."""
    data = _get(f"act_{ad_account_id}/ads", {
        "fields": (
            "id,name,status,adset_id,"
            "insights.date_preset(last_7d)"
            "{impressions,clicks,ctr,spend,actions,cost_per_action_type}"
        ),
        "limit": 50,
    }, token)
    return data.get("data", [])


def _parse_insights(ad: dict) -> dict:
    """Extract key metrics from an ad's insights block."""
    raw = (ad.get("insights") or {}).get("data", [{}])
    ins = raw[0] if raw else {}

    impressions = int(ins.get("impressions", 0))
    clicks      = int(ins.get("clicks", 0))
    spend       = float(ins.get("spend", 0))
    ctr_pct     = float(ins.get("ctr", 0))
    ctr         = ctr_pct / 100  # Meta returns as percentage string

    # Count link clicks or lead events as "results"
    results = 0
    for action in ins.get("actions", []):
        if action.get("action_type") in (
            "link_click",
            "offsite_conversion.fb_pixel_lead",
            "onsite_conversion.lead_grouped",
        ):
            results += int(action.get("value", 0))

    cpr = spend / results if results > 0 else None

    return {
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "spend": spend,
        "results": results,
        "cpr": cpr,
    }


# ── Daily optimisation ────────────────────────────────────────────────────────

def optimise(ad_account_id: str, token: str, dry_run: bool = False) -> list[str]:
    """
    Evaluate all active ads and take action:
    - Pause if CTR < MIN_CTR (after 500+ impressions)
    - Scale budget if CTR > SCALE_CTR and CPR < SCALE_CPR
    - Leave alone otherwise
    Returns a list of action strings for the digest email.
    """
    ads = get_ads_with_insights(ad_account_id, token)
    log = []

    for ad in ads:
        if ad.get("status") not in ("ACTIVE", "PAUSED"):
            continue

        m    = _parse_insights(ad)
        name = ad["name"]

        if m["impressions"] < MIN_IMPRESSIONS:
            log.append(f"  ⏳ {name}: {m['impressions']} impressions — waiting")
            continue

        # Fetch current adset budget
        asid    = ad["adset_id"]
        as_data = _get(asid, {"fields": "daily_budget,name"}, token)
        budget  = int(as_data.get("daily_budget", 700))  # pence

        ctr_pct   = f"{m['ctr']:.1%}"
        spend_str = f"£{m['spend']:.2f}"
        cpr_str   = f"£{m['cpr']:.0f}" if m['cpr'] else "n/a"

        if m["ctr"] < MIN_CTR:
            if not dry_run:
                pause_ad(ad["id"], token)
            log.append(
                f"  ⏸ PAUSED: {name} — CTR {ctr_pct} (below {MIN_CTR:.0%}) | "
                f"spend {spend_str} | {m['impressions']} impressions"
            )

        elif m["ctr"] >= SCALE_CTR and (m["cpr"] is None or m["cpr"] <= SCALE_CPR):
            new_budget = int(budget * BUDGET_SCALE)
            if not dry_run:
                update_adset_budget(asid, new_budget, token)
            log.append(
                f"  📈 SCALED: {name} — CTR {ctr_pct}, CPR {cpr_str} | "
                f"budget £{budget/100:.0f} → £{new_budget/100:.0f}/day"
            )

        else:
            log.append(
                f"  ✅ OK: {name} — CTR {ctr_pct} | spend {spend_str} | "
                f"results {m['results']} | CPR {cpr_str}"
            )

    return log


# ── Report ────────────────────────────────────────────────────────────────────

def report(ad_account_id: str, token: str):
    """Print a formatted performance report."""
    ads = get_ads_with_insights(ad_account_id, token)
    print(f"\n{'='*60}")
    print(f"  Battleship Ads Report — {datetime.now().strftime('%d %b %Y')}")
    print(f"{'='*60}")
    for ad in ads:
        m = _parse_insights(ad)
        print(f"\n  Ad: {ad['name']}")
        print(f"  Status: {ad.get('status')}")
        print(f"  Impressions: {m['impressions']:,}")
        print(f"  Clicks:      {m['clicks']:,}  (CTR {m['ctr']:.2%})")
        print(f"  Spend:       £{m['spend']:.2f}")
        print(f"  Results:     {m['results']}  (CPR £{m['cpr']:.0f})" if m['cpr'] else f"  Results:     {m['results']}")
    print(f"\n{'='*60}\n")


# ── Pipeline entry point (called by battleship_pipeline.py) ───────────────────

def run(secrets: dict, vault_root: Path):
    """Daily optimisation run — called from main pipeline."""
    ad_account_id = secrets.get("fb_ad_account_id", "")
    token         = secrets.get("fb_user_token", "") or secrets.get("fb_page_access_token", "")

    if not ad_account_id:
        print("  (FB_AD_ACCOUNT_ID not set — skipping ads bot)")
        return
    if not token:
        print("  (FB token not set — skipping ads bot)")
        return

    actions = optimise(ad_account_id, token)
    for a in actions:
        print(a)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load_env() -> dict:
    if not ENV_FILE.exists():
        return {}
    result = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip().lower()] = v.strip()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Battleship Facebook Ads Bot")
    parser.add_argument("--smoke-test",  action="store_true", help="Launch smoke test campaign")
    parser.add_argument("--optimise",    action="store_true", help="Run daily optimisation")
    parser.add_argument("--report",      action="store_true", help="Show performance report")
    parser.add_argument("--budget",      type=float, default=7.0, help="Daily budget in £ (default: 7)")
    parser.add_argument("--image",       type=str, default=DEFAULT_IMAGE, help="Path to ad image")
    parser.add_argument("--dry-run",     action="store_true", help="Show actions without executing")
    args = parser.parse_args()

    env = _load_env()
    token         = env.get("fb_user_token") or env.get("fb_page_access_token", "")
    ad_account_id = env.get("fb_ad_account_id", "")
    page_id       = env.get("fb_page_id", "")

    if not token:
        print("❌ FB_USER_TOKEN not set in ~/.battleship.env")
        sys.exit(1)
    if not ad_account_id:
        print("❌ FB_AD_ACCOUNT_ID not set in ~/.battleship.env")
        sys.exit(1)

    if args.smoke_test:
        ids = launch_smoke_test(ad_account_id, page_id, args.image, args.budget, token)
        print(f"\n  Smoke test IDs: {ids}")

    elif args.optimise:
        actions = optimise(ad_account_id, token, dry_run=args.dry_run)
        for a in actions:
            print(a)

    elif args.report:
        report(ad_account_id, token)

    else:
        parser.print_help()
