### File 5: `sub-agents/orchestrator.md`

```markdown
# Orchestrator – Battleship – Midlife Fitness Reset

**Purpose**  
Main agent that routes incoming tasks/data to the correct sub-agent/skill.  
Runs continuously via OpenClaw daemon or scheduled heartbeat.

**Input** (examples)  
- "new_client_form" → JSON form data  
- "weekly_logs" → client ID + log JSON  
- "research_pains" → query string  
- "content_needed" → topic

**Logic Flow**  
1. Read task type from input or vault trigger  
2. Route to correct skill/agent  
3. Collect output  
4. Write result to vault (client folder or learnings.md)  
5. Notify client/coach if needed (email/Group)

**OpenClaw Orchestrator Pseudocode**  
```python
# orchestrator.py (main loop)
while True:
    task = get_next_task()  # from webhook, schedule, or file watch
    if task.type == "intake":
        result = battleship_intake(task.form)
    elif task.type == "weekly_checkin":
        result = battleship_checkin(task.logs)
    elif task.type == "generate_plan":
        result = battleship_plan_gen(task.tags, task.level)
    elif task.type == "education_drip":
        result = battleship_education(task.context)
    save_result(result)
    heartbeat_sleep(3600)  # check every hour