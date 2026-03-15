"""
Battleship Reset — Brand Manager Bot
======================================
Manages photos, creates composites, maintains a catalogue of brand assets,
and provides the right image for each content use case.

USAGE:
  python3 skills/brand_manager.py --before-after        # create before/after composite for ads
  python3 skills/brand_manager.py --catalogue           # print full photo catalogue
  python3 skills/brand_manager.py --new-photos          # scan for uncatalogued photos
  python3 skills/brand_manager.py --ad-image <use_case> # get best image for a use case
"""

import json
import shutil
import argparse
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

VAULT_ROOT   = Path("/Users/will/Obsidian-Vaults/BattleShip-Vault")
BRAND_DIR    = VAULT_ROOT / "brand"
OUTPUT_DIR   = VAULT_ROOT / "brand/output"
CATALOGUE_FILE = VAULT_ROOT / "brand/catalogue.json"

# ── Photo catalogue ────────────────────────────────────────────────────────────
# Manually curated — describes each photo for the bot to reason about

KNOWN_PHOTOS = {
    # Getting-fit-random-snaps — face/body progress series
    "Getting-fit-random-snaps/IMG_0291.jpeg": {
        "tags": ["face", "before", "early", "puffy", "indoor", "selfie"],
        "period": "before",
        "quality": "usable",
        "notes": "Early before shot — rounder face, puffier jaw. Rotated sideways.",
        "use_cases": ["before_after"],
    },
    "Getting-fit-random-snaps/IMG_0300.jpeg": {
        "tags": ["face", "before", "early", "puffy", "indoor", "selfie"],
        "period": "before",
        "quality": "good",
        "notes": "Clean before face shot — fuller face, good light. Best 'before' image.",
        "use_cases": ["before_after", "ad"],
    },
    "Getting-fit-random-snaps/IMG_0345.jpeg": {
        "tags": ["face", "after", "lean", "sharp", "indoor", "selfie"],
        "period": "after",
        "quality": "best",
        "notes": "Sharp jaw, lean face, alert eyes. Good light. Best 'after' face shot.",
        "use_cases": ["before_after", "ad", "profile"],
    },
    "Getting-fit-random-snaps/IMG_0411.jpeg": {
        "tags": ["face", "after", "lean", "sharp", "indoor", "portrait"],
        "period": "after",
        "quality": "best",
        "notes": "Best after face shot. Sharp jaw, confident, good light, proper portrait. Will's pick.",
        "use_cases": ["before_after", "ad", "profile"],
    },
    "Getting-fit-random-snaps/IMG_0808.jpeg": {
        "tags": ["face", "after", "lean", "sharp", "indoor", "selfie"],
        "period": "after",
        "quality": "good",
        "notes": "Very lean face, strong jaw definition. Clean background. Good after shot.",
        "use_cases": ["before_after", "ad", "profile"],
    },
    "Getting-fit-random-snaps/IMG_0375.jpeg": {
        "tags": ["body", "mid-progress", "shirtless", "indoor"],
        "period": "mid",
        "quality": "usable",
        "notes": "Body shot mid-progress. Real and unpolished. Rotated sideways.",
        "use_cases": ["progress_post"],
    },
    "Getting-fit-random-snaps/IMG_0818.jpeg": {
        "tags": ["face", "after", "outdoor", "relaxed", "sunglasses"],
        "period": "after",
        "quality": "good",
        "notes": "Outdoors, relaxed, post-transformation. Natural and approachable.",
        "use_cases": ["social_post", "ad"],
    },
    "Getting-fit-random-snaps/IMG_0929.jpeg": {
        "tags": ["lifestyle", "eating", "healthy", "casual", "indoor"],
        "period": "after",
        "quality": "good",
        "notes": "Eating a healthy meal, relaxed. Good for nutrition content.",
        "use_cases": ["nutrition_post", "social_post"],
    },

    # brand/ — main brand photos
    "IMG_0014.jpeg": {
        "tags": ["body", "after", "gym", "mirror", "lean", "strong"],
        "period": "after",
        "quality": "best",
        "notes": "Gym mirror selfie. Best full-body after shot. Clean grey tiles.",
        "use_cases": ["ad", "profile", "before_after", "hero"],
    },
    "IMG_2453.jpeg": {
        "tags": ["face", "after", "outdoor", "field", "sage-top"],
        "period": "after",
        "quality": "best",
        "notes": "Outdoor field photo. Best face photo for marketing. Natural light.",
        "use_cases": ["ad", "profile", "hero", "social_post"],
    },
    "IMG_2887.jpeg": {
        "tags": ["body", "after", "lean", "very-lean"],
        "period": "after",
        "quality": "best",
        "notes": "Very lean body shot. 5mo walking + 4mo gym. Peak result photo.",
        "use_cases": ["before_after", "ad", "hero"],
    },
    "IMG_3366.jpeg": {
        "tags": ["body", "after", "mirror", "bathroom", "abs", "apple-watch"],
        "period": "after",
        "quality": "best",
        "notes": "Bathroom mirror selfie. Best new after shot — frontal, very lean, clean background, Apple Watch visible.",
        "use_cases": ["before_after", "ad", "hero"],
    },
    "IMG_3566.jpeg": {
        "tags": ["body", "after", "full-body", "natural", "bedroom", "not-selfie"],
        "period": "after",
        "quality": "best",
        "notes": "Shot by someone else — not a selfie. Natural, very lean, frontal full-body. Most professional-looking body shot.",
        "use_cases": ["before_after", "ad", "hero", "social_post"],
    },
    "IMG_3575.jpeg": {
        "tags": ["body", "after", "full-body", "bedroom", "standing"],
        "period": "after",
        "quality": "good",
        "notes": "Full body bedroom shot — lean, standing straight. Good scale reference.",
        "use_cases": ["progress_post", "before_after", "social_post"],
    },
    "IMG_3577.jpeg": {
        "tags": ["body", "after", "full-body", "bedroom", "smiling"],
        "period": "after",
        "quality": "good",
        "notes": "Same series as 3575 but smiling — more approachable. Best full-body with personality.",
        "use_cases": ["social_post", "ad", "hero"],
    },
    "IMG_3565.jpeg": {
        "tags": ["body", "mid", "bathroom", "mirror", "progress"],
        "period": "mid",
        "quality": "usable",
        "notes": "Earlier bathroom selfie — visibly heavier than current. Good mid-progress or alternative before shot.",
        "use_cases": ["before_after", "progress_post"],
    },
    "IMG_3372.jpeg": {
        "tags": ["face", "lifestyle", "outdoor", "sunglasses", "airpods", "sunny"],
        "period": "after",
        "quality": "good",
        "notes": "Outdoor selfie, sunglasses + AirPods, blue sky. Relaxed, active lifestyle shot.",
        "use_cases": ["social_post", "lifestyle_post"],
    },
    "IMG_3373.jpeg": {
        "tags": ["face", "lifestyle", "outdoor", "sunglasses", "smiling", "sunny"],
        "period": "after",
        "quality": "good",
        "notes": "Same outdoor session as 3372 but smiling — most approachable lifestyle shot in the library.",
        "use_cases": ["social_post", "lifestyle_post", "ad"],
    },

    # random-snaps/
    "random-snaps/IMG_0448.jpeg": {
        "tags": ["outdoor", "path", "lifestyle", "cliff", "walking"],
        "period": "after",
        "quality": "good",
        "notes": "Cliff path. Used as Facebook cover photo and ad image.",
        "use_cases": ["cover", "ad", "social_post"],
    },
    "random-snaps/IMG_0651.jpeg": {
        "tags": ["equipment", "home-gym", "bench", "dumbbells"],
        "period": "after",
        "quality": "good",
        "notes": "Home gym setup — bench + adjustable dumbbells.",
        "use_cases": ["equipment_post", "social_post"],
    },
    "random-snaps/IMG_1367.jpeg": {
        "tags": ["lifestyle", "camper", "mtb", "outdoors"],
        "period": "after",
        "quality": "good",
        "notes": "Red VW camper + MTB. Lifestyle shot.",
        "use_cases": ["lifestyle_post", "social_post"],
    },
}

