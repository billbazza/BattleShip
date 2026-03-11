#!/usr/bin/env python3
"""
Battleship Intake Extractor
Pulls latest Typeform responses and formats them into Battleship Diagnosis briefs.
API key is read securely from 1Password — never stored in code.
"""

import subprocess
import requests
import json
from datetime import datetime

# --- Config ---
FORM_ID = "wbD9VYUa"
OP_PATH = "op://Private/Typeform/credential"

# --- Question reference (maps Typeform field IDs to readable labels) ---
# Run with --map flag first time to print field ID mappings
FIELD_LABELS = {}


def get_api_key():
    """Fetch Typeform API key from 1Password."""
    try:
        result = subprocess.check_output(
            ["op", "read", OP_PATH],
            stderr=subprocess.STDOUT
        ).decode().strip()
        return result
    except subprocess.CalledProcessError as e:
        print("❌ Could not retrieve API key from 1Password.")
        print("   Make sure 1Password is unlocked and CLI is authenticated.")
        print(f"   Error: {e.output.decode()}")
        exit(1)


def get_responses(api_key, count=5):
    """Fetch latest N responses from Typeform."""
    url = f"https://api.typeform.com/forms/{FORM_ID}/responses"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"page_size": count, "sort": "submitted_at,desc"}

    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        print(f"❌ Typeform API error: {response.status_code}")
        print(response.text)
        exit(1)

    return response.json()


def get_form_fields(api_key):
    """Fetch form field definitions to map IDs to labels."""
    url = f"https://api.typeform.com/forms/{FORM_ID}"
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get(url, headers=headers)
    return response.json()


def extract_answer(answer):
    """Extract human-readable value from a Typeform answer object."""
    atype = answer.get("type")
    if atype == "text":
        return answer.get("text", "")
    elif atype == "email":
        return answer.get("email", "")
    elif atype == "number":
        return str(answer.get("number", ""))
    elif atype == "choice":
        return answer.get("choice", {}).get("label", "")
    elif atype == "choices":
        labels = answer.get("choices", {}).get("labels", [])
        other = answer.get("choices", {}).get("other", "")
        if other:
            labels.append(f"Other: {other}")
        return ", ".join(labels)
    elif atype == "boolean":
        return "Yes" if answer.get("boolean") else "No"
    elif atype == "long_text":
        return answer.get("text", "")
    else:
        return str(answer)


def format_diagnosis_brief(response_data, field_map):
    """Format a single response into a Battleship Diagnosis Brief."""
    answers = response_data.get("answers", [])
    submitted = response_data.get("submitted_at", "")

    # Build answer lookup by field ID
    answer_map = {}
    for answer in answers:
        field_id = answer.get("field", {}).get("id", "")
        answer_map[field_id] = extract_answer(answer)

    # Build readable Q&A pairs
    qa_pairs = []
    for field_id, label in field_map.items():
        value = answer_map.get(field_id, "[not answered]")
        qa_pairs.append(f"**{label}**\n{value}")

    brief = f"""
================================================================================
BATTLESHIP INTAKE BRIEF
Submitted: {submitted}
================================================================================

{chr(10).join(qa_pairs)}

================================================================================
END OF INTAKE BRIEF
================================================================================
"""
    return brief.strip()


def build_field_map(form_data):
    """Build a dict of field_id -> readable question label."""
    field_map = {}
    fields = form_data.get("fields", [])
    for field in fields:
        fid = field.get("id")
        title = field.get("title", "Unknown")
        field_map[fid] = title
    return field_map


def main():
    import sys
    map_mode = "--map" in sys.argv
    count = 1
    for arg in sys.argv[1:]:
        if arg.startswith("--count="):
            count = int(arg.split("=")[1])

    print("🔐 Fetching API key from 1Password...")
    api_key = get_api_key()
    print("✅ API key retrieved.\n")

    print("📋 Fetching form field definitions...")
    form_data = get_form_fields(api_key)
    field_map = build_field_map(form_data)

    if map_mode:
        print("\n--- Field ID Map ---")
        for fid, label in field_map.items():
            print(f"{fid}: {label}")
        return

    print(f"📥 Fetching {count} latest response(s)...\n")
    data = get_responses(api_key, count=count)
    items = data.get("items", [])

    if not items:
        print("📭 No responses found yet.")
        return

    print(f"✅ Found {len(items)} response(s).\n")

    for i, item in enumerate(items, 1):
        brief = format_diagnosis_brief(item, field_map)
        print(brief)

        # Save to vault
        timestamp = item.get("submitted_at", "unknown").replace(":", "-")[:16]
        name_answer = ""
        for answer in item.get("answers", []):
            if answer.get("type") == "text":
                name_answer = extract_answer(answer).lower().replace(" ", "-")
                break

        filename = f"intake-{name_answer}-{timestamp}.md" if name_answer else f"intake-{timestamp}.md"
        filepath = f"/Users/will/Obsidian-Vaults/BattleShip-Vault/clients/{filename}"

        with open(filepath, "w") as f:
            f.write(brief)
        print(f"\n💾 Saved to clients/{filename}\n")


if __name__ == "__main__":
    main()
