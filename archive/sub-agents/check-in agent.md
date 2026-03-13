# Check-in Agent – Battleship – Midlife Fitness Reset

**Purpose**  
Read client’s weekly logs → compare to targets → fill and update the client progress tracker template → generate adjustments + warm British coach message (praise first, one key correction, next week's focus).

**Input**  
JSON weekly log snapshot (from client upload or MyFitnessPal export):

```json
{
  "week": 6,
  "weight_kg": 89.5,
  "waist_cm": 98,
  "energy_score": 7,
  "steps_avg": 9200,
  "protein_g_avg": 145,
  "calories_avg": 2150,
  "alcohol_units": 8,
  "notes": "Knee played up mid-week, missed one workout"
}
Output
1.  Fully filled Battleship Client Progress Tracker markdown document (using the exact structure from [[client-progress-tracker-template]])
2.  Embedded warm coach message at the end
Logic Flow
1.  Load current client progress tracker file (if exists) or start from baseline
2.  Update “Current Progress” section with latest weekly data → calculate changes
3.  Compare against Battleship targets (steps 10k, protein 160g+, energy >7, alcohol minimal)
4.  Call Claude with the embedded prompt below to analyse logs and write the report
5.  Format the entire output as one markdown file: filled tracker + coach message
6.  Save/update in clients/[client-id]/progress-tracker.md
7.  Deliver coach message portion via email or Group post
Embedded Claude Prompt (must be used exactly)
You are the Check-in Agent for Battleship – Midlife Fitness Reset.

You MUST use the exact structure from the vault file [[client-progress-tracker-template]].

Weekly logs: [paste JSON here]

Targets: 10k steps avg, 160g+ protein avg, energy score >7, alcohol minimal (tracked)

Follow these steps exactly:
1. Load the template structure from [[client-progress-tracker-template]]
2. Fill "Current Progress" section with the provided logs → calculate and show changes (e.g. waist -7 cm, energy +3)
3. If previous tracker exists, carry forward baseline and historical changes
4. Update "Non-Scale Wins" with any qualitative notes from logs or previous messages (e.g. "back on bike", "more patient with kids")
5. Fill "Battleship Agent Notes / Trends" with:
   - Consistency rating (steps & logging)
   - Biggest win this period
   - Biggest challenge / correction
   - Recommended tweaks next week
   - Alcohol impact observation (if relevant)
   - Overall trajectory (Improving / Plateau / Needs adjustment)
6. Set "Next Check-in Date" and "Last Updated"
7. At the end, write a full coach message in warm British tone:
   - Praise wins first (specific & encouraging)
   - One key correction (gentle, non-shaming)
   - Next week's focus (actionable, realistic)
   - Keep message ~150–250 words

Output the ENTIRE filled tracker as markdown, followed by the coach message section.

Do not invent data — use only what is provided. If data is missing, mark as "not tracked this week" and note in Agent Notes.

OpenClaw Skill Pseudocode

def run_checkin(logs_json, client_id):
    # Load existing tracker if exists
    existing_tracker = read_from_vault(f"clients/{client_id}/progress-tracker.md") or ""
    
    prompt = build_checkin_prompt_with_tracker_instruction(logs_json, existing_tracker)
    full_report_raw = call_claude(prompt)  # via OpenClaw LLM call
    
    # Parse into sections (tracker + message)
    tracker_md, coach_message = parse_tracker_and_message(full_report_raw)
    
    # Save updated tracker
    write_to_vault(f"clients/{client_id}/progress-tracker.md", tracker_md)
    
    # Deliver message
    send_to_client(coach_message)  # email or Group post
    
    return {"status": "checkin_complete", "tracker_updated": True}