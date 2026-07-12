#!/usr/bin/env python3
"""
Cafe Daily Instagram Post Generator
Picks one menu item per day, generates a caption with Claude AI,
generates a set of marketing images with gpt-image-2, zips them up,
emails everything to the cafe owner, and saves local backups.
"""

import base64
import logging
import os
import json
import re
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Optional

import anthropic
import openai as openai_module
from dotenv import load_dotenv
from pypdf import PdfReader

# ── Load config ──────────────────────────────────────────────────────────────

load_dotenv()

ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
RESEND_API_KEY      = os.getenv("RESEND_API_KEY")   # resend.com — for sending emails
OWNER_EMAIL         = os.getenv("OWNER_EMAIL")
CAFE_NAME           = os.getenv("CAFE_NAME", "Our Cafe")
CAFE_LOCATION       = os.getenv("CAFE_LOCATION", "Malviya Nagar, Jaipur")

# Resend requires a verified from address — default is their shared domain for free accounts
RESEND_FROM         = "Chapas Bot <onboarding@resend.dev>"

BASE_DIR      = Path(__file__).parent
MENU_PDF      = BASE_DIR / "menu.pdf"
TRACKER_FILE  = BASE_DIR / "tracker.json"
POSTS_DIR     = BASE_DIR / "posts"
LOGS_DIR      = BASE_DIR / "logs"
GITHUB_STEP_SUMMARY = os.getenv("GITHUB_STEP_SUMMARY")  # set automatically by GitHub Actions

MAX_EMAIL_ATTACHMENT_MB = 24


def setup_logging() -> logging.Logger:
    """Set up logging to both terminal and a daily log file."""
    LOGS_DIR.mkdir(exist_ok=True)
    today_str = date.today().strftime("%Y-%m-%d")
    log_file  = LOGS_DIR / f"{today_str}.log"

    logger = logging.getLogger("cafe_bot")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")

    # File handler — full detail
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler — same detail
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def write_github_summary(item_name: str, caption: str, images_ok: bool, email_ok: bool) -> None:
    """Write a summary card to the GitHub Actions job summary page."""
    if not GITHUB_STEP_SUMMARY:
        return
    with open(GITHUB_STEP_SUMMARY, "a") as f:
        f.write(f"## ☕ Today's Post — {item_name}\n\n")
        f.write(f"```\n{caption}\n```\n\n")
        f.write(f"| Step | Status |\n|---|---|\n")
        f.write(f"| Images generated | {'✅' if images_ok else '⚠️ skipped'} |\n")
        f.write(f"| Email sent | {'✅' if email_ok else '❌ failed'} |\n")

# ── Menu parsing ─────────────────────────────────────────────────────────────

def parse_menu(pdf_path: Path) -> list[str]:
    """Extract all menu item names from the PDF."""
    if not pdf_path.exists():
        print("Error: menu.pdf not found. Please place it in the project folder.")
        raise SystemExit(1)

    print("Reading menu...")
    reader = PdfReader(str(pdf_path))

    price_line = re.compile(r"^(.+?)\s*\.{2,}\s*`\s*\d+\s*$")

    items = []
    for page in reader.pages:
        for line in (page.extract_text() or "").splitlines():
            line = line.strip()
            match = price_line.match(line)
            if match:
                name = match.group(1).strip()
                name = re.sub(r"\bkl\B", "", name).strip()
                if name:
                    items.append(name)

    if not items:
        print("Warning: could not parse items from PDF — using built-in menu list.")
        items = _fallback_menu()

    print(f"Found {len(items)} menu items.")
    return items


