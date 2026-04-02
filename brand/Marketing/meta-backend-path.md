# Meta Backend Path

Verified on 2026-04-02 against the current codebase.

## What Is Backend-Only

- Organic Facebook image posting is backend-only via [`skills/facebook_bot.py`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_bot.py):[post_photo](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_bot.py#L512) and [`_post_live`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_bot.py#L239). It uses `FB_PAGE_ACCESS_TOKEN` + `FB_PAGE_ID`.
- Instagram image publishing is backend-only via [`_upload_photo_get_url`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_bot.py#L507) -> [`_ig_post_image`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_bot.py#L470). The image is first uploaded to the Facebook page CDN, then published through the IG Graph endpoints.
- Ad creation is backend-only via [`skills/facebook_ads_bot.py`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_ads_bot.py): [`create_campaign`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_ads_bot.py#L100), [`create_adset`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_ads_bot.py#L112), [`upload_image`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_ads_bot.py#L141), [`create_ad_creative`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_ads_bot.py#L159), and [`create_ad`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/skills/facebook_ads_bot.py#L185).
- The dashboard exposes the same ad path through [`scripts/app.py`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/scripts/app.py): [`/api/ads/campaigns`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/scripts/app.py#L5101) and [`/api/ads/boost-post`](/Users/will/.cline/worktrees/31fe4/BattleShip-Vault/scripts/app.py#L5169).

## Actual Runtime Gates

- Posting content is gated only by the presence of `FB_PAGE_ACCESS_TOKEN` and `FB_PAGE_ID`.
- Ad automation is gated only by:
  - `FB_AD_ACCOUNT_ID`
  - a token with ads permissions (`FB_SYSTEM_TOKEN` preferred, then `FB_USER_TOKEN`)
  - `FB_PAGE_ID` for creative creation
  - the `fb_ads_paused` bot-state switch for spend control
- Missing credentials should skip work safely. They should not be described as a Meta Standard Access blocker.

## Operational Rule

- Keep automation control separate from spend control.
- `fb_ads_paused=1` is the explicit spend kill-switch.
- Meta API review/dev-mode responses should be treated as a per-attempt API failure, not as a global pipeline blocker. Leave the idea queued and retry later.
