def run_intake(form_text):
    prompt = f"You are the Intake Agent...\n\nRead this client's intake form:\n\n{form_text}\n\n..."  # full prompt above
    raw_response = call_claude(prompt)  # OpenClaw LLM call
    # Parse: split report and tags
    report_md = extract_report(raw_response)
    tags_json = extract_tags(raw_response)
    write_to_vault(f"clients/{client_id}/diagnosis.md", report_md)
    return {"status": "diagnosis_generated", "tags": tags_json}
NextOutput tags → Program Agent
### 2. sub-agents/program-agent.md

```markdown
# Program Agent – Battleship – Midlife Fitness Reset

**Purpose**  
Take Intake Agent tags + client fitness level → generate complete 12-week Battleship Plan in markdown.

**Input**  
JSON from Intake Agent + fitness level string:

```json
{
  "main_goal": "belly fat + energy",
  "constraints": ["desk job 9-5", "bad knee", "no home equipment"],
  "risk_flags": {"sleep": "poor", "alcohol": "10-15 units/wk"},
  "level": "restart"
}