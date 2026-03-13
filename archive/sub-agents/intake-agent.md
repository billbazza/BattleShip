# Intake Agent – Battleship – Midlife Fitness Reset

**Purpose**  
Process new client long-form intake form → tag key data → generate personalised 1-page "Battleship Diagnosis Report" (Why it failed so far + what will be different this time).  
Non-shaming, system-focused, realistic British tone.

**Input**  
Markdown or JSON from form responses, e.g.:

Name: John Age: 53 Main goal: lose belly fat, more energy Past attempts: tried keto twice, gym for 2 months, failed both Schedule: desk job, 9-5, kids at home Injuries: bad right knee from old football Alcohol: 10–15 units/week (mostly weekends) Sleep: 5–6 hours, wakes tired Stress: high (work + family) Equipment: none at home, can use gym lunchtime

**Output**  
Markdown report (~300–500 words):

- Why past attempts failed (system mismatch, not personal weakness)  
- What will be different with Battleship (simple, fits life, measurable)  
- Tagged summary for next agent (Program Agent)

**Logic Flow**  
1. Parse input → extract & tag: goal, constraints (time/injury/kit), risk flags (sleep/alcohol/stress)  
2. Call Claude with structured prompt  
3. Format output as clean markdown report  
4. Save tags as JSON for orchestrator

**Claude Prompt Template**  

You are the Intake Agent for Battleship – Midlife Fitness Reset.
Read this client’s intake form:
[paste full form here]
Tag the following:
•  main_goal: primary outcome (e.g. belly fat, energy)
•  constraints: time, injuries, equipment, schedule
•  risk_flags: sleep quality, alcohol units/pattern, stress level
Write a 1-page Battleship Diagnosis Report in warm, non-shaming British tone:
•  Section 1: “Why it failed so far” – focus on system mismatch (not client weakness)
•  Section 2: “What will be different this time” – highlight simple, realistic Battleship approach (Zone 2, tracking, progressive strength, limiting dead calories)
•  Keep under 500 words, actionable, encouraging
Output format:
Battleship Diagnosis Report – [Client Name]
Why It Failed So Far
…
What Will Be Different This Time
…
Agent Tags (JSON)
{“main_goal”: “…”, “constraints”: […], “risk_flags”: {…}}

**OpenClaw Skill Pseudocode**  
```python
# skills/battleship-intake.py
def run_intake(form_text):
    prompt = build_diagnosis_prompt(form_text)
    report_raw = call_claude(prompt)  # via OpenClaw LLM call
    report_md, tags_json = parse_report(report_raw)
    write_to_vault("clients/client-name/diagnosis.md", report_md)
    return {"status": "report_generated", "tags": tags_json}