def _fallback_menu() -> list[str]:
    """Hardcoded list of all Chapas menu items (used if PDF parsing fails)."""
    return [
        # Chai with milk
        "Kadak Chai", "Adrak Chai", "Sauf Chai", "Dalchini Chai",
        "Assam Chai", "Darjeeling Chai", "Adrak Tulsi Chai", "Adrak Elaichi Chai",
        "Sauf Elaichi Chai", "Gur Wali Chai", "Kulhad Masala Chai", "Chapas Special Chai",
        # Chai without milk
        "Green Chai", "Lemon Chai", "Honey Ginger Chai", "Honey Ginger Lemon Chai",
        # Ice chai
        "Lemon Ice Chai", "Peach Ice Chai", "Strawberry Ice Chai",
        # Coffee
        "Black Coffee", "Hot Coffee", "Hot Coffee with Hazelnut", "Hot Chocolate Coffee",
        # Mojito
        "Mint Mojito", "Green Apple Mojito", "Strawberry Mojito",
        # Cold coffee
        "Cold Coffee", "Cold Coffee with Hazelnut", "Cold Coffee with Chocolate",
        # Lemonada
        "Masala Nimbu Paani", "Fresh Lime Soda", "Masala Lemonada", "Chilli Guava Lemonada",
        # Shakes
        "Chocolate Shake", "Oreo Shake", "Kitkat Shake", "Oreo Kitkat Shake", "Brownie Shake",
        # Breakfast
        "Bun Maska", "Poha", "Vada Pav", "Stuffed Aloo Paratha", "Stuffed Pyaaz Paratha",
        "Masala Omelette", "Chilli Garlic Toast", "Bun Omelette", "Bread Omelette",
        "Stuffed Paneer Paratha", "Crunchy Veg Nuggets", "Veggie Finger",
        # Burgers
        "Classic Veggie Burger", "Spicy Paneer Burger", "Barbeque Burger (Veg)",
        "Barbeque Burger (Paneer)", "Delight Tandoori Burger (Veg)",
        "Delight Tandoori Burger (Paneer)",
        # Pizza
        "Classic Margherita", "American Corn & Cheese Pizza", "Pinoz Onion Pizza",
        "Three Bell Peppers Pizza", "Spicy Mushroom Pizza", "Corn N Mushroom Pizza",
        "Country Veg Pizza", "Peri-Peri Paneer Pizza", "Mushroom N Paneer Pizza",
        "Paneer N Onion Pizza",
        # Fries
        "French Fries", "Peri-Peri Fries", "Barbeque Fries", "Cheesy Fries", "Tandoori Fries",
        # Frankie
        "Veggie Frankie", "Double Egg Frankie", "Paneer Frankie",
        # Pasta
        "Alfredo Pasta", "Arrabiata Pasta", "Mix Sauce Pasta",
        # Maggie
        "Masala Maggie", "Veggie Maggie", "Smoky Barbeque Maggie", "Cheesy Masala Maggie",
        # Sandwich
        "Potato Rosti", "Veggie Sandwich", "American Corn N Cheese Sandwich",
        "Pepper Paneer Sandwich", "Creamy Veg Coleslaw",
        # Chaat
        "Bhel Puri", "American Corn Chaat", "Corn & Peanut Chaat",
        # Dessert
        "Chocolate Brownie",
    ]

# ── Tracker ───────────────────────────────────────────────────────────────────

def pick_todays_item(menu: list[str]) -> tuple[str, int]:
    """Return (item_name, new_index) — advances one step through the menu each day."""
    if TRACKER_FILE.exists():
        data = json.loads(TRACKER_FILE.read_text())
        last_index = data.get("last_index", -1)
    else:
        last_index = -1

    new_index = (last_index + 1) % len(menu)
    return menu[new_index], new_index


def save_tracker(new_index: int) -> None:
    TRACKER_FILE.write_text(json.dumps({"last_index": new_index}, indent=2))

# ── Claude API ────────────────────────────────────────────────────────────────

def generate_caption(item_name: str) -> str:
    """Ask Claude to write an Instagram caption for today's item."""
    print(f"Generating caption for: {item_name}...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = (
        f"You are writing an Instagram caption for {CAFE_NAME}, "
        f"a beloved chai cafe in {CAFE_LOCATION}.\n\n"
        f"Today's featured item: {item_name}\n\n"
        "Write a short, punchy Instagram caption that:\n"
        "- Is exactly 2–3 sentences — crisp, no fluff\n"
        "- Sounds warm and conversational, like a friendly barista\n"
        "- Highlights what makes this item special in one vivid line\n"
        "- Where it genuinely fits, weave in a light touch of CURRENT Indian internet/meme "
        "culture that Instagram audiences here would recognise — a popular desi meme "
        "format, a trending relatable phrase, or Hinglish humor commonly used in Indian "
        "food/cafe social posts (e.g. 'red flag/green flag', 'it's giving...', 'ambani "
        "wedding' style exaggeration, 'ye toh scene hi alag hai', 'main character energy', "
        "office-chai/Monday-mood relatable bits). Keep it natural and tasteful — never "
        "forced, and skip it entirely if no reference fits this item well.\n"
        "- Ends with 3–4 relevant hashtags on a new line (mix trending Indian food/cafe "
        "hashtags with item-specific ones)\n"
        "- Does NOT mention the price\n\n"
        "Write only the caption — nothing else."
    )

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except anthropic.APIError as err:
            if attempt == 0:
                print(f"  API error ({err}), retrying once...")
            else:
                raise RuntimeError(f"Claude API failed after retry: {err}") from err


