"""
Battleship Reset — Client Progress Tracker Generator

Served by Flask at /tracker/<account_no>
URL: https://webhook.battleshipreset.com/tracker/BSR-2026-XXXX

Features:
  - Per-set logging (3 rows per exercise)
  - Pre-fills from previous session
  - Smart "go heavier / harder variation" recommendations
  - Full session history
  - PWA — Add to Home Screen on iOS/Android
"""

import json
from pathlib import Path

# ── Programme library ──────────────────────────────────────────────────────────

PROGRAMMES = {

    "beginner_bodyweight": {
        "label": "Beginner Bodyweight",
        "frequency": "3× per week",
        "sessions": [
            {
                "name": "Full Body",
                "exercises": [
                    {"name": "Wall or Chair Squat",  "bodyweight": True},
                    {"name": "Knee Push-Up",          "bodyweight": True},
                    {"name": "Doorframe Row",         "bodyweight": True},
                    {"name": "Glute Bridge",          "bodyweight": True},
                    {"name": "Bird Dog",              "bodyweight": True},
                    {"name": "Plank Hold",            "bodyweight": True, "timed": True},
                ],
            }
        ],
        "blocks": [
            {"weeks": [1,2,3],  "sets": "2–3", "reps": "8–10",  "note": "Controlled, slow reps"},
            {"weeks": [4,5,6],  "sets": "3",   "reps": "10–12", "note": "Add reps when easy"},
            {"weeks": [7,8,9],  "sets": "3",   "reps": "12–15", "note": "Push near failure on last set"},
            {"weeks": [10,11],  "sets": "3–4", "reps": "max",   "note": "Test your limits"},
        ],
    },

    "bodyweight_full": {
        "label": "Bodyweight Full Body",
        "frequency": "3× per week",
        "sessions": [
            {
                "name": "Full Body",
                "exercises": [
                    {"name": "Air Squat",      "bodyweight": True},
                    {"name": "Push-Up",        "bodyweight": True},
                    {"name": "Inverted Row",   "bodyweight": True},
                    {"name": "Walking Lunge",  "bodyweight": True},
                    {"name": "Pike Push-Up",   "bodyweight": True},
                    {"name": "Plank",          "bodyweight": True, "timed": True},
                ],
            }
        ],
        "blocks": [
            {"weeks": [1,2,3],  "sets": "3",   "reps": "8–12",  "note": "Baseline — find your rep range"},
            {"weeks": [4,5,6],  "sets": "3–4", "reps": "10–15", "note": "Progress to harder variations"},
            {"weeks": [7,8,9],  "sets": "4",   "reps": "10–15", "note": "Add harder variations"},
            {"weeks": [10,11],  "sets": "4",   "reps": "max",   "note": "Push to failure on last set"},
        ],
    },

    "bodyweight_hiit": {
        "label": "Bodyweight HIIT",
        "frequency": "3× per week",
        "sessions": [
            {
                "name": "HIIT Circuit",
                "exercises": [
                    {"name": "Squat Jump",          "bodyweight": True},
                    {"name": "Push-Up",             "bodyweight": True},
                    {"name": "Alternating Lunge",   "bodyweight": True},
                    {"name": "Mountain Climbers",   "bodyweight": True, "timed": True},
                    {"name": "Burpee",              "bodyweight": True},
                    {"name": "High Knees",          "bodyweight": True, "timed": True},
                    {"name": "Bicycle Crunch",      "bodyweight": True},
                ],
            }
        ],
        "blocks": [
            {"weeks": [1,2,3],  "sets": "2", "reps": "30s on / 30s off", "note": "Work up to full circuit"},
            {"weeks": [4,5,6],  "sets": "3", "reps": "40s on / 20s off", "note": "Reduce rest time"},
            {"weeks": [7,8,9],  "sets": "3", "reps": "45s on / 15s off", "note": "Increase intensity"},
            {"weeks": [10,11],  "sets": "4", "reps": "50s on / 10s off", "note": "Max effort"},
        ],
    },

    "resistance_bands": {
        "label": "Resistance Bands",
        "frequency": "3× per week",
        "sessions": [
            {
                "name": "Full Body",
                "exercises": [
                    {"name": "Banded Squat"},
                    {"name": "Banded Hip Hinge"},
                    {"name": "Banded Chest Press"},
                    {"name": "Banded Row"},
                    {"name": "Banded Lateral Raise"},
                    {"name": "Banded Bicep Curl"},
                    {"name": "Plank", "bodyweight": True, "timed": True},
                ],
            }
        ],
        "blocks": [
            {"weeks": [1,2,3],  "sets": "3",   "reps": "12–15", "note": "Light band — nail the movement"},
            {"weeks": [4,5,6],  "sets": "3–4", "reps": "12–15", "note": "Move to heavier band"},
            {"weeks": [7,8,9],  "sets": "4",   "reps": "10–12", "note": "Heavier band, controlled reps"},
            {"weeks": [10,11],  "sets": "4",   "reps": "10–12", "note": "Pause at peak contraction"},
        ],
    },

    "dumbbell_full_body": {
        "label": "Dumbbell Full Body",
        "frequency": "3× per week",
        "sessions": [
            {
                "name": "Full Body",
                "exercises": [
                    {"name": "Goblet Squat"},
                    {"name": "Dumbbell Romanian Deadlift"},
                    {"name": "Dumbbell Bench Press"},
                    {"name": "Bent-Over Dumbbell Row"},
                    {"name": "Overhead Press"},
                    {"name": "Reverse Lunge"},
                    {"name": "Plank", "bodyweight": True, "timed": True},
                ],
            }
        ],
        "blocks": [
            {"weeks": [1,2,3],  "sets": "3",   "reps": "8–12",  "note": "Baseline — find working weight"},
            {"weeks": [4,5,6],  "sets": "3–4", "reps": "8–12",  "note": "Add set when form is solid"},
            {"weeks": [7,8,9],  "sets": "4",   "reps": "6–10",  "note": "Heavier — strength focus"},
            {"weeks": [10,11],  "sets": "4",   "reps": "6–10",  "note": "Drop set or rest-pause on final set"},
        ],
    },

    "home_complete": {
        "label": "Home Complete",
        "frequency": "3× per week",
        "sessions": [
            {
                "name": "Upper",
                "exercises": [
                    {"name": "Dumbbell Bench Press"},
                    {"name": "Dumbbell Row"},
                    {"name": "Overhead Press"},
                    {"name": "Pull-Up",            "bodyweight": True},
                    {"name": "Band Face Pull"},
                    {"name": "Dumbbell Bicep Curl"},
                ],
            },
            {
                "name": "Lower + Core",
                "exercises": [
                    {"name": "Goblet Squat"},
                    {"name": "Romanian Deadlift"},
                    {"name": "Reverse Lunge"},
                    {"name": "Lateral Raise"},
                    {"name": "Dead Bug",  "bodyweight": True},
                    {"name": "Plank",     "bodyweight": True, "timed": True},
                ],
            },
        ],
        "blocks": [
            {"weeks": [1,2,3],  "sets": "3",   "reps": "8–12",  "note": "Establish baseline weights"},
            {"weeks": [4,5,6],  "sets": "3–4", "reps": "8–12",  "note": "Increase load each session"},
            {"weeks": [7,8,9],  "sets": "4",   "reps": "6–10",  "note": "Strength focus"},
            {"weeks": [10,11],  "sets": "4",   "reps": "6–10",  "note": "Peak — drop set on final set"},
        ],
    },

    "gym_beginner": {
        "label": "Gym Beginner (Machines)",
        "frequency": "3× per week",
        "sessions": [
            {
                "name": "Full Body",
                "exercises": [
                    {"name": "Leg Press"},
                    {"name": "Chest Press Machine"},
                    {"name": "Lat Pulldown"},
                    {"name": "Seated Cable Row"},
                    {"name": "Shoulder Press Machine"},
                    {"name": "Leg Curl Machine"},
                    {"name": "Plank", "bodyweight": True, "timed": True},
                ],
            }
        ],
        "blocks": [
            {"weeks": [1,2,3],  "sets": "3",   "reps": "10–12", "note": "Light weight — learn the machines"},
            {"weeks": [4,5,6],  "sets": "3",   "reps": "10–12", "note": "Add weight each session"},
            {"weeks": [7,8,9],  "sets": "3–4", "reps": "8–10",  "note": "Heavier — push near failure on last set"},
            {"weeks": [10,11],  "sets": "4",   "reps": "8–10",  "note": "Record your weights — beat them next time"},
        ],
    },

    "gym_intermediate": {
        "label": "Gym Intermediate (Push / Pull / Legs)",
        "frequency": "3× per week",
        "sessions": [
            {
                "name": "Push",
                "exercises": [
                    {"name": "Bench Press"},
                    {"name": "Dumbbell Overhead Press"},
                    {"name": "Incline Dumbbell Press",    "start_week": 4},
                    {"name": "Lateral Raise"},
                    {"name": "Tricep Pushdown"},
                    {"name": "Overhead Tricep Extension"},
                ],
            },
            {
                "name": "Pull",
                "exercises": [
                    {"name": "Barbell Row"},
                    {"name": "Lat Pulldown"},
                    {"name": "Seated Cable Row",  "start_week": 3},
                    {"name": "Face Pull"},
                    {"name": "Dumbbell Bicep Curl"},
                    {"name": "Hammer Curl",       "start_week": 5},
                ],
            },
            {
                "name": "Legs",
                "exercises": [
                    {"name": "Barbell Back Squat"},
                    {"name": "Romanian Deadlift"},
                    {"name": "Leg Press"},
                    {"name": "Leg Curl Machine"},
                    {"name": "Walking Lunge",  "start_week": 3},
                    {"name": "Calf Raise"},
                ],
            },
        ],
        "blocks": [
            {"weeks": [1,2,3],  "sets": "3",   "reps": "8–10",  "note": "Find working weights — form first"},
            {"weeks": [4,5,6],  "sets": "3–4", "reps": "8–10",  "note": "Add weight each session where form holds"},
            {"weeks": [7,8,9],  "sets": "4",   "reps": "6–8",   "note": "Strength phase — heavier, lower reps"},
            {"weeks": [10,11],  "sets": "4",   "reps": "6–8",   "note": "Last set to near failure — record new maxes"},
        ],
    },
}