# ── Use case → best photo mapping ─────────────────────────────────────────────

USE_CASE_PRIORITY = {
    "ad":             ["IMG_3566.jpeg", "IMG_0014.jpeg", "IMG_2453.jpeg", "Getting-fit-random-snaps/IMG_0808.jpeg"],
    "before_after":   ["before_after_composite"],  # generated
    "profile":        ["IMG_2453.jpeg", "IMG_0014.jpeg", "Getting-fit-random-snaps/IMG_0345.jpeg"],
    "hero":           ["IMG_3566.jpeg", "IMG_2887.jpeg", "IMG_0014.jpeg", "IMG_2453.jpeg"],
    "cover":          ["random-snaps/IMG_0448.jpeg", "IMG_2453.jpeg"],
    "social_post":    ["IMG_3373.jpeg", "IMG_3577.jpeg", "IMG_2453.jpeg", "random-snaps/IMG_1367.jpeg"],
    "lifestyle_post": ["IMG_3372.jpeg", "IMG_3373.jpeg", "random-snaps/IMG_1367.jpeg"],
    "nutrition_post": ["Getting-fit-random-snaps/IMG_0929.jpeg"],
    "equipment_post": ["random-snaps/IMG_0651.jpeg"],
    "progress_post":  ["IMG_3575.jpeg", "IMG_3577.jpeg", "Getting-fit-random-snaps/IMG_0375.jpeg"],
}