def generate_image_prompts(item_name: str) -> list[str]:
    """Ask Claude to write 8 DALL-E image prompts for a marketing photo set."""
    print("  Writing image prompts...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = (
        f"You are helping create an 8-image Instagram marketing photo set for "
        f"'{item_name}' from {CAFE_NAME}, a chai cafe in Jaipur, India.\n\n"
        "Write exactly 8 DALL-E image prompts in this order (most dramatic first):\n"
        "1. HERO SHOT — the final item beautifully presented, most mouth-watering angle\n"
        "2. Extreme close-up of the most appetising detail (steam rising, condensation, texture, colour)\n"
        "3. Another tight close-up from a different angle or detail\n"
        "4. Side-profile shot with beautiful bokeh background\n"
        "5. Flat-lay / bird's-eye view of the item\n"
        "6. Action/preparation moment (pouring, stirring, assembling, rolling)\n"
        "7. Key ingredients arranged neatly\n"
        "8. Final beauty shot — slightly different framing from slide 1\n\n"
        "IMPORTANT background rule for ALL prompts: use a plain solid-colour backdrop "
        "(cream, terracotta, sage, dusty rose, navy, warm white) OR a simple textured surface "
        "(rough plaster wall, bare brick, wooden planks, linen cloth). "
        "Do NOT depict a cafe interior, restaurant, or any recognisable room.\n\n"
        "Style for all prompts: warm soft studio lighting, shallow depth of field, "
        "professional food photography, high detail, appetising.\n\n"
        "Return ONLY the 8 prompts, one per line, numbered 1–8. Nothing else."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip the leading "1. ", "2. " etc.
    prompts = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            cleaned = re.sub(r"^\d+\.\s*", "", line)
            prompts.append(cleaned)

    if len(prompts) != 8:
        raise RuntimeError(f"Expected 8 image prompts, got {len(prompts)}")

    return prompts

# ── DALL-E image generation ───────────────────────────────────────────────────

def generate_images(prompts: list[str], tmp_dir: Path) -> list[Path]:
    """Generate 4 images in parallel via gpt-image-1 and save them to tmp_dir."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set — cannot generate images.")

    print(f"  Generating {len(prompts)} images in parallel...")

    def _generate_one(args):
        i, prompt_text = args
        client = openai_module.OpenAI(api_key=OPENAI_API_KEY, timeout=120.0)
        # Retry once on rate limit (429) with a 15s wait
        for attempt in range(2):
            try:
                response = client.images.generate(
                    model="gpt-image-2",
                    prompt=prompt_text,
                    size="1024x1024",
                    quality="low",
                    n=1,
                )
                break
            except openai_module.RateLimitError:
                if attempt == 0:
                    print(f"  Image {i}: rate limited — waiting 15s and retrying...")
                    import time; time.sleep(15)
                else:
                    raise
        img_path = tmp_dir / f"slide_{i}.png"
        img_path.write_bytes(base64.b64decode(response.data[0].b64_json))
        size_kb = img_path.stat().st_size / 1024
        print(f"  Image {i} done. ({size_kb:.0f} KB)")
        return i, img_path

    paths = [None] * len(prompts)
    # Max 5 parallel workers — gpt-image-2 rate limit is 5 images/min
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_generate_one, (i + 1, p)): i for i, p in enumerate(prompts)}
        for future in as_completed(futures):
            i, path = future.result()
            paths[i - 1] = path

    return paths

# ── Zip creation ──────────────────────────────────────────────────────────────

def zip_images(image_paths: list[Path], item_name: str, output_path: Path) -> Path:
    """Zip up the generated images into a single downloadable file."""
    print("Zipping images...")
    safe_name = re.sub(r"[^\w\-]+", "_", item_name).strip("_")
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, img in enumerate(image_paths, 1):
            zf.write(img, arcname=f"{safe_name}_{i}{img.suffix}")
    print(f"  Zip saved: {output_path.name} ({output_path.stat().st_size/1024:.0f} KB)")
    return output_path

# ── Save & email ───────────────────────────────────────────────────────────────

def save_post(item_name: str, caption: str) -> Path:
    """Write the caption to posts/YYYY-MM-DD.txt."""
    POSTS_DIR.mkdir(exist_ok=True)
    today_str = date.today().strftime("%Y-%m-%d")
    filepath = POSTS_DIR / f"{today_str}.txt"
    filepath.write_text(f"Item: {item_name}\nDate: {today_str}\n\n{caption}\n")
    print(f"Caption saved: {filepath.relative_to(BASE_DIR)}")
    return filepath


def send_email(item_name: str, caption: str, zip_path: Optional[Path] = None) -> None:
    """Send the caption + a zip of images to the cafe owner via Resend."""
    if not RESEND_API_KEY or not OWNER_EMAIL:
        print("RESEND_API_KEY or OWNER_EMAIL not set — skipping email.")
        return

    import resend
    resend.api_key = RESEND_API_KEY

    today_str = date.today().strftime("%B %d, %Y")
    subject   = f"Today's Instagram Post – {item_name} | {today_str}"
    body      = f"{caption}\n\n---\nReview and post to Instagram when ready."

    params: resend.Emails.SendParams = {
        "from": RESEND_FROM,
        "to": [OWNER_EMAIL],
        "subject": subject,
        "text": body,
    }

    # Attach the image zip if available and within size limit
    if zip_path and zip_path.exists():
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_EMAIL_ATTACHMENT_MB:
            print(f"Zip too large to attach ({size_mb:.1f}MB) — sending caption only.")
        else:
            params["attachments"] = [{
                "filename": zip_path.name,
                "content": list(zip_path.read_bytes()),
            }]
            print(f"Zip attached: {zip_path.name} ({size_mb:.1f}MB)")

    try:
        resend.Emails.send(params)
        print(f"Email sent to {OWNER_EMAIL}")
    except Exception as err:
        print(f"Email failed: {err}")
        print("(The post was still saved locally — nothing is lost.)")

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log = setup_logging()
    log.info(f"{CAFE_NAME} — Daily Instagram Post Generator starting")

    # 0. Skip if already run today (prevents duplicate posts on manual re-runs)
    today_str = date.today().strftime("%Y-%m-%d")
    if (POSTS_DIR / f"{today_str}.txt").exists():
        log.info(f"Today's post already generated ({today_str}.txt exists). Skipping.")
        return

    # 1. Parse menu
    menu = parse_menu(MENU_PDF)

    # 2. Pick today's item
    item_name, new_index = pick_todays_item(menu)
    log.info(f"Today's item: {item_name}  (#{new_index + 1} of {len(menu)})")

    # 3. Generate caption (with fallback on failure)
    try:
        caption = generate_caption(item_name)
    except RuntimeError as err:
        log.error(f"Caption generation failed: {err}")
        send_email(item_name, f"Could not generate today's caption for: {item_name}\nPlease write the post manually.")
        write_github_summary(item_name, "Caption generation failed.", False, False)
        return

    log.info("Caption generated:\n" + "-" * 40 + f"\n{caption}\n" + "-" * 40)

    # 4. Save caption locally
    save_post(item_name, caption)

    # 5. Generate images (gpt-image-2) and zip them up
    zip_path  = None
    images_ok = False
    if OPENAI_API_KEY:
        try:
            log.info("Generating marketing images...")
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path    = Path(tmp)
                prompts     = generate_image_prompts(item_name)
                image_paths = generate_images(prompts, tmp_path)
                POSTS_DIR.mkdir(exist_ok=True)
                zip_path    = zip_images(image_paths, item_name, POSTS_DIR / f"{today_str}.zip")
                images_ok   = True
                zip_mb      = zip_path.stat().st_size / (1024 * 1024)
                total_images_kb = sum(p.stat().st_size for p in image_paths) / 1024
                log.info(f"Zip saved: {zip_path.name} ({zip_mb:.1f} MB)")
                log.info(f"Images total: {total_images_kb:.0f} KB across {len(image_paths)} images")
        except Exception as err:
            log.error(f"Image generation failed: {err}")
            log.info("Sending email with caption only — images skipped.")
    else:
        log.warning("OPENAI_API_KEY not set — skipping image generation.")

    # 6. Email the owner with the image zip attached
    email_ok = False
    try:
        send_email(item_name, caption, zip_path)
        email_ok = True
    except Exception as err:
        log.error(f"Email failed: {err}")

    # 7. Write GitHub Actions summary
    write_github_summary(item_name, caption, images_ok, email_ok)

    # 8. Advance the tracker so tomorrow picks the next item
    save_tracker(new_index)

    log.info("Done! Have a great day at the cafe. ☕")


if __name__ == "__main__":
    main()
