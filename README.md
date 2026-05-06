# Battleship Reset Agentic Business Research Project

**Status:** Closed / archived  
**Project period:** March 2026 to May 2026  
**Owner:** Will Barratt  
**Repository:** BattleShip-Vault  
**Primary domain:** `battleshipreset.com`  
**Shutdown date:** 2026-05-06

Battleship Reset was a practical research project into whether a small online coaching business could be operated through an agentic, automation-heavy system rather than through conventional SaaS tools, manual operations, or a traditional agency stack.

The business concept was an online fitness reset for men in midlife. The technical concept was broader: build a local-first autonomous business operating system that could capture leads, process intake data, generate personalised coaching material, send emails, monitor payments, run check-ins, produce social content, track metrics, and coordinate growth workflows through a set of Python agents and scheduled automations.

The project should be read as an applied experiment in agentic workflows, content operations, API orchestration, and local automation. It was not closed because the system could not be built. The system was built to a meaningful degree. It was closed because the operating cost, external-service complexity, manual account dependencies, and commercial traction did not justify keeping the infrastructure live.

## Research Goals

The project explored five main questions.

1. Could a solo operator build a working online coaching operation using local Python, AI APIs, and lightweight third-party services?

2. Could agentic workflows replace or reduce the need for a CRM, email automation platform, social media scheduler, Zapier-style glue layer, and manual business dashboard?

3. Could social media content generation, approval, posting, and performance tracking be run as a semi-autonomous feedback loop?

4. Could Cloudflare Tunnel make a home/local Mac-based service practical enough to receive public webhooks from services like Tally and Stripe?

5. Could the same architecture later become a reusable "sovereign" business operating system for other products, niches, or verticals?

## Product Concept

The commercial product was **Battleship Reset**, a 12-week online coaching programme for men aged roughly 40 to 60 who wanted a realistic midlife fitness reset.

The offer was positioned around:

- Simple walking and strength progression.
- A non-extreme approach to fat loss.
- Personalised diagnosis after an intake form.
- Weekly check-ins and course correction.
- Education drips across the 12-week journey.
- A later Phase 2 monthly coaching offer built around a personal challenge goal.

The intended customer journey was:

```text
battleshipreset.com
  -> Tally intake form
  -> webhook.battleshipreset.com/tally-webhook
  -> local Flask app via Cloudflare Tunnel
  -> queued intake JSON
  -> Python pipeline
  -> AI-generated diagnosis email
  -> Stripe payment link
  -> payment detection
  -> personalised onboarding and 12-week plan
  -> weekly Google Form check-ins
  -> AI-generated coach replies
  -> education emails
  -> Week 8 challenge prompt
  -> Week 12 close and Phase 2 pitch
```

## High-Level Architecture

The system was intentionally local-first. The main runtime lived on a Mac and exposed selected endpoints to the public internet through Cloudflare Tunnel.

```text
External services
  Carrd website
  Tally intake form
  Stripe payments
  Google Forms / Sheets
  Meta Graph API
  Beehiiv
  SMTP / IMAP email
  Telegram
  Cloudflare DNS / Tunnel

Local machine
  Flask dashboard and webhook receiver
  Python pipeline
  SQLite database
  JSON state files
  Markdown vault
  LaunchAgent automations
  Agent scripts in skills/

AI layer
  Claude originally
  Later OpenAI / xAI-compatible wrapper
  Prompt-driven generation for diagnosis, coaching, content, reports, and replies
```

The system used plain files, SQLite, and Markdown as much as possible. This made development fast and inspectable, but created consistency challenges once multiple bots wrote to the same data surfaces.

## Repository Structure

Important folders and files:

| Path | Role |
| --- | --- |
| `scripts/battleship_pipeline.py` | Main operational pipeline for intake, payment polling, onboarding, check-ins, drips, inbound email, and orchestrator calls. |
| `scripts/app.py` | Flask dashboard, webhook receiver, business manager, action endpoints, and public legal pages. |
| `scripts/db.py` | SQLite persistence helpers used by dashboard and bots. |
| `runtime_config.py` | Runtime config loader with environment and macOS Keychain support. |
| `llm_client.py` | Shared LLM provider wrapper added to make provider changes less invasive. |
| `skills/` | Agent and bot scripts for growth, marketing, social, SEO, accounts, newsletters, tech backlog, graphics, and trackers. |
| `clients/` | Client state, database, generated client folders, review queues, and metrics state. |
| `brand/Marketing/` | Marketing strategy, idea banks, SEO outputs, reminders, tech backlog, and review state. |
| `education-lessons/` | Static educational lesson library used by drip sequences. |
| `11-week-programs/` | Training programme templates selected based on client equipment and status. |
| `scripts/launchagents/` | macOS LaunchAgent definitions for dashboard, pipeline, tunnel, and daily Claude agent. |
| `logs/` | Pipeline logs, daily logs, and operational notes. |
| `spec.md` | Original technical specification from the live phase. |
| `scripts/COMMANDS.md` | Operational command reference from the live phase. |