VIDEO_SEARCHES = {
    "Wall or Chair Squat":        "wall squat beginners tutorial",
    "Knee Push-Up":               "knee push up form beginners",
    "Doorframe Row":              "doorframe row bodyweight exercise how to",
    "Glute Bridge":               "glute bridge form tutorial",
    "Bird Dog":                   "bird dog exercise core tutorial",
    "Plank Hold":                 "plank hold form tutorial",
    "Plank":                      "plank exercise form tutorial",
    "Air Squat":                  "air squat form tutorial",
    "Push-Up":                    "push up perfect form tutorial",
    "Inverted Row":               "inverted row bodyweight tutorial",
    "Walking Lunge":              "walking lunge form tutorial",
    "Pike Push-Up":               "pike push up form tutorial",
    "Squat Jump":                 "squat jump form tutorial",
    "Alternating Lunge":          "alternating lunge form tutorial",
    "Mountain Climbers":          "mountain climbers exercise tutorial",
    "Burpee":                     "burpee form tutorial beginners",
    "High Knees":                 "high knees exercise tutorial",
    "Bicycle Crunch":             "bicycle crunch ab exercise tutorial",
    "Banded Squat":               "resistance band squat form tutorial",
    "Banded Hip Hinge":           "resistance band hip hinge tutorial",
    "Banded Chest Press":         "resistance band chest press tutorial",
    "Banded Row":                 "resistance band row tutorial",
    "Banded Lateral Raise":       "resistance band lateral raise tutorial",
    "Banded Bicep Curl":          "resistance band bicep curl tutorial",
    "Goblet Squat":               "goblet squat form tutorial",
    "Dumbbell Romanian Deadlift": "dumbbell romanian deadlift form tutorial",
    "Dumbbell Bench Press":       "dumbbell bench press form tutorial",
    "Bent-Over Dumbbell Row":     "bent over dumbbell row form tutorial",
    "Overhead Press":             "dumbbell overhead press form tutorial",
    "Reverse Lunge":              "reverse lunge dumbbell form tutorial",
    "Dumbbell Row":               "dumbbell row form tutorial",
    "Band Face Pull":             "face pull exercise tutorial",
    "Dumbbell Bicep Curl":        "dumbbell bicep curl form tutorial",
    "Romanian Deadlift":          "romanian deadlift form tutorial",
    "Lateral Raise":              "lateral raise dumbbell form tutorial",
    "Dead Bug":                   "dead bug core exercise tutorial",
    "Pull-Up":                    "pull up form tutorial beginners",
    "Leg Press":                  "leg press machine form tutorial",
    "Chest Press Machine":        "chest press machine form tutorial",
    "Lat Pulldown":               "lat pulldown form tutorial",
    "Seated Cable Row":           "seated cable row form tutorial",
    "Shoulder Press Machine":     "shoulder press machine form tutorial",
    "Leg Curl Machine":           "leg curl machine form tutorial",
    "Bench Press":                "barbell bench press form tutorial",
    "Dumbbell Overhead Press":    "dumbbell overhead press seated tutorial",
    "Incline Dumbbell Press":     "incline dumbbell press form tutorial",
    "Tricep Pushdown":            "tricep pushdown cable form tutorial",
    "Overhead Tricep Extension":  "overhead tricep extension form tutorial",
    "Barbell Row":                "barbell row form tutorial",
    "Face Pull":                  "face pull cable form tutorial",
    "Hammer Curl":                "hammer curl form tutorial",
    "Barbell Back Squat":         "barbell back squat form tutorial",
    "Calf Raise":                 "calf raise machine form tutorial",
}


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Battleship">
  <meta name="theme-color" content="#0d0d0d">
  <title>Battleship Tracker</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}}
    html,body{{height:100%;background:#0d0d0d;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;overscroll-behavior:none;font-size:16px}}
    body{{max-width:480px;margin:0 auto}}

    /* ── Header ── */
    .hdr{{background:#111;padding:14px 18px 12px;border-bottom:2px solid #c41e3a;position:sticky;top:0;z-index:100;display:flex;align-items:center;justify-content:space-between}}
    .hdr-left .logo{{font-size:10px;letter-spacing:3px;text-transform:uppercase;color:#c41e3a;font-weight:700}}
    .hdr-left .cname{{font-size:12px;color:#555;margin-top:3px}}
    .hdr-right button{{background:none;border:1px solid #333;color:#666;border-radius:8px;padding:7px 12px;font-size:11px;letter-spacing:1px;text-transform:uppercase;cursor:pointer}}

    /* ── Week bar ── */
    .wkbar{{background:#161616;padding:18px 18px 14px}}
    .wkbar-top{{display:flex;align-items:flex-start;justify-content:space-between}}
    .wknum{{font-size:26px;font-weight:800;letter-spacing:-0.5px}}
    .wknum span{{font-size:15px;color:#444;font-weight:400}}
    .wknote{{font-size:11px;color:#555;margin-top:4px;letter-spacing:0.5px;line-height:1.5}}
    .prog{{background:#222;height:3px;border-radius:2px;margin-top:14px}}
    .prog-fill{{background:#c41e3a;height:3px;border-radius:2px;transition:width .4s ease}}
    .wk-nav{{display:flex;gap:6px;margin-top:0}}
    .wk-nav button{{background:#1e1e1e;border:1px solid #2a2a2a;color:#666;border-radius:6px;padding:6px 10px;font-size:13px;cursor:pointer}}
    .wk-nav button:hover{{border-color:#c41e3a;color:#fff}}

    /* ── View toggle ── */
    .vtabs{{display:flex;background:#111;border-bottom:1px solid #1a1a1a}}
    .vtab{{flex:1;padding:12px 8px;text-align:center;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;font-weight:600;cursor:pointer;color:#444;border-bottom:2px solid transparent;transition:all .15s}}
    .vtab.on{{color:#fff;border-bottom-color:#c41e3a}}

    /* ── Session tabs ── */
    .stabs{{display:flex;background:#0d0d0d;border-bottom:1px solid #1a1a1a}}
    .stab{{flex:1;padding:12px 6px;text-align:center;font-size:11px;letter-spacing:1px;text-transform:uppercase;font-weight:600;cursor:pointer;color:#444;border-bottom:2px solid transparent;transition:all .15s}}
    .stab.on{{color:#fff;border-bottom-color:#c41e3a}}

    /* ── Exercise card ── */
    .ex-list{{padding-bottom:110px}}
    .ex-card{{border-bottom:1px solid #161616;padding:14px 18px 16px}}
    .ex-card.future{{opacity:0.3}}

    .ex-hdr{{display:flex;align-items:center;justify-content:space-between;margin-bottom:3px}}
    .ex-name{{font-size:15px;font-weight:700;flex:1;line-height:1.3}}
    .vid-btn{{background:none;border:none;color:#c41e3a;font-size:20px;padding:2px 6px;cursor:pointer;line-height:1;flex-shrink:0}}

    .ex-meta{{font-size:11px;color:#555;margin-bottom:10px;letter-spacing:0.3px}}

    /* Recommendation pill */
    .rec{{display:inline-flex;align-items:center;gap:5px;background:#1a0a0a;border:1px solid #c41e3a33;border-radius:20px;padding:5px 10px;font-size:11px;color:#e07070;margin-bottom:10px;line-height:1.3}}
    .rec.harder{{background:#0a1a0a;border-color:#4caf5033;color:#7cd47c}}

    /* Set rows */
    .set-rows{{display:flex;flex-direction:column;gap:6px}}
    .set-row{{display:flex;align-items:center;gap:7px}}
    .set-lbl{{font-size:11px;color:#444;width:36px;text-align:right;flex-shrink:0;letter-spacing:0.5px}}
    .inp{{background:#1a1a1a;border:1.5px solid #252525;color:#fff;border-radius:9px;padding:10px 6px;font-size:15px;text-align:center;-webkit-appearance:none;appearance:none;transition:border-color .15s;min-width:0}}
    .inp:focus{{border-color:#c41e3a;outline:none;background:#1e1e1e}}
    .inp.w{{width:72px}}
    .inp.r{{width:64px}}
    .inp-lbl{{font-size:9px;color:#333;text-align:center;margin-top:3px;letter-spacing:0.5px}}
    .inp-wrap{{display:flex;flex-direction:column;flex-shrink:0}}
    .sep{{font-size:13px;color:#333;padding:0 1px;flex-shrink:0}}
    .done-btn{{width:42px;height:42px;border-radius:9px;background:#1a1a1a;border:1.5px solid #252525;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:18px;transition:all .15s;flex-shrink:0;color:#444}}
    .done-btn.on{{background:#c41e3a;border-color:#c41e3a;color:#fff}}

    .add-set-btn{{margin-top:8px;background:none;border:1px dashed #2a2a2a;color:#555;border-radius:8px;padding:7px 14px;font-size:11px;letter-spacing:1px;text-transform:uppercase;cursor:pointer;width:100%;transition:all .15s}}
    .add-set-btn:hover{{border-color:#c41e3a;color:#c41e3a}}

    /* ── Save bar ── */
    .save-bar{{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:480px;padding:10px 14px;background:#0d0d0d;border-top:1px solid #1a1a1a}}
    .save-btn{{width:100%;background:#c41e3a;color:#fff;font-size:13px;font-weight:700;letter-spacing:2px;text-transform:uppercase;padding:15px;border:none;border-radius:11px;cursor:pointer;transition:background .2s}}
    .save-btn.done{{background:#1a4a1a}}

    /* ── History ── */
    .hist{{padding:16px 18px 110px}}
    .hist-wk{{background:#111;border-radius:10px;padding:14px;margin-bottom:10px;border:1px solid #1a1a1a}}
    .hist-hdr{{font-size:10px;font-weight:700;color:#c41e3a;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px}}
    .hist-ex{{display:flex;justify-content:space-between;align-items:flex-start;padding:6px 0;border-bottom:1px solid #1a1a1a;font-size:13px;gap:8px}}
    .hist-ex:last-child{{border:none}}
    .hist-sets{{color:#666;font-size:11px;margin-top:2px;line-height:1.6}}
    .hist-done{{color:#4caf50}}

    /* ── Info / Install ── */
    .info-page{{padding:18px 18px 110px}}
    .info-section{{background:#111;border-radius:10px;padding:16px;margin-bottom:12px;border:1px solid #1a1a1a}}
    .info-section h3{{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#c41e3a;margin-bottom:10px}}
    .info-section p{{font-size:13px;color:#888;line-height:1.7;margin-bottom:8px}}
    .info-section p:last-child{{margin-bottom:0}}
    .info-section ul{{padding-left:18px;color:#888;font-size:13px;line-height:1.8}}
    .install-step{{display:flex;gap:12px;align-items:flex-start;margin-bottom:12px}}
    .install-num{{background:#c41e3a;color:#fff;width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0;margin-top:1px}}
    .install-text{{font-size:13px;color:#888;line-height:1.6}}
    .install-text strong{{color:#ccc}}

    /* ── Empty state ── */
    .empty{{color:#444;text-align:center;padding:50px 20px;font-size:13px;line-height:2}}
  </style>
</head>
<body>

<div class="hdr">
  <div class="hdr-left">
    <div class="logo">&#9875; Battleship Reset</div>
    <div class="cname" id="cname"></div>
  </div>
  <div class="hdr-right">
    <button onclick="view='info';render()">&#9432; Help</button>
  </div>
</div>

<div id="app"></div>

<script>
// ── Data ──────────────────────────────────────────────────────────────────────
const CLIENT    = {client_json};
const PROGRAMME = {programme_json};
const VIDEOS    = {videos_json};

// ── State ─────────────────────────────────────────────────────────────────────
let viewWeek   = null;   // null = auto
// Show guide on first ever open, today on return visits
const _hasHistory = (() => {{
  for (let w = 1; w <= 11; w++)
    for (let si = 0; si < PROGRAMME.sessions.length; si++)
      if (Object.values(getLog(w,si)).some(v => v?.sets?.some(s=>s.done))) return true;
  return false;
}})();
let view = _hasHistory ? 'today' : 'info';

// Auto-select next session in sequence based on last completed
function nextSessionIdx() {{
  if (PROGRAMME.sessions.length <= 1) return 0;
  const week = autoWeek();
  // Find the last session that has any done sets, scanning all weeks newest first
  for (let w = week; w >= 1; w--) {{
    for (let si = PROGRAMME.sessions.length - 1; si >= 0; si--) {{
      const log = getLog(w, si);
      const done = Object.values(log).some(v => v?.sets?.some(s => s.done));
      if (done) return (si + 1) % PROGRAMME.sessions.length; // next in sequence
    }}
  }}
  return 0; // nothing logged yet — start at first session
}}
let sessionIdx = nextSessionIdx();

// ── Storage ───────────────────────────────────────────────────────────────────
function skey(week, si) {{
  return 'bsr2_' + CLIENT.account_no + '_w' + week + '_s' + si;
}}
function saveLog(week, si, data) {{
  localStorage.setItem(skey(week, si), JSON.stringify(data));
}}
function getLog(week, si) {{
  try {{ return JSON.parse(localStorage.getItem(skey(week, si))) || {{}}; }}
  catch(e) {{ return {{}}; }}
}}

// ── Week helpers ──────────────────────────────────────────────────────────────
function autoWeek() {{
  const enrolled = new Date(CLIENT.enrolled_date);
  const today    = new Date();
  const days     = Math.floor((today - enrolled) / 86400000);
  return Math.min(Math.max(Math.floor(days / 7) + 1, 1), 11);
}}
function currentWeek() {{
  return viewWeek !== null ? viewWeek : autoWeek();
}}
function getBlock(week) {{
  return PROGRAMME.blocks.find(b => b.weeks.includes(week)) || PROGRAMME.blocks[0];
}}

// ── Set count parsing ─────────────────────────────────────────────────────────
function parseSets(block) {{
  const s = String(block.sets);
  const m = s.match(/(\d+)[^\d]*(\d+)?/);
  const min = m ? parseInt(m[1]) : 3;
  const max = (m && m[2]) ? parseInt(m[2]) : min;
  return {{min, max}};
}}

// ── Rep range parsing ─────────────────────────────────────────────────────────
function topReps(block) {{
  const reps = String(block.reps);
  const m = reps.match(/(\d+)\s*$|^(\d+)$/);
  return m ? parseInt(m[1] || m[2]) : 999;
}}

// ── Previous session lookup ───────────────────────────────────────────────────
function prevLog(si) {{
  const week = currentWeek();
  for (let w = week - 1; w >= 1; w--) {{
    const log = getLog(w, si);
    if (log && Object.keys(log).some(k => k !== '_sets' && log[k] && log[k].sets && log[k].sets.length)) {{
      return log;
    }}
  }}
  return null;
}}

// ── Recommendation ────────────────────────────────────────────────────────────
function getRecommendation(exName, ex, block, si) {{
  const prev = prevLog(si);
  if (!prev || !prev[exName] || !prev[exName].sets) return null;
  const sets = prev[exName].sets.filter(s => s.done);
  if (sets.length === 0) return null;

  const top = topReps(block);
  const avgReps = sets.reduce((sum, s) => sum + (parseInt(s.reps) || 0), 0) / sets.length;
  const lastWeight = parseFloat(sets.find(s => s.weight)?.weight || 0);
  const isBodyweight = ex.bodyweight || (!lastWeight);

  if (avgReps >= top && top < 999) {{
    if (isBodyweight) {{
      return {{type: 'harder', msg: 'You hit max reps last session \u2014 progress to a harder variation'}};
    }} else {{
      const next = (lastWeight + 2.5).toFixed(1).replace(/\.0$/, '');
      return {{type: 'heavier', msg: `You hit \u2265${{top}} reps last time \u2014 try ${{next}}kg today`}};
    }}
  }}
  return null;
}}

// ── Auto-save all inputs ──────────────────────────────────────────────────────
function snapshot(week, si) {{
  const session = PROGRAMME.sessions[si];
  const log     = getLog(week, si);
  session.exercises.forEach((ex, ei) => {{
    if (!log[ex.name]) log[ex.name] = {{sets: []}};
    const numRows = parseInt(document.getElementById('nsets_' + ei)?.value || '3');
    const sets = [];
    for (let s = 0; s < numRows; s++) {{
      const wEl = document.getElementById(`w_${{ei}}_${{s}}`);
      const rEl = document.getElementById(`r_${{ei}}_${{s}}`);
      const dEl = document.getElementById(`d_${{ei}}_${{s}}`);
      sets.push({{
        weight: wEl?.value || '',
        reps:   rEl?.value || '',
        done:   dEl?.dataset.done === '1',
      }});
    }}
    log[ex.name].sets = sets;
  }});
  saveLog(week, si, log);
}}

function toggleDone(ei, si, setIdx) {{
  const week = currentWeek();
  snapshot(week, si);
  const log = getLog(week, si);
  const ex = PROGRAMME.sessions[si].exercises[ei];
  if (!log[ex.name]) log[ex.name] = {{sets:[]}};
  if (!log[ex.name].sets[setIdx]) log[ex.name].sets[setIdx] = {{}};
  const cur = log[ex.name].sets[setIdx].done || false;
  log[ex.name].sets[setIdx].done = !cur;
  saveLog(week, si, log);

  const btn = document.getElementById(`d_${{ei}}_${{setIdx}}`);
  if (btn) {{
    btn.dataset.done = log[ex.name].sets[setIdx].done ? '1' : '0';
    btn.className = 'done-btn' + (log[ex.name].sets[setIdx].done ? ' on' : '');
  }}
  updateSaveBtn();
}}

function addSet(ei, si) {{
  const week  = currentWeek();
  const block = getBlock(week);
  const {{max}} = parseSets(block);
  const hidEl = document.getElementById('nsets_' + ei);
  let n = parseInt(hidEl.value);
  if (n >= max) return;
  hidEl.value = n + 1;

  const container = document.getElementById('setrows_' + ei);
  const prev = getLog(week, si);
  const exName = PROGRAMME.sessions[si].exercises[ei].name;
  const prevSets = prev?.[exName]?.sets || [];
  const prevSet  = prevSets[n] || prevSets[n-1] || {{}};

  const row = document.createElement('div');
  row.className = 'set-row';
  row.id = 'setrow_' + ei + '_' + n;
  row.innerHTML = `
    <span class="set-lbl">SET ${{n+1}}</span>
    <div class="inp-wrap">
      <input class="inp w" type="number" inputmode="decimal" placeholder="\u2014"
        id="w_${{ei}}_${{n}}" value="${{prevSet.weight||''}}" oninput="snapshot(${{week}},${{si}})">
      <div class="inp-lbl">kg / lbs</div>
    </div>
    <span class="sep">&times;</span>
    <div class="inp-wrap">
      <input class="inp r" type="number" inputmode="numeric" placeholder="\u2014"
        id="r_${{ei}}_${{n}}" value="${{prevSet.reps||''}}" oninput="snapshot(${{week}},${{si}})">
      <div class="inp-lbl">reps</div>
    </div>
    <button class="done-btn" id="d_${{ei}}_${{n}}" data-done="0"
      onclick="toggleDone(${{ei}},${{si}},${{n}})">&#10003;</button>`;
  container.appendChild(row);
}}

function saveSession(week, si) {{
  snapshot(week, si);
  const log     = getLog(week, si);
  const session = PROGRAMME.sessions[si];
  session.exercises.forEach((ex, ei) => {{
    if (!log[ex.name]) log[ex.name] = {{sets:[]}};
    const numRows = parseInt(document.getElementById('nsets_' + ei)?.value || '3');
    log[ex.name].sets = (log[ex.name].sets || []).map((s, idx) =>
      idx < numRows ? {{...s, done: true}} : s
    );
    if ((log[ex.name].sets || []).length === 0) {{
      log[ex.name].sets = Array(numRows).fill(null).map(() => ({{done:true}}));
    }}
  }});
  saveLog(week, si, log);
  render();
}}

function updateSaveBtn() {{
  const week = currentWeek();
  const si   = sessionIdx;
  const btn  = document.getElementById('savebtn');
  if (!btn) return;
  const allDone = isAllDone(week, si);
  btn.className = 'save-btn' + (allDone ? ' done' : '');
  btn.innerHTML = allDone ? '&#10003; Session Complete' : 'Mark All Done &amp; Save';
}}

function isAllDone(week, si) {{
  const log     = getLog(week, si);
  const session = PROGRAMME.sessions[si];
  return session.exercises
    .filter(ex => !ex.start_week || week >= ex.start_week)
    .every(ex => {{
      const sets = log?.[ex.name]?.sets || [];
      return sets.length > 0 && sets.some(s => s.done);
    }});
}}

// ── Render today ──────────────────────────────────────────────────────────────
function renderToday() {{
  const week    = currentWeek();
  const block   = getBlock(week);
  const pct     = Math.round((week / 11) * 100);
  const auto    = autoWeek();

  let html = `
    <div class="wkbar">
      <div class="wkbar-top">
        <div>
          <div class="wknum">Week ${{week}} <span>of 11</span></div>
          <div class="wknote">${{block.sets}} sets &times; ${{block.reps}}&nbsp;&nbsp;&bull;&nbsp;&nbsp;${{block.note}}</div>
        </div>
        <div class="wk-nav">
          <button onclick="viewWeek=Math.max(1,(viewWeek||${{auto}})-1);render()" title="Previous week">&larr;</button>
          <button onclick="viewWeek=Math.min(11,(viewWeek||${{auto}})+1);render()" title="Next week">&rarr;</button>
        </div>
      </div>
      <div class="prog"><div class="prog-fill" style="width:${{pct}}%"></div></div>
    </div>`;

  // View tabs
  html += `<div class="vtabs">
    <div class="vtab on" onclick="view='today';render()">Today</div>
    <div class="vtab" onclick="view='history';render()">History</div>
    <div class="vtab" onclick="view='info';render()">Info</div>
  </div>`;

  // Session tabs
  const sessions = PROGRAMME.sessions;
  if (sessions.length > 1) {{
    html += '<div class="stabs">';
    sessions.forEach((s, i) => {{
      const done = isAllDone(week, i);
      html += `<div class="stab${{i===sessionIdx?' on':''}}" onclick="sessionIdx=${{i}};render()">${{s.name}}${{done?' &#10003;':''}}</div>`;
    }});
    html += '</div>';
  }}

  const session = sessions[sessionIdx];
  const log     = getLog(week, sessionIdx);
  const prev    = prevLog(sessionIdx);
  const {{min: minSets, max: maxSets}} = parseSets(block);

  html += '<div class="ex-list">';
  session.exercises.forEach((ex, ei) => {{
    const future = ex.start_week && week < ex.start_week;
    if (future) {{
      html += `<div class="ex-card future">
        <div class="ex-hdr"><div class="ex-name">${{ex.name}}</div></div>
        <div class="ex-meta">Starts Week ${{ex.start_week}}</div>
      </div>`;
      return;
    }}

    const prevSets = prev?.[ex.name]?.sets || [];
    const savedSets = log?.[ex.name]?.sets || [];
    // Use saved if exists, else pre-fill from prev
    const displaySets = savedSets.length ? savedSets : prevSets;
    const numRows = Math.max(minSets, displaySets.length || minSets);

    const rec = getRecommendation(ex.name, ex, block, sessionIdx);

    const timeLabel = ex.timed ? 'secs' : 'reps';

    let recHtml = '';
    if (rec) {{
      recHtml = `<div class="rec${{rec.type==='harder'?' harder':''}}">${{rec.type==='harder'?'&#9650;':'&#9651;'}} ${{rec.msg}}</div>`;
    }} else if (prevSets.length) {{
      const w = prevSets.find(s=>s.weight)?.weight;
      const r = prevSets.find(s=>s.reps)?.reps;
      if (w || r) {{
        recHtml = `<div style="font-size:11px;color:#555;margin-bottom:8px;">Last: ${{w?w+'kg ':''}}${{r?'&times; '+r+(ex.timed?' secs':' reps'):''}}</div>`;
      }}
    }}

    let setRowsHtml = '';
    for (let s = 0; s < numRows; s++) {{
      const ds = displaySets[s] || {{}};
      const isDone = ds.done || false;
      setRowsHtml += `
        <div class="set-row" id="setrow_${{ei}}_${{s}}">
          <span class="set-lbl">SET ${{s+1}}</span>
          <div class="inp-wrap">
            <input class="inp w" type="number" inputmode="decimal" placeholder="&mdash;"
              id="w_${{ei}}_${{s}}" value="${{ds.weight||''}}" oninput="snapshot(${{week}},${{sessionIdx}})">
            <div class="inp-lbl">kg / lbs</div>
          </div>
          <span class="sep">&times;</span>
          <div class="inp-wrap">
            <input class="inp r" type="number" inputmode="numeric" placeholder="&mdash;"
              id="r_${{ei}}_${{s}}" value="${{ds.reps||''}}" oninput="snapshot(${{week}},${{sessionIdx}})">
            <div class="inp-lbl">${{timeLabel}}</div>
          </div>
          <button class="done-btn${{isDone?' on':''}}" id="d_${{ei}}_${{s}}" data-done="${{isDone?1:0}}"
            onclick="toggleDone(${{ei}},${{sessionIdx}},${{s}})">&#10003;</button>
        </div>`;
    }}

    const canAdd = numRows < maxSets;

    html += `
      <div class="ex-card">
        <input type="hidden" id="nsets_${{ei}}" value="${{numRows}}">
        <div class="ex-hdr">
          <div class="ex-name">${{ex.name}}</div>
          <button class="vid-btn" onclick="window.open('https://www.youtube.com/results?search_query=${{encodeURIComponent(VIDEOS['${{ex.name}}']||ex.name+' form tutorial')}}','_blank')" title="How-to video">&#9654;</button>
        </div>
        <div class="ex-meta">${{block.sets}} sets &times; ${{block.reps}}</div>
        ${{recHtml}}
        <div class="set-rows" id="setrows_${{ei}}">${{setRowsHtml}}</div>
        ${{canAdd ? `<button class="add-set-btn" onclick="addSet(${{ei}},${{sessionIdx}})">+ Add set</button>` : ''}}
      </div>`;
  }});
  html += '</div>';

  const allDone = isAllDone(week, sessionIdx);
  html += `<div class="save-bar">
    <button class="save-btn${{allDone?' done':''}}" id="savebtn" onclick="saveSession(${{week}},${{sessionIdx}})">
      ${{allDone ? '&#10003; Session Complete' : 'Mark All Done &amp; Save'}}
    </button>
  </div>`;

  return html;
}}

// ── Render history ────────────────────────────────────────────────────────────
function renderHistory() {{
  let html = `<div class="vtabs">
    <div class="vtab" onclick="view='today';render()">Today</div>
    <div class="vtab on">History</div>
    <div class="vtab" onclick="view='info';render()">Info</div>
  </div><div class="hist">`;

  let any = false;
  for (let w = 11; w >= 1; w--) {{
    PROGRAMME.sessions.forEach((session, si) => {{
      const log = getLog(w, si);
      const hasData = Object.entries(log).some(([k,v]) => k !== '_saved' && v?.sets?.some(s => s.done || s.reps));
      if (!hasData) return;
      any = true;
      html += `<div class="hist-wk">
        <div class="hist-hdr">Week ${{w}}${{PROGRAMME.sessions.length > 1 ? ' &mdash; ' + session.name : ''}}</div>`;
      session.exercises.forEach(ex => {{
        const d = log[ex.name];
        if (!d?.sets?.length) return;
        const doneSets = d.sets.filter(s => s.done || s.reps);
        if (!doneSets.length) return;
        const setStrs = doneSets.map(s =>
          [s.weight ? s.weight+'kg' : '', s.reps ? '&times;'+s.reps : ''].filter(Boolean).join(' ')
        ).filter(Boolean);
        html += `<div class="hist-ex">
          <span>${{ex.name}}</span>
          <div style="text-align:right">
            <div class="hist-sets">${{setStrs.join(' &nbsp; ')}}</div>
            ${{d.sets.every(s=>s.done) ? '<div class="hist-done" style="font-size:10px;">&#10003; Complete</div>' : ''}}
          </div>
        </div>`;
      }});
      html += '</div>';
    }});
  }}

  if (!any) html += '<div class="empty">No sessions logged yet.<br>Complete your first session to see history here.</div>';
  html += '</div>';
  return html;
}}

// ── Render info / install ─────────────────────────────────────────────────────
function renderInfo() {{
  const week  = currentWeek();
  const block = getBlock(week);
  return `<div class="vtabs">
    <div class="vtab" onclick="view='today';render()">Today</div>
    <div class="vtab" onclick="view='history';render()">History</div>
    <div class="vtab on">Info</div>
  </div>
  <div class="info-page">

    <div class="info-section">
      <h3>How to use this tracker</h3>
      <p>Each exercise shows 3 set rows. Enter the weight you lifted and the number of reps, then tap &#10003; to mark the set done.</p>
      <p>Tap the &#9654; button next to any exercise to open a how-to video in YouTube.</p>
      <p>When you finish all sets, tap <strong>Mark All Done &amp; Save</strong>. Your session is saved to this phone automatically.</p>
      <p>Use the &larr; &rarr; arrows to browse previous weeks. Your logged data stays there.</p>
    </div>

    <div class="info-section">
      <h3>This week &mdash; Week ${{week}}</h3>
      <p><strong style="color:#fff">${{block.sets}} sets &times; ${{block.reps}}</strong></p>
      <p>${{block.note}}</p>
      <p>Progressive overload is the only thing that makes your body change. Each session, try to add one rep or 2.5kg on at least one exercise. Write it down here so you remember next time.</p>
    </div>

    <div class="info-section">
      <h3>When to go heavier</h3>
      <p>If you hit the <em>top</em> of the rep range on all sets (e.g., you got 12 reps when the target is 8&ndash;12), add 2.5kg next session. If you&rsquo;re doing a bodyweight exercise and hit max reps, move to a harder variation.</p>
      <p>The tracker will tell you when this happens &mdash; look for the red arrow on the exercise card.</p>
    </div>

    <div class="info-section">
      <h3>Add to your home screen</h3>
      <div class="install-step">
        <div class="install-num">1</div>
        <div class="install-text"><strong>iPhone / iPad (Safari):</strong> Tap the Share button at the bottom of the screen, then tap <strong>Add to Home Screen</strong>. Tap Add.</div>
      </div>
      <div class="install-step">
        <div class="install-num">2</div>
        <div class="install-text"><strong>Android (Chrome):</strong> Tap the three dots menu in the top right, then <strong>Add to Home Screen</strong> or <strong>Install App</strong>.</div>
      </div>
      <div class="install-step">
        <div class="install-num">3</div>
        <div class="install-text">Once installed, open from your home screen. Your data is saved on this device &mdash; no login needed.</div>
      </div>
      <p style="font-size:11px;color:#444;margin-top:8px;">All your session data is stored locally on your phone. It stays there even when you&rsquo;re offline.</p>
    </div>

    <div class="info-section">
      <h3>Your programme</h3>
      <p><strong style="color:#fff">${{PROGRAMME.label}}</strong> &mdash; ${{PROGRAMME.frequency}}</p>
      <p>Your exercises match your equipment and fitness level. Each week follows a progression block that builds in intensity across the 11 weeks.</p>
    </div>

  </div>`;
}}

// ── Main render ───────────────────────────────────────────────────────────────
function render() {{
  document.getElementById('cname').textContent = CLIENT.name;
  const app = document.getElementById('app');
  if (view === 'history') {{ app.innerHTML = renderHistory(); return; }}
  if (view === 'info')    {{ app.innerHTML = renderInfo();    return; }}
  app.innerHTML = renderToday();
}}

render();
</script>
</body>
</html>"""


def generate_tracker_html(account_no: str, name: str, enrolled_date: str, track: str) -> str:
    prog = PROGRAMMES.get(track, PROGRAMMES["dumbbell_full_body"])
    client_data = {
        "account_no":    account_no,
        "name":          name,
        "enrolled_date": enrolled_date,
        "track":         track,
        "track_label":   prog["label"],
    }
    all_exercises = [ex["name"] for s in prog["sessions"] for ex in s["exercises"]]
    videos = {ex: VIDEO_SEARCHES.get(ex, ex + " exercise tutorial") for ex in all_exercises}

    return _HTML_TEMPLATE.format(
        client_name=name,
        client_json=json.dumps(client_data),
        programme_json=json.dumps(prog),
        videos_json=json.dumps(videos),
    )


def generate_tracker_for_client(cs: dict) -> str:
    return generate_tracker_html(
        account_no=cs.get("account_no", "BSR-0000"),
        name=cs.get("name", "Client"),
        enrolled_date=cs.get("enrolled_date", ""),
        track=cs.get("track", "dumbbell_full_body"),
    )


if __name__ == "__main__":
    html = generate_tracker_html(
        account_no="BSR-2026-0001",
        name="Will",
        enrolled_date="2026-02-15",
        track="gym_intermediate",
    )
    out = Path(__file__).parent.parent / "tracker_test.html"
    out.write_text(html)
    print(f"Generated: {out}")