# Facebook/Instagram output specs
OUTPUT_SPECS = {
    "fb_feed":      (1200, 630),
    "fb_cover":     (820, 312),
    "fb_profile":   (400, 400),
    "ig_square":    (1080, 1080),
    "ig_portrait":  (1080, 1350),
    "ad_feed":      (1200, 628),
}


# ── Image helpers ─────────────────────────────────────────────────────────────

def _load_image(rel_path: str) -> Image.Image:
    full = BRAND_DIR / rel_path
    img = Image.open(full).convert("RGB")
    # Auto-rotate based on EXIF
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img


def _crop_to_ratio(img: Image.Image, ratio: tuple) -> Image.Image:
    """Centre-crop image to target aspect ratio."""
    tw, th = ratio
    iw, ih = img.size
    target_ratio = tw / th
    current_ratio = iw / ih

    if current_ratio > target_ratio:
        new_w = int(ih * target_ratio)
        left  = (iw - new_w) // 2
        img   = img.crop((left, 0, left + new_w, ih))
    else:
        new_h = int(iw / target_ratio)
        top   = (ih - new_h) // 2
        img   = img.crop((0, top, iw, top + new_h))
    return img


def _resize(img: Image.Image, size: tuple) -> Image.Image:
    return img.resize(size, Image.LANCZOS)


# ── Before/after composite ────────────────────────────────────────────────────

