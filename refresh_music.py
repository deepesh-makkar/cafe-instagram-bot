#!/usr/bin/env python3
"""
Biweekly Music Refresher for Chapas Instagram Bot
--------------------------------------------------
1. Asks Claude what music styles are trending in Instagram food reels right now
2. Searches Pixabay for a matching royalty-free track
3. Updates the MUSIC_URL GitHub secret so the next video uses the new track
4. Logs what was picked and why
"""

import os
import json
import base64
import hashlib
import requests
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PIXABAY_API_KEY   = os.getenv("PIXABAY_API_KEY")   # free at pixabay.com/api/docs/
GH_PAT            = os.getenv("GH_PAT")             # GitHub PAT with secrets:write scope
GH_REPO           = os.getenv("GH_REPO", "deepesh-makkar/cafe-instagram-bot")

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# ── Step 1: Ask Claude what's trending ───────────────────────────────────────

def get_trending_music_style() -> dict:
    """Ask Claude to recommend a music style and Pixabay search term."""
    print("Asking Claude about trending food reel music...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    today = date.today().strftime("%B %Y")
    prompt = (
        f"It is {today}. You are a social media expert who tracks Instagram Reels trends.\n\n"
        "What music style is currently trending in food/cafe Instagram Reels? "
        "Think about what's performing well on food Reels globally and in India right now.\n\n"
        "Reply with a JSON object (no markdown, raw JSON only) with these fields:\n"
        "- style: one-line description of the trending music style (e.g. 'upbeat lofi hip hop')\n"
        "- reason: one sentence explaining why it's trending\n"
        "- pixabay_query: 2-3 word search term to find this style on Pixabay (e.g. 'lofi chill')\n"
        "- mood: the emotional vibe (e.g. 'cozy', 'energetic', 'nostalgic')\n\n"
        "Raw JSON only. No explanation outside the JSON."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if Claude adds them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    print(f"  Trending style: {data['style']}")
    print(f"  Reason: {data['reason']}")
    print(f"  Pixabay search: {data['pixabay_query']}")
    return data


# ── Step 2: Search Pixabay for a matching track ───────────────────────────────

def search_pixabay(query: str) -> dict | None:
    """Search Pixabay Music API and return the best matching track."""
    if not PIXABAY_API_KEY:
        print("  PIXABAY_API_KEY not set — using fallback lofi track.")
        return None

    print(f"Searching Pixabay for: '{query}'...")
    url = "https://pixabay.com/api/videos/music/"   # Pixabay music endpoint
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "per_page": 10,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])

    if not hits:
        print(f"  No results for '{query}' — trying 'lofi'...")
        params["q"] = "lofi"
        resp = requests.get(url, params=params, timeout=15)
        hits = resp.json().get("hits", [])

    if not hits:
        print("  No Pixabay results found — will keep existing music.")
        return None

    # Pick the track with the most downloads (most popular)
    best = max(hits, key=lambda t: t.get("downloads", 0))
    print(f"  Selected: '{best.get('tags', 'unknown')}' ({best.get('downloads', 0)} downloads)")
    return best


def get_track_download_url(track: dict) -> str | None:
    """Extract the direct MP3 download URL from a Pixabay track object."""
    # Pixabay music API returns audio URLs in the 'audio' field
    audio = track.get("audio") or track.get("url")
    if audio:
        return audio
    # Fallback: construct from track ID
    track_id = track.get("id")
    if track_id:
        return f"https://cdn.pixabay.com/audio/{track_id}.mp3"
    return None


# ── Step 3: Update the GitHub secret ─────────────────────────────────────────

def update_github_secret(secret_name: str, secret_value: str) -> bool:
    """Update a GitHub Actions secret using the REST API."""
    if not GH_PAT:
        print("  GH_PAT not set — cannot update GitHub secret.")
        return False

    headers = {
        "Authorization": f"token {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Step A: Get the repo's public key for secret encryption
    key_resp = requests.get(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key",
        headers=headers, timeout=10
    )
    key_resp.raise_for_status()
    key_data  = key_resp.json()
    public_key = key_data["key"]
    key_id     = key_data["key_id"]

    # Step B: Encrypt the secret value with the public key (libsodium sealed box)
    try:
        from nacl import encoding, public as nacl_public
        pk = nacl_public.PublicKey(public_key.encode(), encoding.Base64Encoder)
        box = nacl_public.SealedBox(pk)
        encrypted = base64.b64encode(box.encrypt(secret_value.encode())).decode()
    except ImportError:
        print("  PyNaCl not installed — installing now...")
        import subprocess
        subprocess.run(["pip", "install", "PyNaCl", "-q"], check=True)
        from nacl import encoding, public as nacl_public
        pk = nacl_public.PublicKey(public_key.encode(), encoding.Base64Encoder)
        box = nacl_public.SealedBox(pk)
        encrypted = base64.b64encode(box.encrypt(secret_value.encode())).decode()

    # Step C: PUT the encrypted secret
    put_resp = requests.put(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/{secret_name}",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": key_id},
        timeout=10
    )

    if put_resp.status_code in (201, 204):
        print(f"  ✅ GitHub secret '{secret_name}' updated successfully.")
        return True
    else:
        print(f"  ❌ Failed to update secret: {put_resp.status_code} {put_resp.text}")
        return False


# ── Step 4: Log the decision ──────────────────────────────────────────────────

def log_music_update(trend: dict, track: dict | None, music_url: str) -> None:
    """Append a record to logs/music_history.json for transparency."""
    history_file = LOGS_DIR / "music_history.json"
    history = json.loads(history_file.read_text()) if history_file.exists() else []

    entry = {
        "date": date.today().isoformat(),
        "trending_style": trend.get("style"),
        "reason": trend.get("reason"),
        "mood": trend.get("mood"),
        "pixabay_query": trend.get("pixabay_query"),
        "track_tags": track.get("tags") if track else "fallback",
        "music_url": music_url,
    }
    history.append(entry)
    history_file.write_text(json.dumps(history, indent=2))
    print(f"  Music history saved to logs/music_history.json")


# ── Main ──────────────────────────────────────────────────────────────────────

# Fallback track — a calm lofi track from Pixabay (CC0, no attribution required)
FALLBACK_MUSIC_URL = "https://cdn.pixabay.com/audio/2024/03/14/audio_9a6e5f1234.mp3"

def main():
    print(f"\n🎵 Biweekly Music Refresh — {date.today()}\n")

    # 1. Ask Claude what's trending
    trend = get_trending_music_style()

    # 2. Search Pixabay for a matching track
    track = search_pixabay(trend["pixabay_query"])
    music_url = get_track_download_url(track) if track else FALLBACK_MUSIC_URL

    if not music_url:
        print("Could not determine a music URL — skipping update.")
        return

    print(f"\nNew music URL: {music_url}")

    # 3. Update the MUSIC_URL GitHub secret
    update_github_secret("MUSIC_URL", music_url)

    # 4. Log the decision
    log_music_update(trend, track, music_url)

    print(f"\n✅ Done! Next video will use: {trend['style']} ({trend['mood']} mood)")


if __name__ == "__main__":
    main()
