#!/usr/bin/env python3
"""
Cafe Daily Instagram Post Generator
Picks one menu item per day, generates a caption with Claude AI,
emails it to the cafe owner, and saves it as a local backup.
"""

import os
import json
import re
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pypdf import PdfReader

# ── Load config ──────────────────────────────────────────────────────────────

load_dotenv()

ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
GMAIL_SENDER        = os.getenv("GMAIL_SENDER")
GMAIL_APP_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD")
OWNER_EMAIL         = os.getenv("OWNER_EMAIL")
CAFE_NAME           = os.getenv("CAFE_NAME", "Our Cafe")

BASE_DIR      = Path(__file__).parent
MENU_PDF      = BASE_DIR / "menu.pdf"
TRACKER_FILE  = BASE_DIR / "tracker.json"
POSTS_DIR     = BASE_DIR / "posts"

# ── Menu parsing ─────────────────────────────────────────────────────────────

def parse_menu(pdf_path: Path) -> list[str]:
    """Extract all menu item names from the PDF."""
    if not pdf_path.exists():
        print("Error: menu.pdf not found. Please place it in the project folder.")
        raise SystemExit(1)

    print("Reading menu...")
    reader = PdfReader(str(pdf_path))

    # Each menu line looks like:  Item Name ........... ` 99
    price_line = re.compile(r"^(.+?)\s*\.{2,}\s*`\s*\d+\s*$")

    items = []
    for page in reader.pages:
        for line in (page.extract_text() or "").splitlines():
            line = line.strip()
            match = price_line.match(line)
            if match:
                name = match.group(1).strip()
                # Fix OCR glitch on "Masala klOmelette"
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

# ── Save & email ───────────────────────────────────────────────────────────────

def save_post(item_name: str, caption: str) -> Path:
    """Write the caption to posts/YYYY-MM-DD.txt."""
    POSTS_DIR.mkdir(exist_ok=True)
    today_str = date.today().strftime("%Y-%m-%d")
    filepath = POSTS_DIR / f"{today_str}.txt"
    filepath.write_text(f"Item: {item_name}\nDate: {today_str}\n\n{caption}\n")
    print(f"Saved to: {filepath.relative_to(BASE_DIR)}")
    return filepath


def send_email(item_name: str, caption: str) -> None:
    """Send the caption to the cafe owner via Gmail SMTP."""
    if not all([GMAIL_SENDER, GMAIL_APP_PASSWORD, OWNER_EMAIL]):
        print("Email credentials not set — skipping email. Add them to your .env file.")
        return

    today_str = date.today().strftime("%B %d, %Y")
    subject = f"☕ Today's Instagram Post – {item_name} | {today_str}"
    body = f"{caption}\n\n---\nReview and post to Instagram when ready.\n"

    msg = MIMEMultipart()
    msg["From"] = GMAIL_SENDER
    msg["To"] = OWNER_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

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
    print(f"\n{CAFE_NAME} — Daily Instagram Post Generator")
    print("=" * 52)

    # 1. Parse menu
    menu = parse_menu(MENU_PDF)

    # 2. Pick today's item
    item_name, new_index = pick_todays_item(menu)
    print(f"Today's item: {item_name}  (#{new_index + 1} of {len(menu)})")

    # 3. Generate caption (with fallback on failure)
    try:
        caption = generate_caption(item_name)
    except RuntimeError as err:
        print(f"Caption generation failed: {err}")
        fallback_body = (
            f"Could not generate today's caption for: {item_name}\n"
            "Please write the post manually."
        )
        send_email(item_name, fallback_body)
        return

    # 4. Print the post
    print("\n" + "-" * 52)
    print("TODAY'S INSTAGRAM POST")
    print("-" * 52)
    print(caption)
    print("-" * 52)

    # 5. Save locally
    save_post(item_name, caption)

    # 6. Email the owner
    send_email(item_name, caption)

    # 7. Advance the tracker so tomorrow picks the next item
    save_tracker(new_index)

    print("\nDone! Have a great day at the cafe. ☕")


if __name__ == "__main__":
    main()
