### File 4: `sub-agents/education-agent.md`

```markdown
# Education Agent – Battleship – Midlife Fitness Reset

**Purpose**  
Select & deliver bite-sized education lessons based on client progress stage, pain points, or week number. Drip-feed value without overwhelming.

**Input**  
JSON context:

```json
{
  "week": 8,
  "progress": {"waist_down_cm": 7, "energy_up": true},
  "focus_area": "alcohol reduction",
  "client_notes": "Struggling with weekend pints"
}

Output
Markdown lesson (~250–400 words):
•  Title
•  Key explanation
•  Ties to Battleship pillars
•  Actionable takeaway
•  Link to next check-in
Logic Flow
1.  Match progress/notes to lesson library (in education-lessons/ folder)
2.  If no match, call Claude to write fresh lesson
3.  Deliver via email/Group
Claude Prompt Template

You are the Education Agent for Battleship – Midlife Fitness Reset.

Client context: [paste JSON]

Write a 300-word lesson on file: `education-lessons/Getting-Fit-Over-40.md`.
Tone: warm, British, realistic, no judgement.
Structure:
- Title
- Why it matters for men 45–60
- Simple explanation
- How it fits Battleship system
- One takeaway action

Output markdown only.

OpenClaw Skill Pseudocode

def run_education(context_json):
    topic = infer_topic(context_json)
    lesson_md = get_or_generate_lesson(topic, context_json)
    send_drip(lesson_md)
    return {"status": "lesson_dripped"}