## Core Runtime Components

### 1. Flask Dashboard and Webhook Receiver

`scripts/app.py` served several roles:

- Local dashboard at `http://localhost:5100`.
- Business manager view at `/business`.
- System status panel.
- Tally webhook receiver at `/tally-webhook`.
- Stripe guide webhook endpoint.
- Client detail pages.
- Manual action endpoints for enrolment, notes, archive, refund, status changes, and week advancement.
- Public legal/privacy pages.
- Read-only signed snapshot endpoint.
- Brand asset serving for generated pages and emails.

This made Flask both the operational UI and the public webhook ingress. That reduced moving parts, but it also meant the dashboard process became critical infrastructure.

### 2. Main Pipeline

`scripts/battleship_pipeline.py` was the core automation loop. It ran on a schedule and could also be invoked manually.

The intended execution order was:

1. Process queued Tally intake submissions.
2. Generate diagnosis material.
3. Send diagnosis email with payment link.
4. Poll Stripe charges and enrol paid clients.
5. Generate 12-week plans.
6. Send onboarding emails.
7. Send weekly check-in requests.
8. Read Google Sheets check-in responses.
9. Generate personalised coach replies.
10. Process inbound IMAP email.
11. Send education drips.
12. Generate Week 8 challenge prompts.
13. Generate Week 12 close and Phase 2 pitch.
14. Run the growth orchestrator.

The pipeline was deliberately written as a single, inspectable Python entrypoint. That helped debugging early on, but the file grew into a large mixed-responsibility script.

### 3. LaunchAgent Automations

macOS LaunchAgents were used instead of a server process manager.

Installed agents included:

| LaunchAgent | Purpose |
| --- | --- |
| `com.battleship.dashboard` | Kept the Flask dashboard running. |
| `com.battleship.tunnel` | Kept `cloudflared tunnel run battleship` running. |
| `com.battleship.pipeline` | Ran the main pipeline every two hours. |
| `com.battleship.claude-agent` | Ran a daily Claude-based business agent prompt. |
| `com.battleship.morning` | Morning briefing automation. |
| `com.battleship.evening` | Evening check-in automation. |
| `com.battleship.marketing` | Marketing review or content automation. |

This worked well for local persistence and automatic restart. The downside was that shutdown required disabling both running processes and their installed `KeepAlive` plists. If a plist remained in `~/Library/LaunchAgents`, launchd could restart a supposedly stopped service.

### 4. Cloudflare Tunnel

Cloudflare Tunnel was used to expose a local Mac service to public webhooks without opening router ports.

The historical tunnel config was:

```yaml
tunnel: 2f741e0f-2df9-4673-847d-26785964c43c
ingress:
  - hostname: webhook.battleshipreset.com
    service: http://localhost:5100
  - service: http_status:404
```

The tunnel enabled:

- Tally webhook delivery.
- External dashboard/business URL.
- Signed snapshots.
- Public tracker URLs.
- Brand asset serving from local files.

This was one of the most successful infrastructure choices. It made a local-first architecture viable for experimentation. The tradeoff was operational fragility: if the Mac, Flask process, tunnel, or LaunchAgent failed, webhook delivery failed.

### 5. Data Layer

The project used a hybrid data model:

- Markdown files for durable business memory and content.
- JSON files for bot state, queues, and early application state.
- SQLite for dashboard-readable state and more structured data.
- Per-client folders for generated diagnosis, plans, logs, and trackers.

Important data surfaces included:

| Surface | Purpose |
| --- | --- |
| `clients/state.json` | Original client state source. |
| `clients/battleship.db` | SQLite database used increasingly by dashboard and bots. |
| `clients/business_metrics_history.json` | Historical KPI snapshots. |
| `brand/Marketing/ideas-bank.json` | Marketing ideas and content queue. |
| `brand/Marketing/orchestrator_state.json` | Daily growth orchestrator state. |
| `brand/Marketing/tech_backlog.json` | Automation and tooling backlog. |
| `brand/Marketing/SEO/seo_state.json` | Google Business Profile task progression. |
| `clients/content_review.json` | Content approval/review queue. |
| `clients/newsletter_state.json` | Newsletter state and Beehiiv references. |

