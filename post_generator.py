#!/usr/bin/env python3
"""
Cafe Daily Instagram Post Generator
Picks one menu item per day, generates a caption with Claude AI,
creates a 15-second slideshow video with DALL-E images,
emails everything to the cafe owner, and saves local backups.
"""

import base64
import logging
import os
import json
import re
import shutil
import smtplib
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
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
GMAIL_SENDER        = os.getenv("GMAIL_SENDER")
GMAIL_APP_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD")
OWNER_EMAIL         = os.getenv("OWNER_EMAIL")
CAFE_NAME           = os.getenv("CAFE_NAME", "Our Cafe")

BASE_DIR      = Path(__file__).parent
MENU_PDF      = BASE_DIR / "menu.pdf"
TRACKER_FILE  = BASE_DIR / "tracker.json"
POSTS_DIR     = BASE_DIR / "posts"
LOGS_DIR      = BASE_DIR / "logs"
GITHUB_STEP_SUMMARY = os.getenv("GITHUB_STEP_SUMMARY")  # set automatically by GitHub Actions

MAX_EMAIL_ATTACHMENT_MB = 24  # Gmail rejects over 25MB


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


def write_github_summary(item_name: str, caption: str, video_ok: bool, email_ok: bool) -> None:
    """Write a summary card to the GitHub Actions job summary page."""
    if not GITHUB_STEP_SUMMARY:
        return
    with open(GITHUB_STEP_SUMMARY, "a") as f:
        f.write(f"## ☕ Today's Post — {item_name}\n\n")
        f.write(f"```\n{caption}\n```\n\n")
        f.write(f"| Step | Status |\n|---|---|\n")
        f.write(f"| Video generated | {'✅' if video_ok else '⚠️ skipped'} |\n")
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
        f"a beloved chai cafe in Malviya Nagar, Jaipur.\n\n"
        f"Today's featured item: {item_name}\n\n"
        "Write a warm, inviting Instagram caption that:\n"
        "- Sounds like a friendly barista talking to regulars\n"
        "- Highlights what makes this item special (taste, ingredients, the mood it creates)\n"
        "- Is 3–6 sentences long\n"
        "- Ends with 3–5 relevant hashtags\n"
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
    """Ask Claude to write 4 DALL-E image prompts for the slideshow."""
    print("  Writing image prompts...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = (
        f"You are helping create a 4-slide Instagram Reel for '{item_name}' "
        f"from {CAFE_NAME}, a chai cafe in Jaipur, India.\n\n"
        "Write exactly 4 DALL-E image prompts for these slides:\n"
        "1. Fresh ingredients laid out neatly on a wooden surface\n"
        "2. Key preparation moment (pouring, rolling, stirring, assembling)\n"
        "3. Close-up texture/detail shot (steam, cheese pull, condensation, colour)\n"
        "4. Final dish beautifully plated and served in a warm cafe setting\n\n"
        "Style for all prompts: warm golden-hour lighting, shallow depth of field, "
        "food photography, cozy Indian cafe aesthetic, high detail, appetising.\n\n"
        "Return ONLY the 4 prompts, one per line, numbered 1–4. Nothing else."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
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

    if len(prompts) != 4:
        raise RuntimeError(f"Expected 4 image prompts, got {len(prompts)}")

    return prompts

# ── DALL-E image generation ───────────────────────────────────────────────────

def generate_images(prompts: list[str], tmp_dir: Path) -> list[Path]:
    """Generate 4 images in parallel via gpt-image-1 and save them to tmp_dir."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set — cannot generate images.")

    print(f"  Generating {len(prompts)} images in parallel...")

    def _generate_one(args):
        i, prompt_text = args
        client = openai_module.OpenAI(api_key=OPENAI_API_KEY, timeout=90.0)
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt_text,
            size="1024x1024",
            quality="low",  # faster generation, still looks good for social media
            n=1,
        )
        img_path = tmp_dir / f"slide_{i}.png"
        img_path.write_bytes(base64.b64decode(response.data[0].b64_json))
        print(f"  Image {i} done.")
        return i, img_path

    paths = [None] * len(prompts)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_generate_one, (i + 1, p)): i for i, p in enumerate(prompts)}
        for future in as_completed(futures):
            i, path = future.result()
            paths[i - 1] = path

    return paths

# ── Video creation ────────────────────────────────────────────────────────────

SLIDE_DURATION = 3.75   # seconds per slide  (4 × 3.75 = 15 s total)
FPS            = 25
OUTPUT_SIZE    = "1080x1080"


def _check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def create_video(image_paths: list[Path], cafe_name: str, output_path: Path) -> Path:
    """Stitch 4 images into a 15-sec MP4 slideshow with cafe name on last slide."""
    if not _check_ffmpeg():
        raise RuntimeError(
            "ffmpeg is not installed. Install it with: brew install ffmpeg"
        )

    print("Creating video...")
    tmp_dir = output_path.parent / "_tmp_clips"
    tmp_dir.mkdir(exist_ok=True)

    try:
        # Build one ffmpeg command that takes all 4 images and stitches them
        # Each image shown for SLIDE_DURATION seconds — simple, fast, no CPU-heavy zoom
        inputs = []
        for img in image_paths:
            inputs += ["-loop", "1", "-t", str(SLIDE_DURATION), "-i", str(img)]

        # Scale all inputs to 1080x1080, concatenate, add text on last slide
        text_start = SLIDE_DURATION * 3   # 11.25 s
        # Sanitize cafe name for ffmpeg drawtext — strip chars that break the filter
        safe_name = re.sub(r"[:\\'\[\]{}]", "", cafe_name).strip()

        filter_parts = []
        for i in range(4):
            filter_parts.append(f"[{i}:v]scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,setsar=1[v{i}]")

        filter_parts.append("[v0][v1][v2][v3]concat=n=4:v=1:a=0[base]")
        filter_parts.append(
            f"[base]drawtext=text='{safe_name}':"
            f"fontsize=52:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-120:"
            f"enable='gte(t,{text_start})':"
            f"box=1:boxcolor=black@0.55:boxborderw=12[out]"
        )

        filter_complex = ";".join(filter_parts)

        cmd = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-r", str(FPS),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",  # fastest encoding, fine for daily social posts
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed:\n{result.stderr.decode()}")

        print(f"  Video saved: {output_path.name}")
        return output_path

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# ── Save & email ───────────────────────────────────────────────────────────────

def save_post(item_name: str, caption: str) -> Path:
    """Write the caption to posts/YYYY-MM-DD.txt."""
    POSTS_DIR.mkdir(exist_ok=True)
    today_str = date.today().strftime("%Y-%m-%d")
    filepath = POSTS_DIR / f"{today_str}.txt"
    filepath.write_text(f"Item: {item_name}\nDate: {today_str}\n\n{caption}\n")
    print(f"Caption saved: {filepath.relative_to(BASE_DIR)}")
    return filepath


def send_email(item_name: str, caption: str, video_path: Optional[Path] = None) -> None:
    """Send the caption (and optional video) to the cafe owner via Gmail SMTP."""
    if not all([GMAIL_SENDER, GMAIL_APP_PASSWORD, OWNER_EMAIL]):
        print("Email credentials not set — skipping email. Add them to your .env file.")
        return

    today_str = date.today().strftime("%B %d, %Y")
    subject   = f"☕ Today's Instagram Post – {item_name} | {today_str}"
    body      = f"{caption}\n\n---\nReview and post to Instagram when ready.\n"

    msg = MIMEMultipart()
    msg["From"]    = GMAIL_SENDER
    msg["To"]      = OWNER_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if video_path and video_path.exists():
        size_mb = video_path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_EMAIL_ATTACHMENT_MB:
            print(f"Video too large to attach ({size_mb:.1f}MB > {MAX_EMAIL_ATTACHMENT_MB}MB) — sending caption only.")
        else:
            with open(video_path, "rb") as f:
                part = MIMEBase("video", "mp4")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=video_path.name)
            msg.attach(part)
            print(f"Video attached: {video_path.name} ({size_mb:.1f}MB)")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
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

    # 5. Generate video (DALL-E images → MP4)
    video_path = None
    video_ok   = False
    if OPENAI_API_KEY:
        try:
            log.info("Generating slideshow video...")
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path    = Path(tmp)
                prompts     = generate_image_prompts(item_name)
                image_paths = generate_images(prompts, tmp_path)
                POSTS_DIR.mkdir(exist_ok=True)
                video_path = create_video(image_paths, CAFE_NAME, POSTS_DIR / f"{today_str}.mp4")
                video_ok   = True
                log.info(f"Video saved: {video_path.name}")
        except Exception as err:
            log.error(f"Video generation failed: {err}")
            log.info("Sending email with caption only — video skipped.")
    else:
        log.warning("OPENAI_API_KEY not set — skipping video generation.")

    # 6. Email the owner (with video if available)
    email_ok = False
    try:
        send_email(item_name, caption, video_path)
        email_ok = True
    except Exception as err:
        log.error(f"Email failed: {err}")

    # 7. Write GitHub Actions summary
    write_github_summary(item_name, caption, video_ok, email_ok)

    # 8. Advance the tracker so tomorrow picks the next item
    save_tracker(new_index)

    log.info("Done! Have a great day at the cafe. ☕")


if __name__ == "__main__":
    main()
