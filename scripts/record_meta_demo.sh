#!/usr/bin/env bash
# record_meta_demo.sh
# Screen recording helper for Meta App Review API demonstrations.
# Run this script in Terminal while QuickTime Player is recording.
# It shows live API calls to Meta Graph API on behalf of Battleship Reset.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=================================================="
echo "  Battleship Reset — Meta API Demo"
echo "  App: Battleship-Reset  |  Account: act_869755968629816"
echo "=================================================="
echo ""

# Load secrets from ~/.battleship.env
if [[ ! -f "$HOME/.battleship.env" ]]; then
  echo "ERROR: ~/.battleship.env not found" && exit 1
fi
# shellcheck disable=SC1090
set -a; source "$HOME/.battleship.env"; set +a

sleep 2

echo "▶ Step 1: Fetching Facebook Page stats"
echo "  Endpoint: GET /v19.0/${FB_PAGE_ID}?fields=fan_count,followers_count,name"
sleep 1
python3 - <<'PYEOF'
import os, json, urllib.request as r
token = os.environ.get("FB_PAGE_ACCESS_TOKEN","")
page_id = os.environ.get("FB_PAGE_ID","1039975692536580")
url = f"https://graph.facebook.com/v19.0/{page_id}?fields=fan_count,followers_count,name&access_token={token}"
with r.urlopen(url, timeout=10) as resp:
    d = json.loads(resp.read())
print(f"  Page name    : {d.get('name')}")
print(f"  Fans         : {d.get('fan_count')}")
print(f"  Followers    : {d.get('followers_count')}")
PYEOF
sleep 3

echo ""
echo "▶ Step 2: Fetching Instagram account stats"
echo "  Endpoint: GET /v19.0/${IG_USER_ID}?fields=followers_count,media_count,username"
sleep 1
python3 - <<'PYEOF'
import os, json, urllib.request as r
token = os.environ.get("FB_PAGE_ACCESS_TOKEN","")
ig_id = os.environ.get("IG_USER_ID","17841452712961347")
url = f"https://graph.facebook.com/v19.0/{ig_id}?fields=followers_count,follows_count,media_count,username&access_token={token}"
with r.urlopen(url, timeout=10) as resp:
    d = json.loads(resp.read())
print(f"  IG username  : @{d.get('username')}")
print(f"  Followers    : {d.get('followers_count')}")
print(f"  Media count  : {d.get('media_count')}")
PYEOF
sleep 3

echo ""
echo "▶ Step 3: Fetching Ad Campaign list"
echo "  Endpoint: GET /v19.0/${FB_AD_ACCOUNT_ID}/campaigns"
sleep 1
python3 - <<'PYEOF'
import os, json, urllib.request as r
token = os.environ.get("FB_USER_TOKEN","")
account = os.environ.get("FB_AD_ACCOUNT_ID","act_869755968629816")
url = (f"https://graph.facebook.com/v19.0/{account}/campaigns"
       f"?fields=id,name,status,objective,budget_remaining"
       f"&access_token={token}")
with r.urlopen(url, timeout=10) as resp:
    d = json.loads(resp.read())
for c in d.get("data", []):
    status = c.get("status","")
    marker = "✅ ACTIVE" if status == "ACTIVE" else "⏸  PAUSED"
    print(f"  {marker}  {c.get('name','')[:55]}")
    print(f"           objective={c.get('objective')}, budget_remaining={c.get('budget_remaining','n/a')}p")
PYEOF
sleep 3

echo ""
echo "▶ Step 4: Fetching 7-day Ad Insights (ads_read)"
echo "  Endpoint: GET /v19.0/${FB_AD_ACCOUNT_ID}/insights?date_preset=last_7d"
sleep 1
python3 - <<'PYEOF'
import os, json, urllib.request as r
token = os.environ.get("FB_USER_TOKEN","")
account = os.environ.get("FB_AD_ACCOUNT_ID","act_869755968629816")
url = (f"https://graph.facebook.com/v19.0/{account}/insights"
       f"?fields=impressions,reach,clicks,spend,ctr,cpm,cpc"
       f"&date_preset=last_7d&access_token={token}")
with r.urlopen(url, timeout=10) as resp:
    d = json.loads(resp.read())
rows = d.get("data", [])
if rows:
    row = rows[0]
    print(f"  Impressions  : {row.get('impressions')}")
    print(f"  Reach        : {row.get('reach')}")
    print(f"  Clicks       : {row.get('clicks')}")
    print(f"  Spend        : £{row.get('spend')}")
    print(f"  CTR          : {row.get('ctr')}%")
    print(f"  CPC          : £{row.get('cpc')}")
else:
    print("  (no rows returned for date range)")
PYEOF
sleep 3

echo ""
echo "▶ Step 5: Fetching recent Facebook Page posts (pages_read_engagement)"
echo "  Endpoint: GET /v19.0/${FB_PAGE_ID}/posts"
sleep 1
python3 - <<'PYEOF'
import os, json, urllib.request as r
token = os.environ.get("FB_PAGE_ACCESS_TOKEN","")
page_id = os.environ.get("FB_PAGE_ID","1039975692536580")
url = (f"https://graph.facebook.com/v19.0/{page_id}/posts"
       f"?fields=message,created_time&limit=3&access_token={token}")
with r.urlopen(url, timeout=10) as resp:
    d = json.loads(resp.read())
posts = d.get("data", [])
print(f"  Posts returned: {len(posts)}")
for p in posts:
    msg = (p.get("message") or "")[:60]
    print(f"  [{p.get('created_time','')[:10]}] {msg}…")
PYEOF
sleep 3

echo ""
echo "▶ Step 6: Running full daily sync (writes to clients/)"
echo "  python3 scripts/fetch_meta_metrics.py"
sleep 1
cd "$VAULT_ROOT"
python3 scripts/fetch_meta_metrics.py
sleep 3

echo ""
echo "=================================================="
echo "  ✅ Demo complete. All API calls succeeded."
echo "  Data written to clients/social_metrics.json"
echo "  and clients/marketing_strategy.json"
echo "=================================================="
sleep 2
