# README – Battleship – Midlife Fitness Reset Vault

**Last updated:** February 27, 2026  
**Owner:** William George Battleship Barratt  
**Purpose:** This Obsidian vault is the complete operating system, knowledge base, and agent blueprint for running **Battleship – Midlife Fitness Reset** — a simple, realistic online coaching programme for men 45–60 who’ve “failed before” at fitness, weight loss, or health resets.

**Core Brand Promise**  
“Simple system that works if you show up.”  
Reframe: “It failed before because the system didn’t fit your life or age — not because you’re weak.”  
Focus: belly fat, energy, confidence, blood markers, longevity.  
Alcohol stance: not mandatory quit, but dead calories & recovery killer — significant reduction usually required.

**Three Core Deliverables**  
1. Intake & Diagnosis → personalised “Why failed + what’s different” report  
2. 12-Week Battleship Plan → movement (Zone 2 steps), workouts, nutrition, mindset  
3. Ongoing Guidance & Tracking → weekly check-ins, adjustments, education drips

**Vault Structure & Key Files**

**Root Files**  
- [[00-Overview.md]] → High-level summary, brand, pillars, navigation hub  
- [[00-Agent-Launch-Command.md]] → Ignition prompt to start the persistent Battleship orchestrator agent  
- [[01-Niching-and-Goal-Setting.md]] → Target audience profile, messaging, business KPIs  
- [[02-Essential-Setup.md]] → Legal, payments, Stripe, insurance, tech stack checklist (UK-focused)  
- [[03-Creating-Your-Offer.md]] → Full programme structure, deliverables, agent responsibilities  
- [[04-Automated-Selling-System.md]] → Funnel flow, Meta Ads (FB primary), email sequences, automations  
- [[05-Getting-Clients.md]] → Acquisition channels: FB ads, organic Groups, X threads, outbound DMs  
- [[06-Scaling-and-Optimization.md]] → Phased roadmap: validation → automation → £10k+/mo leverage  
- [[07-Using-Claude-in-Your-Business.md]] → How to use Claude as co-founder/brain (context block in claude.md)  
- [[08-Resource-Gathering-with-AI-Agents.md]] → ClawPod agents for market research, competitor intel, pain-point scraping  
- [[09-Building-AI-Agent-Skills-with-OpenClaw.md]] → How to build modular OpenClaw skills for Battleship tasks  
- [[About-Will.md]] → Personal story – Will’s journey from fat & frail to fit at 47  
- [[alcohol-guidance.md]] → Realistic stance on drinking – dead calories, tracking, non-judgemental  
- [[client-progress-tracker-template.md]] → Weekly tracker template used by Check-in Agent (duplicate per client)


- `sub-agents/`  
  - [[intake-agent.md]]  
  - [[program-agent.md]]  
  - [[check-in-agent.md]] (uses progress tracker template)  
  - [[education-agent.md]]  
  - [[orchestrator.md]] (routes tasks to sub-agents)  

- `education-lessons/` 
  - [[01-Getting-Fit-Over-40.md]]
  - [[Insulin-fasting-visceral-fat.md]]
  - [[jamnadas-fasting-visceral-fat.md]]

**Other Folders**  
- `skills/` → OpenClaw skill blueprints & code  
- `agents/` → ClawPod agent plans  
- `scripts/` → Git-managed code  
- `clients/` → Per-client folders (duplicate progress tracker here)  
- `case-studies/` → Anonymised progress for marketing

- `skills/` 
  - [[battleship-intake.py]] - example code for intake of clients 
  Blueprints & code for OpenClaw skills (e.g. battleship-checkin.py)  

- `agents/`  
  ClawPod agent plans (market research, etc.)  

- `scripts/`  
  Git-managed Python/Node code  

- `clients/` (create per client)  
  Example: `clients/JD-53/`  
  - progress-tracker.md  
  - diagnosis.md  
  - 12-week-plan.md  

- `case-studies/`  
  Anonymised progress excerpts for marketing/testimonials (git-tracked)

**How the Agents Work Together**  
1. New lead → intake quiz → Intake Agent → diagnosis report + tags  
2. Enrolment → Program Agent → 12-week plan  
3. Weekly → Check-in Agent → updates progress tracker → coach message  
4. Milestones → Education Agent → drip lesson  
5. Orchestrator routes everything via OpenClaw daemon

**Launch Sequence**  
1. Fill [[claude.md]] with persistent context  
2. Paste [[00-Agent-Launch-Command]] into OpenClaw / Claude Projects / long-running chat  
3. Test with mock client: "Orchestrate intake for 53yo male, desk job, bad knee, wants belly fat gone"  
4. Watch chain: intake → plan → weekly check-in loop

**Quick Start Checklist**  
- [ ] Create claude.md & paste context block  
- [ ] Set up Stripe + Meta Ads Manager  
- [ ] Create FB Group "Battleship Crew"  
- [ ] Buy domain (battleshipreset.com / similar) & Carrd landing page  
- [ ] Install OpenClaw daemon & test one skill  
- [ ] Run first mock client through agents  
- [ ] Git init & push vault

**Vault is now complete**  
All files are self-contained, branded, and ready.  
Start small: manual Claude chats → add OpenClaw → scale with ads & agents.

Good luck, Battleship.  
You’ve got this. 🚢