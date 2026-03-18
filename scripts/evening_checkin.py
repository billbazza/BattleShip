#!/usr/bin/env python3
"""Evening check-in prompt via Telegram — runs at 18:00 daily."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.telegram_notify import send_message

send_message(
    "🌆 <b>End of day check-in</b>\n\n"
    "1. Any new ideas to add to the ideas bank?\n"
    "2. Pick one idea to green light for tomorrow\n"
    "3. How did today's posts perform?\n"
    "4. Anything to flag before tomorrow?\n\n"
    "Reply here — I'll log it and update the ideas bank."
)
