# Cafe Daily Instagram Post Generator

## Project Overview
This tool automates daily Instagram caption generation for a cafe. It reads a menu PDF, picks one item per day (rotating through the full menu), generates an engaging Instagram post using the Claude API, and emails it to the cafe owner each morning at 9am for review and manual posting.

## Goals
- Read `menu.pdf` from the project root to extract all menu items
- Rotate through items one per day using a `tracker.json` file (cycle back to start when list is exhausted)
- Generate a warm, engaging Instagram caption with 3–5 relevant hashtags using the Claude API
- Email the generated post to the cafe owner via Gmail (using Gmail SMTP or Gmail API)
- Save each post to a `posts/YYYY-MM-DD.txt` file as a local backup
- Schedule to run automatically at 9am daily via cron (Mac/Linux) or Task Scheduler (Windows)

## Tech Stack
- **Language:** Python 3.10+
- **PDF reading:** `pypdf` library
- **Claude API:** `anthropic` Python SDK, model `claude-sonnet-4-20250514`
- **Email:** Python `smtplib` with Gmail SMTP (or `gmail-api` if preferred)
- **Scheduling:** cron job (Mac/Linux)

## Project File Structure
```
cafe-bot/
├── CLAUDE.md              ← this file
├── menu.pdf               ← cafe menu (provided by owner)
├── tracker.json           ← tracks last used menu item index {"last_index": -1}
├── posts/                 ← saved post backups, one file per day
├── post_generator.py      ← main script
├── requirements.txt       ← Python dependencies
└── .env                   ← API keys and config (never commit this)
```

## Environment Variables (in .env)
```
ANTHROPIC_API_KEY=your_key_here
GMAIL_SENDER=yourcafe@gmail.com
GMAIL_APP_PASSWORD=your_gmail_app_password
OWNER_EMAIL=owner@example.com
CAFE_NAME=Your Cafe Name
```

## How post_generator.py Should Work

1. **Load config** from `.env` using `python-dotenv`
2. **Parse menu.pdf** using `pypdf` — extract all menu items with name, description, and price
3. **Read tracker.json** — get `last_index`, increment by 1, wrap around if at end of list
4. **Pick today's item** from the extracted menu list
5. **Call Claude API** with a prompt to write an Instagram post for that item (see prompt style below)
6. **Save the post** to `posts/YYYY-MM-DD.txt`
7. **Email the post** to the owner via Gmail SMTP with subject: `☕ Today's Instagram Post – [Item Name]`
8. **Update tracker.json** with the new index
9. **Print the post** to terminal as well

## Claude API Prompt Style
The generated caption should:
- Be warm, inviting, and conversational — like a friendly barista talking to regulars
- Highlight what makes the item special (taste, ingredients, mood it creates)
- Be 3–6 sentences long
- End with 3–5 relevant hashtags
- NOT include the price in the post

Example tone: *"Mondays are better with our Cardamom Rose Latte. Delicate floral notes, a hint of spice, and velvety oat milk — it's basically a hug in a cup. Come find us and make your morning a little more special. ☕ #CafeLife #RoseLatte #SpecialtyCoffee #MondayMood"*

## Email Format
- **Subject:** `☕ Today's Instagram Post – [Item Name] | [Date]`
- **Body:** Plain text with the generated caption, followed by a note: *"Review and post to Instagram when ready."*

## Error Handling
- If `menu.pdf` is missing → print clear error and exit
- If Claude API call fails → retry once, then log error and send a fallback email saying generation failed today
- If email fails → still save the post locally and print to terminal

## Setup Instructions to Provide to User
After building the script, give the user:
1. How to install dependencies: `pip install -r requirements.txt`
2. How to set up Gmail App Password (not regular Gmail password)
3. How to add their `.env` file
4. How to test: `python post_generator.py`
5. How to set up the cron job:
   ```
   0 9 * * * cd /path/to/cafe-bot && python post_generator.py
   ```

## Coding Preferences
- Keep code simple and readable — the owner is not a developer
- Add clear comments explaining what each section does
- Use functions with descriptive names
- Print friendly status messages as the script runs so the owner can see what's happening if they run it manually
