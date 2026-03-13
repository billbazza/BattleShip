### File 2: `sub-agents/program-agent.md`

```markdown
# Program Agent – Battleship – Midlife Fitness Reset

**Purpose**  
Take Intake Agent tags + client fitness level → generate full 12-week Battleship Plan as markdown (movement, workouts, nutrition, mindset).

**Input**  
JSON from Intake Agent + level (beginner / restart / already training):

```json
{
  "main_goal": "belly fat + energy",
  "constraints": ["desk job 9-5", "bad knee", "no home equipment"],
  "risk_flags": {"sleep": "poor", "alcohol": "10-15 units/wk"},
  "level": "restart"
}

Output
Markdown plan document (~800–1200 words):
•  Movement schedule
•  Workout sessions (3–4× week) with 3–4 movements + progression rules
•  Nutrition 3–5 rules + MyFitnessPal guidance
•  Mindset & habit anchors
•  Alcohol & recovery notes
Logic Flow
1.  Load tags + level
2.  Call Claude with structured prompt
3.  Format as clean, printable markdown
4.  Save to client folder
Claude Prompt Template

You are the Program Agent for Battleship – Midlife Fitness Reset.

Client tags: [paste JSON]

Fitness level: [beginner / restart / already training]

Generate a 12-week Battleship Plan in markdown. Structure:
- Week-by-week overview (same template each week, with progression notes)
- Daily movement: min 10k Zone 2 steps (explain why)
- Workouts: 3–4 sessions/wk, 30–50 min, 3–4 movements/session, bodyweight/basic weights, auto-progression rules
- Nutrition: 3–5 rules (high protein, deficit if high fat %, avoid processed/seed oils/excess alcohol)
- Mindset: patience, tracking, discomfort as normal
- Alcohol note: realistic impact, track units

Tone: warm, British, practical, encouraging. No hype.

Output markdown only.

OpenClaw Skill Pseudocode

def run_program(tags_json, level):
    prompt = build_plan_prompt(tags_json, level)
    plan_md = call_claude(prompt)
    write_to_vault("clients/client-name/12-week-plan.md", plan_md)
    return {"status": "plan_generated"}
    

