# Learnings & Reflections – Battleship – Midlife Fitness Reset

*Updated daily. Minimum 3 insights/reflections per day. This file is the compounding brain of the business.*

---

## 2026-03-10 – Day 1

### Context load complete
- Vault is structurally solid. All strategy docs (offer, funnel, sub-agents, alcohol guidance, education lessons) are written and coherent.
- The personal story (About-Will.md) is genuinely compelling — the pool photo moment, the Apple Watch fitness age of 55, the on-off drinking cycle, the stubborn tech worker who tested everything on himself first. This is the core of the brand. Never lose it.
- OpenClaw dependency removed from strategy. Sub-agents will be rewritten as Claude-native prompts (paste-and-run in Cowork). This is actually better for Wil: no daemon, no security risk, no escalating costs — just structured prompts he can run in a session.

### Insight 1 – The brand story is the product differentiation
Most midlife fitness coaches sell "programmes." Will sells *understanding* — "it failed before because the system was wrong, not you." That reframe is rare and resonant for men who've tried and blamed themselves. Every piece of content, every intake question, every coach message should reinforce this. The system is the villain. Will (and the client) are the heroes.

### Insight 2 – Facebook is the right primary channel for this audience
Men 45–60 in the UK are on Facebook daily. Instagram skews younger. X (Twitter) works for threads and building authority but has a smaller pool of this demographic. Meta Ads lead forms are the fastest path to paid leads. The vault already knows this — execution needs to follow.

### Insight 3 – Zone 2 walking is the killer differentiator vs other coaches
Most coaches for this age group push HIIT, boot camps, and aggressive calorie deficits — all of which burn out men with desk jobs, bad knees, and full family lives. Battleship's Zone 2 walking + progressive strength approach is sustainable, evidence-backed, and genuinely different. This should be front-and-centre in all marketing.

### Insight 4 – The alcohol stance is gold
Non-judgmental, realistic, evidence-based ("dead calories + insulin spike + recovery hit"). Most coaches either ignore alcohol entirely or demand sobriety. Battleship acknowledges it, quantifies it, and gives the client agency. Men in this demographic will trust that honesty far more than a hard line.

### Insight 5 – Critical path to Week 4 client target
Week 4 is 31 March 2026. To have paying clients by then, the following must exist by end of Week 1:
- Intake quiz (Typeform or Google Forms) — lead capture
- Landing page live (Carrd) with intake quiz link
- Stripe products created (£199 one-time, £89/mo)
- FB Group created ("Battleship Crew")
- First 5 content pieces published (X + FB)
- Email welcome + diagnosis delivery sequence drafted

### Decisions made today
- Sub-agents will be rewritten as Claude-native (paste-and-run) — no OpenClaw
- Primary acquisition: Meta Ads (Facebook lead forms) + organic FB Group content
- Pricing confirmed: 12-week programme £199 (or 3×£75), ongoing £89/mo
- Tech stack simplified: Carrd → Typeform/Google Forms → Stripe → ConvertKit/Pulse → MyFitnessPal

---

## Weekly KPI Summary (update every Monday)

| Week | Clients Onboarded | Content Published | Revenue (£) | Leads Generated | Notes |
|------|------------------|-------------------|-------------|-----------------|-------|
| W1 (10 Mar) | 0 | 0 | £0 | 0 | Setup week |
| W2 | | | | | |
| W3 | | | | | |
| W4 | | | | | Target: first paying client |
| W5 | | | | | |
| W6 | | | | | |
| W7 | | | | | |
| W8 | | | | | |
| W9 | | | | | |
| W10 | | | | | |
| W11 | | | | | |
| W12 | | | | | Target: £3,000/mo |

---

*Add new daily entries above the weekly summary table.*

## 2026-03-26 – Day 17

- [2026-03-26] [ops] A missing `import sys` in `skills/marketing_bot.py` silently broke live posting for the entire day — 3 posts generated correctly but none reached Facebook. Silent warnings in pipeline output must be treated as P1 when they block the only revenue-generating action, even if they don't crash the process.
- [2026-03-26] [engineering] Python UnboundLocalError cascade: a variable assigned inside a try block is unbound if the block crashes before that assignment line. A later try block referencing it gets `cannot access local variable X where it is not associated with a value` — this is a symptom, not the root cause. Always trace to the first error in the chain.
- [2026-03-26] [strategy] With 5 days to the Week 4 client target and zero ad spend, the window is effectively closed unless a paid campaign goes live today. The bug fix unblocks content, but at 30 followers organic reach cannot close a week-4 paying-client target alone.

## 2026-03-25 – Day 16

- [2026-03-25] [distribution] At 30 FB followers, organic content is statistically inert — posting 5×/week into a 30-person audience generates near-zero impressions and zero leads. Paid traffic must run in parallel from day 1; organic compounds later once social proof and follower base exist.
- [2026-03-25] [funnel] The quiz-to-paid conversion rate (100% across all completions to date) confirms the offer and close mechanism are not the problem. The entire growth constraint is top-of-funnel volume. Solving for traffic is the only task that moves MRR.
- [2026-03-25] [ops] Meta app dev mode is a hard blocker on programmatic ad creation — 11 ideas queued with no path to launch until Standard Access is approved. Manual Ads Manager is the correct workaround and should not wait for the API fix. Parallel-track: submit Standard Access app review now so the unblock compounds later.
- [2026-03-25] [ads] The "Promoting Website" campaign logged a 10.2% CTR before expiring — roughly 10× the 0.9% Facebook industry average. This confirms the creative (battleshipreset.com) resonates with the audience. The next manual campaign should duplicate this creative exactly with the quiz URL swapped in as the destination.
- [2026-03-25] [strategy] Week 4 first-client deadline (31 Mar) is 6 days away with £0 ad spend and 0 leads. The only path to hitting it is a live paid campaign within the next 24 hours. If no campaign is live by EOD 25 Mar, the Week 4 target should be revised to Week 5 and the post-mortem should document the dev-mode blocker as the specific cause.
- [2026-03-25] [pipeline] Health check FAIL triggered by 6 API error lines — but inspection shows all 6 are low-severity Meta 400s (expired campaign IDs + IG scope mismatch). The health check threshold needs tuning: distinguish between blocking errors and noisy stale-API calls so genuine issues don't get buried in false positives.