def _crop_aligned(
    img: Image.Image,
    eye_y_frac: float,
    target_w: int,
    target_h: int,
    target_eye_y: float = 0.20,
    zoom: float = 1.0,
) -> Image.Image:
    """
    Crop img to (target_w, target_h) so that the eyes (at eye_y_frac of original
    height) appear at target_eye_y fraction of the output frame.
    zoom < 1 zooms out (shows more body), zoom > 1 zooms in.
    """
    iw, ih = img.size
    # zoom out if requested, but never so far that we can't fill the target width
    scale = max(target_w / iw, target_h / ih) * zoom
    scale = max(scale, target_w / iw)  # always fill width — no black bars
    sw, sh = int(iw * scale), int(ih * scale)
    img = img.resize((sw, sh), Image.LANCZOS)

    eye_px = int(sh * eye_y_frac)
    top    = max(0, min(eye_px - int(target_eye_y * target_h), sh - target_h))
    left   = max(0, (sw - target_w) // 2)
    return img.crop((left, top, left + target_w, top + target_h))


def _draw_headline_overlay(draw: ImageDraw.Draw, text: str, canvas_w: int, canvas_h: int):
    """
    Draw a bold headline across the top of the image.
    Dark semi-transparent bar, white text, centred.
    """
    bar_h = 90
    # Dark bar across full width
    draw.rectangle([(0, 0), (canvas_w, bar_h)], fill=(0, 0, 0, 210))

    # Try fonts in order of preference
    font = None
    for font_path, size in [
        ("/System/Library/Fonts/Helvetica.ttc", 38),
        ("/System/Library/Fonts/Arial Bold.ttf", 38),
        ("/System/Library/Fonts/Helvetica.ttc", 32),
    ]:
        try:
            font = ImageFont.truetype(font_path, size)
            break
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (canvas_w - tw) // 2
    ty = (bar_h - th) // 2

    # Subtle drop shadow
    draw.text((tx + 2, ty + 2), text, fill=(0, 0, 0), font=font)
    draw.text((tx, ty), text, fill=(255, 255, 255), font=font)


def create_before_after(
    before_path: str = "2024-pool-pic.jpg",
    after_path:  str = "IMG_0014.jpeg",
    output_name: str = "before_after_ad.jpg",
    size: tuple  = (1200, 628),
    headline: str | None = None,
) -> Path:
    """
    Create a side-by-side before/after composite optimised for Facebook ads.
    Adds BEFORE / AFTER labels in clean white text.
    If headline is provided, burns it across the top as a scroll-stop hook.

    before_path: pool holiday shot (shock factor)
    after_path:  gym mirror selfie (best full-body result)
    headline:    e.g. "47 years old. No gym. No PT. Just this." or None for plain version
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    before = _load_image(before_path)
    after  = _load_image(after_path)

    half_w = size[0] // 2
    h      = size[1]

    # Eye-aligned crops
    # Before: pool pic — face roughly 35% down, show upper body
    # After: gym mirror full-body — eyes ~18% down, show head→waist→watch (zoom out)
    before_c = _crop_aligned(before, eye_y_frac=0.35, target_w=half_w, target_h=h,
                              target_eye_y=0.22, zoom=1.0)
    after_c  = _crop_aligned(after,  eye_y_frac=0.18, target_w=half_w, target_h=h,
                              target_eye_y=0.12, zoom=0.85)

    # Composite
    canvas = Image.new("RGB", size, (20, 20, 20))
    canvas.paste(before_c, (0, 0))
    canvas.paste(after_c, (half_w, 0))

    # Divider line
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([(half_w - 2, 0), (half_w + 2, h)], fill=(255, 255, 255))

    # Headline overlay (scroll-stop hook)
    if headline:
        _draw_headline_overlay(draw, headline, size[0], h)

    # Labels
    label_h   = 60
    label_pad = 20

    def _draw_label(text, x, y, w):
        draw.rectangle([(x, y), (x + w, y + label_h)], fill=(0, 0, 0, 180))
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]
        tx   = x + (w - tw) // 2
        ty   = y + (label_h - (bbox[3] - bbox[1])) // 2
        draw.text((tx, ty), text, fill=(255, 255, 255), font=font)

    _draw_label("BEFORE", label_pad, h - label_h - label_pad, half_w - label_pad * 2)
    _draw_label("AFTER",  half_w + label_pad, h - label_h - label_pad, half_w - label_pad * 2)

    out_path = OUTPUT_DIR / output_name
    canvas.save(out_path, "JPEG", quality=92)
    print(f"  ✅ Before/after composite saved: {out_path}")
    return out_path


# Hook copy variants — scroll-stop headlines for before/after
HOOK_VARIANTS = [
    # Transformation + age specificity
    "47. No gym membership. Down 2 stone. Here's what actually worked.",
    "I walked my way to abs. At 47. Without a personal trainer.",
    "My GP said 'remarkable'. My waist said -4 inches. My wallet said £199.",
    # Comedy
    "My wife asked if I'd been 'done'. I had. By walking.",
    "This is what happens when a 47-year-old stops making excuses. Apparently.",
    "I didn't know I had abs. Turns out they were just hiding behind the biscuits.",
    # Direct/provocative
    "18 months. Walking. That's the whole programme.",
    "No supplements. No gym. No PT. Just a system that actually makes sense.",
    "What 47 looks like when you stop accepting 'dad bod' as inevitable.",
]


def generate_hooked_variants(secrets: dict | None = None) -> list[Path]:
    """
    Generate before/after composites for each hook variant.
    Returns list of output paths.
    Optionally uses Claude to generate additional AI hooks if secrets provided.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = []

    for i, hook in enumerate(HOOK_VARIANTS):
        fname = f"before_after_hook_{i+1:02d}.jpg"
        path  = create_before_after(output_name=fname, headline=hook)
        paths.append(path)
        print(f"  Hook {i+1}: {hook[:60]}...")

    # AI-generated hooks if API key available
    if secrets and (secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY")):
        ai_hooks = _generate_ai_hooks(secrets)
        for j, hook in enumerate(ai_hooks):
            fname = f"before_after_ai_{j+1:02d}.jpg"
            path  = create_before_after(output_name=fname, headline=hook)
            paths.append(path)

    return paths


def _generate_ai_hooks(secrets: dict) -> list[str]:
    """Use Claude to generate fresh hook variants aligned to current arc phase."""
    try:
        import anthropic
        api_key = secrets.get("ANTHROPIC_API_KEY") or secrets.get("ANTHROPIC_KEY")
        client  = anthropic.Anthropic(api_key=api_key)

        # Pull arc phase for alignment
        arc_context = ""
        try:
            from skills.marketing_bot import get_current_arc_guidance
            arc = get_current_arc_guidance()
            arc_context = f"Current content arc: {arc.get('phase', '')} — {arc.get('theme', '')}"
        except Exception:
            pass

        prompt = f"""You are a direct-response copywriter for a fitness coaching brand.
The founder is Will, 47, UK. Lost 2 stone in 18 months through walking — no gym, no PT, no supplements.
Now has visible abs and a fitness age of 17 (Apple Watch). Sells a 12-week programme for £199.

{arc_context}

Write 3 short headline hooks (max 60 chars each) for a before/after image ad.
Each should stop a 47-year-old man scrolling Facebook dead in his tracks.
Mix styles: 1 specific/credible, 1 slightly comedic, 1 provocative/challenge.
Return only the 3 headlines, one per line. No numbering. No quotes."""

        msg  = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        lines = [l.strip() for l in msg.content[0].text.strip().split("\n") if l.strip()]
        return lines[:3]
    except Exception as e:
        print(f"  ⚠️  AI hook generation failed: {e}")
        return []


# ── Catalogue management ──────────────────────────────────────────────────────

def load_catalogue() -> dict:
    if CATALOGUE_FILE.exists():
        return json.loads(CATALOGUE_FILE.read_text())
    return {}


def save_catalogue(cat: dict):
    CATALOGUE_FILE.write_text(json.dumps(cat, indent=2))


def build_catalogue():
    """Merge KNOWN_PHOTOS with any new files found on disk."""
    cat = load_catalogue()
    for rel, meta in KNOWN_PHOTOS.items():
        if rel not in cat:
            cat[rel] = {**meta, "added": datetime.now().isoformat(), "used_in": []}
    save_catalogue(cat)
    return cat


def scan_new_photos() -> list[str]:
    """Find image files in brand/ not yet in the catalogue."""
    cat    = load_catalogue()
    known  = set(cat.keys())
    found  = []
    for ext in ("*.jpeg", "*.jpg", "*.JPG", "*.JPEG", "*.png"):
        for f in BRAND_DIR.rglob(ext):
            # Skip output folder
            if "output" in f.parts:
                continue
            rel = str(f.relative_to(BRAND_DIR))
            if rel not in known:
                found.append(rel)
    return found


def get_best_image(use_case: str) -> str | None:
    """Return the best available image path for a given use case."""
    cat      = load_catalogue()
    priority = USE_CASE_PRIORITY.get(use_case, [])
    for rel in priority:
        if rel == "before_after_composite":
            out = OUTPUT_DIR / "before_after_ad.jpg"
            if out.exists():
                return str(out)
            # Generate it
            return str(create_before_after())
        if (BRAND_DIR / rel).exists():
            return str(BRAND_DIR / rel)
    # Fallback: any photo with matching use_case tag
    for rel, meta in cat.items():
        if use_case in meta.get("use_cases", []) and (BRAND_DIR / rel).exists():
            return str(BRAND_DIR / rel)
    return None


def mark_used(rel_path: str, context: str):
    """Record that a photo was used in a specific context."""
    cat = load_catalogue()
    if rel_path in cat:
        cat[rel_path].setdefault("used_in", []).append({
            "context": context,
            "date": datetime.now().isoformat(),
        })
        save_catalogue(cat)


def print_catalogue():
    cat = build_catalogue()
    print(f"\n{'='*60}")
    print(f"  Battleship Brand Catalogue — {len(cat)} photos")
    print(f"{'='*60}\n")
    for rel, meta in sorted(cat.items()):
        exists = "✅" if (BRAND_DIR / rel).exists() else "❌"
        quality = meta.get("quality", "unknown")
        period  = meta.get("period", "?")
        uses    = ", ".join(meta.get("use_cases", []))
        print(f"  {exists} {rel}")
        print(f"     [{period}] [{quality}] — {meta.get('notes', '')}")
        print(f"     Use cases: {uses}")
        used = meta.get("used_in", [])
        if used:
            print(f"     Used {len(used)} time(s): {used[-1]['context']} ({used[-1]['date'][:10]})")
        print()


# ── Export resized versions ───────────────────────────────────────────────────

def export_for_platform(rel_path: str, platform: str = "fb_feed") -> Path:
    """Resize and export a photo for a specific platform spec."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    spec = OUTPUT_SPECS.get(platform, (1200, 630))
    img  = _load_image(rel_path)
    img  = _crop_to_ratio(img, spec)
    img  = _resize(img, spec)
    stem = Path(rel_path).stem
    out  = OUTPUT_DIR / f"{stem}_{platform}.jpg"
    img.save(out, "JPEG", quality=92)
    print(f"  ✅ Exported {platform}: {out}")
    return out


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Battleship Brand Manager")
    parser.add_argument("--before-after", action="store_true", help="Create before/after composite")
    parser.add_argument("--hook-variants",action="store_true", help="Create all hooked before/after variants")
    parser.add_argument("--headline",     type=str,            help="Custom headline text to burn onto composite")
    parser.add_argument("--catalogue",    action="store_true", help="Print full photo catalogue")
    parser.add_argument("--new-photos",   action="store_true", help="Scan for uncatalogued photos")
    parser.add_argument("--ad-image",     type=str,            help="Get best image for a use case")
    parser.add_argument("--export",       type=str,            help="Export photo for platform (e.g. fb_feed)")
    parser.add_argument("--photo",        type=str,            help="Photo path (relative to brand/) for --export")
    args = parser.parse_args()

    if args.before_after:
        build_catalogue()
        path = create_before_after(headline=args.headline)
        print(f"\n  Ad-ready composite: {path}")
        print(f"  Upload this to your Facebook ad via the 'Select Media' button.")

    elif args.hook_variants:
        build_catalogue()
        env_file = Path.home() / ".battleship.env"
        secrets: dict = {}
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    secrets[k.strip()] = v.strip()
        paths = generate_hooked_variants(secrets)
        print(f"\n  {len(paths)} hooked variants saved to {OUTPUT_DIR}")
        print("  Open brand/output/ and pick your best scroll-stopper.")

    elif args.catalogue:
        print_catalogue()

    elif args.new_photos:
        build_catalogue()
        new = scan_new_photos()
        if new:
            print(f"\n  {len(new)} uncatalogued photo(s):")
            for f in new:
                print(f"    {f}")
            print("\n  Add them to KNOWN_PHOTOS in brand_manager.py to include in the catalogue.")
        else:
            print("  All photos are catalogued.")

    elif args.ad_image:
        build_catalogue()
        path = get_best_image(args.ad_image)
        print(f"  Best image for '{args.ad_image}': {path}")

    elif args.export and args.photo:
        path = export_for_platform(args.photo, args.export)
        print(f"  Exported: {path}")

    else:
        parser.print_help()
