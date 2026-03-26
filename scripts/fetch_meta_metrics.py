"""
fetch_meta_metrics.py — Daily Meta API sync
Writes to:  clients/social_metrics.json
Updates:    clients/marketing_strategy.json → last_ad_metrics
            brand/Marketing/tech_backlog.json → gap_009 status

Run: python3 scripts/fetch_meta_metrics.py
Cron: already included in daily pipeline run
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import urllib.request as _req
    import urllib.parse as _parse
except ImportError:
    sys.exit("urllib not available")

VAULT_ROOT = Path(__file__).parent.parent
CLIENTS_DIR = VAULT_ROOT / "clients"
SOCIAL_METRICS_FILE = CLIENTS_DIR / "social_metrics.json"
MARKETING_STRATEGY_FILE = CLIENTS_DIR / "marketing_strategy.json"
TECH_BACKLOG_FILE = VAULT_ROOT / "brand" / "Marketing" / "tech_backlog.json"
ENV_FILE = Path.home() / ".battleship.env"

GRAPH_BASE = "https://graph.facebook.com/v22.0"


def _load_env() -> dict:
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def _get(url: str) -> dict:
    try:
        with _req.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ⚠ GET failed: {url[:80]}... — {e}")
        return {}


def _load_json(path: Path, default=None) -> dict:
    if default is None:
        default = {}
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def fetch_page_stats(page_id: str, page_token: str) -> dict:
    url = f"{GRAPH_BASE}/{page_id}?fields=fan_count,followers_count,name&access_token={page_token}"
    data = _get(url)
    return {
        "fans": data.get("fan_count", 0),
        "followers": data.get("followers_count", 0),
    }


def fetch_ig_stats(ig_id: str, page_token: str) -> dict:
    url = (f"{GRAPH_BASE}/{ig_id}?fields=followers_count,follows_count,"
           f"media_count,username&access_token={page_token}")
    data = _get(url)
    return {
        "followers_count": data.get("followers_count", 0),
        "follows_count": data.get("follows_count", 0),
        "media_count": data.get("media_count", 0),
        "username": data.get("username", ""),
    }


def fetch_ad_insights(ad_account: str, user_token: str) -> dict:
    """Pull 7-day aggregate insights across all active Battleship campaigns."""
    # Get active campaigns
    campaigns_url = (f"{GRAPH_BASE}/{ad_account}/campaigns"
                     f"?fields=id,name,status,objective,daily_budget,lifetime_budget,"
                     f"budget_remaining,start_time,stop_time"
                     f"&access_token={user_token}")
    campaigns_data = _get(campaigns_url)
    campaigns = campaigns_data.get("data", [])

    # Filter to Battleship campaigns (exclude old marketplace listings)
    bsr_campaigns = [c for c in campaigns if "Battleship" in c.get("name", "")
                     or "tally.so" in c.get("name", "")
                     or "I was 47" in c.get("name", "")]

    total = {
        "impressions": 0, "reach": 0, "clicks": 0,
        "link_clicks": 0, "landing_page_views": 0, "spend": 0.0,
        "campaigns_active": 0,
        "campaigns": [],
    }

    for c in bsr_campaigns:
        if c.get("status") == "ACTIVE":
            total["campaigns_active"] += 1

        ins_url = (f"{GRAPH_BASE}/{c['id']}/insights"
                   f"?fields=impressions,reach,clicks,spend,cpc,cpm,ctr,actions"
                   f"&date_preset=last_7d&access_token={user_token}")
        ins_data = _get(ins_url)
        rows = ins_data.get("data", [])

        camp_impressions = 0
        camp_clicks = 0
        camp_spend = 0.0
        camp_link_clicks = 0
        camp_lp_views = 0

        for row in rows:
            camp_impressions += int(row.get("impressions", 0))
            camp_clicks += int(row.get("clicks", 0))
            camp_spend += float(row.get("spend", 0) or 0)
            for action in row.get("actions", []):
                if action["action_type"] == "link_click":
                    camp_link_clicks += int(action["value"])
                elif action["action_type"] == "landing_page_view":
                    camp_lp_views += int(action["value"])

        total["impressions"] += camp_impressions
        total["reach"] += int(rows[0].get("reach", 0)) if rows else 0
        total["clicks"] += camp_clicks
        total["link_clicks"] += camp_link_clicks
        total["landing_page_views"] += camp_lp_views
        total["spend"] = round(total["spend"] + camp_spend, 2)

        total["campaigns"].append({
            "id": c["id"],
            "name": c["name"],
            "objective": c.get("objective", ""),
            "status": c.get("status", ""),
            "daily_budget": c.get("daily_budget"),
            "lifetime_budget": c.get("lifetime_budget"),
            "budget_remaining": c.get("budget_remaining"),
            "stop_time": c.get("stop_time"),
            "impressions": camp_impressions,
            "clicks": camp_clicks,
            "spend": str(round(camp_spend, 2)),
        })

    # Derived metrics
    if total["impressions"] > 0:
        total["ctr"] = round(total["clicks"] / total["impressions"] * 100, 2)
        total["cpm"] = round(total["spend"] / total["impressions"] * 1000, 2)
    else:
        total["ctr"] = 0.0
        total["cpm"] = 0.0

    if total["clicks"] > 0:
        total["cpc"] = round(total["spend"] / total["clicks"], 3)
    else:
        total["cpc"] = 0.0

    total["spend"] = str(total["spend"])
    total["fetched_at"] = datetime.now(timezone.utc).isoformat()

    return total


def fetch_recent_posts(page_id: str, page_token: str, limit: int = 5) -> dict:
    url = (f"{GRAPH_BASE}/{page_id}/posts"
           f"?fields=id,message,created_time,permalink_url"
           f"&limit={limit}&access_token={page_token}")
    data = _get(url)
    posts = {}
    for post in data.get("data", []):
        posts[post["id"]] = {
            "message": (post.get("message", "") or "")[:200],
            "created_time": post.get("created_time", ""),
            "permalink": post.get("permalink_url", ""),
            "insights": {"reach": 0, "link_clicks": 0},
        }
    return posts


def update_tech_backlog(ad_data: dict):
    """Update gap_009 status based on whether campaigns are active."""
    backlog = _load_json(TECH_BACKLOG_FILE, {"gaps": []})
    for gap in backlog.get("gaps", []):
        if gap["id"] == "gap_009":
            active = ad_data.get("campaigns_active", 0)
            impr = ad_data.get("impressions", 0)
            spend = ad_data.get("spend", "0")
            if active > 0:
                gap["status"] = "workaround_active"
                gap["impact"] = "high"
                gap["description"] = (
                    f"{active} active campaign(s). {impr} impressions, "
                    f"£{spend} spend (7d). Meta Standard Access still pending "
                    f"for full API campaign creation."
                )
            break
    backlog["last_updated"] = datetime.now(timezone.utc).isoformat()
    TECH_BACKLOG_FILE.write_text(json.dumps(backlog, indent=2, ensure_ascii=False))


def run():
    env = _load_env()
    user_token = env.get("FB_USER_TOKEN", "")
    page_token = env.get("FB_PAGE_ACCESS_TOKEN", "")
    page_id = env.get("FB_PAGE_ID", "1039975692536580")
    ig_id = env.get("IG_USER_ID", "17841452712961347")
    ad_account = env.get("FB_AD_ACCOUNT_ID", "act_869755968629816")

    if not user_token or not page_token:
        print("  ⚠ FB_USER_TOKEN or FB_PAGE_ACCESS_TOKEN not set — skipping Meta sync")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"  📊 Fetching Meta metrics for {today}…")

    # Load existing
    social = _load_json(SOCIAL_METRICS_FILE, {"page": {}, "ig": {}, "posts": {}})
    strategy = _load_json(MARKETING_STRATEGY_FILE, {})

    # Page stats
    page_stats = fetch_page_stats(page_id, page_token)
    social.setdefault("page", {})[today] = page_stats
    print(f"  FB page followers: {page_stats['followers']}")

    # IG stats
    ig_stats = fetch_ig_stats(ig_id, page_token)
    social.setdefault("ig", {})[today] = ig_stats
    print(f"  IG followers: {ig_stats['followers_count']}")

    # Recent posts
    posts = fetch_recent_posts(page_id, page_token)
    social["posts"] = posts
    print(f"  FB posts fetched: {len(posts)}")

    # Keep last 30 days of page/ig snapshots
    for key in ("page", "ig"):
        days = sorted(social.get(key, {}).keys())
        if len(days) > 30:
            for old_day in days[:-30]:
                del social[key][old_day]

    social["fetched_at"] = datetime.now(timezone.utc).isoformat()
    SOCIAL_METRICS_FILE.write_text(json.dumps(social, indent=2))

    # Ad insights
    ad_data = fetch_ad_insights(ad_account, user_token)
    strategy["last_ad_metrics"] = ad_data
    # Update funnel impressions and clicks from ads
    funnel = strategy.setdefault("funnel", {
        "impressions": 0, "clicks": 0, "quiz_starts": 0, "diagnosed": 0, "paid": 0
    })
    funnel["impressions"] = ad_data.get("impressions", 0)
    funnel["clicks"] = ad_data.get("link_clicks", 0)
    strategy["funnel"] = funnel
    MARKETING_STRATEGY_FILE.write_text(json.dumps(strategy, indent=2))
    print(f"  Ad campaigns active: {ad_data.get('campaigns_active', 0)}, "
          f"impressions: {ad_data.get('impressions', 0)}, "
          f"spend: £{ad_data.get('spend', 0)}")

    # Update tech backlog
    update_tech_backlog(ad_data)
    print("  ✅ Meta metrics synced")


if __name__ == "__main__":
    run()