The hybrid approach made iteration fast. It also produced drift risk. A key later convention was added: any bot writing JSON also had to write to SQLite via `db.py`, because the dashboard read SQLite only.

## Agent and Bot Architecture

Agents lived mostly under `skills/`. They were not autonomous LLM agents in the fully open-ended sense. They were bounded Python workflows using state files, APIs, prompts, and deterministic control logic.

### Orchestrator Agent

File: `skills/orchestrator.py`

Role:

- Coordinate growth bots.
- Run daily once through a gate.
- Generate a brand/project-manager style brief.
- Summarise MRR, gap to target, and weekly priorities.
- Send a `[COMMAND]` email report.

What worked:

- The orchestrator gave the system a daily operating rhythm.
- It made the growth system feel coherent rather than like isolated scripts.

What did not work:

- It still depended on external traction and manual service setup.
- It could prioritise work, but it could not remove blockers like Meta account permissions or insufficient ad budget.

### Marketing Bot

File: `skills/marketing_bot.py`

Role:

- Generate social content ideas.
- Maintain marketing arcs.
- Produce copy for Facebook/Instagram-style posts.
- Feed content review queues.
- Support the wider content engine.

What worked:

- It generated a high volume of usable content.
- It encoded brand tone and repeated campaign angles.

What did not work:

- Content generation without sufficient distribution did not move business metrics.
- The system could create posts faster than the audience could absorb them.

### Facebook Bot

File: `skills/facebook_bot.py`

Role:

- Post or schedule Facebook Page content.
- Track organic post performance through Meta Graph API.
- Cross-post images to Instagram when possible.
- Generate comments or engagement actions.
- Feed social metrics back into reports.

What worked:

- The Graph API integration could post, inspect metrics, and support feedback loops.
- The bot helped prove that social publishing can be folded into a local automation stack.

What did not work:

- Meta permissions, page tokens, dev-mode limitations, and app review requirements created substantial friction.
- Instagram automation was constrained by platform limitations.
- Token expiry and scope mismatch produced noisy health check failures.

### Facebook Ads Bot

File: `skills/facebook_ads_bot.py`

Role:

- Draft ad campaigns.
- Attempt campaign/adset/ad/creative creation through Meta Marketing API.
- Track campaign performance through ad account metrics.

What worked:

- The repo captured a clear path toward programmatic ad operations.
- Campaign metrics could be pulled when tokens/scopes were valid.

What did not work:

- Meta app dev mode and `ads_management` access blocked full automation.
- Manual Ads Manager remained the practical workaround.
- Without sustained paid traffic, the funnel could not be properly tested.

### Brand Manager

File: `skills/brand_manager.py`

Role:

- Generate before/after composites.
- Create hook variants.
- Produce image assets for social posts and brand experiments.

What worked:

- Hooked visual variants were useful for rapid creative testing.
- It showed how lightweight image generation/editing workflows could support content operations.

What did not work:

- Asset generation alone did not solve distribution.
- Visual workflows still needed human judgement for brand quality.

### SEO Bot

File: `skills/seo_bot.py`

Role:

- Progress Google Business Profile setup tasks.
- Generate weekly Google Business Profile post copy.
- Create category audits, Q&A ideas, review prompts, services copy, and photo plans.

What worked:

- The bot generated practical local SEO tasks and copy.
- It turned a vague SEO backlog into a staged workflow.

What did not work:

- Google Business Profile actions still required manual account access and confirmation.
- API access for GBP posting was not available for this use case at the free/early stage.

### Tech Bot

File: `skills/tech_bot.py`

Role:

- Track operational gaps.
- Separate free workarounds from paid upgrades.
- Tie tool purchases to revenue thresholds.

What worked:

- This was a useful governance mechanism.
- It helped avoid buying SaaS before revenue justified it.

What did not work:

- It could identify friction but not eliminate account-level blockers.

### Newsletter Bot

File: `skills/newsletter_bot.py`

Role:

- Generate newsletter content.
- Push posts to Beehiiv through API calls.
- Track newsletter state.

What worked:

- Beehiiv API posting could be integrated.
- Newsletter content could be generated and queued from the same agentic stack.

What did not work:

- Newsletter work was premature without a meaningful email list.
- Placeholder drafts exposed the need for validation at the database/write layer.

### Accounts Bot

File: `skills/accounts_bot.py`

Role:

- Track vendor costs and account-related observations.
- Produce finance/admin reports.

What worked:

- It created a path toward lightweight business accounting.

What did not work:

- It remained a workaround for proper accounting software.
- Some financial records still required manual confirmation.

### PDF Guide Bot

File: `skills/pdf_guide_bot.py`

Role:

- Generate digital product guide content.
- Render PDF-style outputs.
- Support low-ticket product experiments.

What worked:

- It demonstrated that product creation could be partially automated from prompts and templates.

What did not work:

- Product creation outpaced validation and distribution.

### Tracker Generator

File: `skills/tracker_generator.py`

Role:

- Generate client workout/progress tracker pages.
- Provide PWA-like local/web tracker experiences.

What worked:

- The generated tracker concept was strong for coaching delivery.
- It gave clients a simple, personalised artefact.

What did not work:

- Public hosting through the local tunnel made the tracker dependent on the Mac and tunnel uptime.

## API and Service Integrations

### Tally

Purpose:

- Intake form capture.
- Webhook POST to `/tally-webhook`.

What worked:

- Tally was lightweight and cheap.
- Webhook flow into Flask was straightforward.

What did not work:

- The intake form became too long and likely created conversion friction.
- Tally could collect leads, but the downstream offer still needed traffic.

### Stripe

Purpose:

- Payment links.
- Payment polling.
- Stripe guide webhook endpoint.
- Phase 2 payment link concept.

What worked:

- Payment links were simple and low overhead.
- Polling charges avoided full webhook complexity for early testing.

What did not work:

- Polling is less robust than a complete webhook/payment intent model.
- Live payment links remained external surfaces that needed manual shutdown.

### Google Forms and Google Sheets

Purpose:

- Weekly check-ins.
- Structured response storage.
- Pipeline readback through service-account credentials.

What worked:

- Google Forms/Sheets provided a free, familiar check-in backend.
- The pipeline could normalise rows into coach-reply prompts.

What did not work:

- Sheets row handling required careful stable IDs.
- Service-account credentials introduced another sensitive local secret.

### Meta / Facebook / Instagram

Purpose:

- Organic posting.
- Page insights.
- Instagram cross-post attempts.
- Ads metrics.
- Campaign creation experiments.

What worked:

- Organic page posting and insights were feasible.
- Performance metrics could feed the dashboard and strategy files.

What did not work:

- API permissions were the largest integration drag.
- App review, token scopes, token expiry, and dev-mode limits blocked full ads automation.
- Meta errors created false-positive health issues until severity handling was improved.

### Beehiiv

Purpose:

- Newsletter post creation.
- Email list/newsletter experiments.

What worked:

- API calls could create posts.
- It fit the content repurposing model.

What did not work:

- It was not a priority before traffic and lead volume existed.

### SMTP and IMAP

Purpose:

- Send diagnosis, onboarding, education, check-in, internal, and command emails.
- Read inbound replies.
- Route support/coach messages.

What worked:

- iCloud SMTP/IMAP made email automation possible without a dedicated email SaaS.
- Subject-tagged replies allowed simple command workflows.

What did not work:

- Email account automation is fragile and security-sensitive.
- App-specific passwords and mailbox routing must be managed carefully.

### Telegram

Purpose:

- Operator notifications.
- Approval/action alerts.

What worked:

- Simple notification channel.

What did not work:

- Notifications became noisy.
- Later kill-switch flags were needed to mute internal Telegram and email alerts without blocking client-facing emails.

### Cloudflare

Purpose:

- DNS for `battleshipreset.com`.
- Tunnel for `webhook.battleshipreset.com`.
- Public ingress to local Flask.

What worked:

- Cloudflare Tunnel was the key enabler for local-first public webhooks.
- It avoided server hosting costs and router configuration.

What did not work:

- Public availability depended on the local machine.
- Cloudflare config and cert files became additional shutdown/security surfaces.

### AI Providers

Purpose:

- Generate diagnosis reports.
- Generate 12-week plans.
- Generate check-in replies.
- Generate challenge and close emails.
- Generate social content, SEO copy, product drafts, and reports.

Original direction:

- Claude was the initial reasoning/generation provider.

Later direction:

- A provider wrapper was introduced to support OpenAI/xAI-style fallback and reduce repo-wide provider coupling.

What worked:

- AI generation was effective for structured, constrained outputs.
- The coaching tone could be encoded well through prompt files and examples.

What did not work:

- Provider-specific SDK calls scattered across bots made cutover painful until centralised.
- AI generation could produce work faster than validation, traffic, and sales could justify.

## Dashboard and Business Manager

The dashboard was one of the most complete pieces of the project.

It included:

- Client list.
- Client detail views.
- Status controls.
- Manual enrolment.
- Archive/refund/silent controls.
- Coach notes.
- Pipeline run button.
- System health checks.
- Business KPI cards.
- Revenue/spend charts.
- Funnel metrics.
- Marketing arc timeline.
- SEO progress.
- Tech backlog.
- Social metrics.
- Approval queues.

What worked:

- The dashboard made a complex automation stack operable.
- It exposed missing data and broken flows quickly.
- It turned a folder of scripts into something closer to an internal operating system.

What did not work:

- Some UI cards initially displayed actions that were not fully wired.
- Health checks were too noisy until severity was separated into critical/warn/info.
- The dashboard depended on local Flask uptime and Cloudflare for external access.

## Security Model

The project used several secret/config storage mechanisms over time:

- `~/.battleship.env`
- `~/.battleship-gsheets.json`
- macOS Keychain
- Cloudflare credentials under `~/.cloudflared/`
- Environment variables for tests and one-off runs

Important security lessons:

- Secrets should not be committed.
- Runtime config should be centralised.
- Home-directory secrets matter as much as repo secrets.
- Any shutdown needs to include API key revocation, service-account deletion, and app-password revocation.
- A local tunnel makes local services public, so every exposed route needs deliberate authentication.

## What Was Achieved

The project achieved a substantial working prototype of an agentic local-first business system.

Completed or partially completed:

- Public website content and domain configuration.
- Tally intake form and webhook architecture.
- Flask webhook receiver.
- Local dashboard.
- Business manager dashboard.
- Cloudflare Tunnel public ingress.
- macOS LaunchAgent scheduling.
- AI diagnosis generation.
- AI plan generation.
- Email templates.
- SMTP sending.
- IMAP inbound processing.
- Stripe payment link integration.
- Stripe polling.
- Google Sheets check-in processing.
- Education drip library.
- Week 8 challenge concept.
- Week 12 close / Phase 2 concept.
- Social content generation.
- Facebook posting and metrics experiments.
- Meta Ads API experiments.
- SEO workflow bot.
- Tech backlog bot.
- Newsletter/Beehiiv experiments.
- PDF guide/product experiments.
- SQLite migration path.
- Runtime config and LLM provider wrapper.
- Shutdown procedure and service audit.

The most important proof was that a single local machine, Python, Cloudflare Tunnel, and AI APIs can coordinate a surprisingly complete business workflow.

## What Worked Well

### Local-first automation was viable

Running the dashboard, webhook receiver, and pipeline locally worked. Cloudflare Tunnel made it possible for external services to reach the local machine.

### Python scripts were enough

The system did not need a large framework. Python scripts, Flask, SQLite, Markdown, JSON, and LaunchAgents were sufficient to build a credible operating prototype.

### AI was strong for constrained generation

Diagnosis reports, coaching emails, education copy, SEO tasks, and content drafts were all good fits for LLM generation when prompts were specific and context was controlled.

### The dashboard mattered

Without the dashboard, the system would have been hard to trust. The UI made pipeline state, metrics, queues, and client records visible.

### Agentic workflows created leverage

The agents were useful when they had bounded jobs:

- Generate content.
- Summarise metrics.
- Draft reports.
- Create SEO tasks.
- Flag tech gaps.
- Send internal command reports.

The best agentic workflows were not open-ended. They were constrained, stateful, and inspectable.

### The project produced reusable patterns

Reusable patterns included:

- Local Flask plus Cloudflare Tunnel for webhooks.
- LaunchAgents for local scheduled automation.
- Markdown plus SQLite as a lightweight business memory stack.
- Human-readable daily logs and learnings.
- Revenue-gated tech backlog.
- Approval queues for generated content.
- Central runtime config and provider abstraction.

## What Did Not Work

### Distribution was the bottleneck

The system could produce content and business assets, but it could not create an audience by itself. Organic reach was too small, and paid traffic was not sustained enough to validate the funnel.

### Meta automation was high-friction

Meta Graph and Marketing APIs introduced significant friction:

- Token scopes.
- App review.
- Development mode.
- Expired campaigns.
- Permissions mismatch.
- Instagram limitations.
- Noisy API errors.

This made full ad automation impractical at the early stage.

### Too much was automated before the funnel was validated

The system automated intake, coaching, check-ins, content, SEO, newsletters, dashboards, and products before there was enough proven demand.

The lesson: automate the narrowest revenue path first. Build the wider operating system after traffic and conversion are proven.

### Hybrid state created drift

JSON, Markdown, and SQLite all had valid uses, but multiple write paths created silent drift. The dashboard reading SQLite while bots wrote JSON was a specific failure mode.

The later rule became: if a bot writes JSON for operational state, it must also sync to SQLite.

### Health checks needed severity

Early health checks treated noisy stale API calls similarly to blocking failures. That trained the operator to ignore warnings.

The fix was to distinguish:

- `CRITICAL`: pipeline cannot operate.
- `WARN`: stale API/noisy integration issue.
- `INFO`: expected condition or diagnostic note.

### Local public infrastructure had uptime limits

Cloudflare Tunnel was effective, but the architecture still depended on:

- Mac uptime.
- Flask process health.
- LaunchAgent state.
- Local network availability.
- Cloudflare tunnel credentials.

This was acceptable for research. It would need hardening for production.

### Notification volume became noise

Telegram and internal emails were useful at first. As bots multiplied, notifications became operational noise. Kill-switch flags were added so internal notifications could be muted without disabling client-facing flows.

## Shutdown Summary

The project was shut down on 2026-05-06.

Shutdown actions completed locally:

- Disabled installed `com.battleship.*` LaunchAgents.
- Moved installed plists to `/Users/will/Library/LaunchAgents.disabled-battleship-2026-05-06/`.
- Stopped the Flask dashboard.
- Stopped the local pipeline automations.
- Stopped the Cloudflare tunnel process.
- Deleted the remote Cloudflare named tunnel `battleship`.
- Verified no Battleship LaunchAgents remained loaded.
- Verified no repo-tied processes remained running.
- Verified no listener remained on port `5100`.
- Verified Cloudflare tunnel list returned no tunnels.

Remaining manual shutdown surfaces identified:

- Carrd public site and plan.
- Cloudflare DNS records.
- Tally form and webhook.
- Stripe payment links, API keys, and webhooks.
- Google Form, Sheet, service account, and credentials.
- Meta/Facebook/Instagram tokens, ads, app permissions, and billing.
- Beehiiv publication/API access.
- iCloud app-specific SMTP/IMAP password.
- Telegram bot token.
- AI provider API keys.
- GitHub repositories if archival/deletion is desired.

Sensitive local files identified for deletion or rotation:

- `~/.battleship.env`
- `~/.battleship-gsheets.json`
- `~/.cloudflared/config.yml`
- `~/.cloudflared/cert.pem`
- Relevant macOS Keychain entries used by the runtime.

## Why The Project Was Closed

Battleship Reset was closed because the research value had been achieved, while the live operating burden no longer made sense.

The project proved that:

- A local-first agentic business stack can be built.
- AI can generate useful coaching, content, and operational outputs.
- Cloudflare Tunnel can support public webhooks into a local automation system.
- Social/content workflows can be semi-automated.
- A dashboard can coordinate a complex solo-operator business system.

The project also proved the limits:

- Automation does not replace distribution.
- Social content generation does not guarantee reach.
- Meta API automation is too high-friction for an early small business without stable app review and token management.
- Local infrastructure can be powerful but carries hidden operational risk.
- Broad automation before funnel validation creates complexity faster than revenue.

The closing conclusion is that the architecture was valuable as a research prototype, but the commercial system should not remain live without a narrower validated acquisition channel, fewer external integrations, stronger auth, cleaner state ownership, and a simpler production deployment model.

The strongest future version would start smaller:

1. One offer.
2. One landing page.
3. One intake path.
4. One payment path.
5. One traffic channel.
6. One dashboard.
7. Only then add agents around proven bottlenecks.

## Final Assessment

Battleship Reset was a successful technical exploration and an incomplete commercial experiment.

It produced a working local agentic operating system for a coaching business, but it did not justify staying live as an ongoing service. The most reusable output is not the fitness business itself. It is the set of patterns, lessons, and architectural constraints discovered while building it.

Those lessons are now preserved in this repository for future agentic business, content workflow, and local automation projects.
