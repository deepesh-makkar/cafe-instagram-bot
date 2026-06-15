# Adapting This Bot for a Product Business (e.g. Bed Covers & Bedsheets)

This repo was built to auto-generate daily Instagram videos for a **chai cafe**. The
same engine can be repurposed to produce **HD marketing videos for a physical-product
business** — like a bed covers / bedsheet brand.

This guide explains **what changes are required**, **which tools to use for each part**,
and **what to decide before building**.

---

## 1. The Core Engine Is ~80% Reusable

The existing pipeline stays structurally the same:

```
Pick next product (rotation)  →  Claude writes caption
   →  Get images (AI or real photos)
   →  ffmpeg assembles HD video (motion + text + music)
   →  Deliver (email / link)
   →  Run automatically on a schedule (GitHub Actions)
```

What changes is the **input source**, the **content domain (prompts)**, the
**quality settings**, and the **delivery method**.

---

## 2. The One Big Decision: AI Images vs. Real Product Photos

This choice determines the whole build.

| Approach | Good for | Trade-off |
|---|---|---|
| **AI-generated images** (current cafe setup) | Mood / brand-awareness content | Bedsheets shown are **fabricated** — not the real designs you sell. Misleading for product marketing. |
| **Real product photos** ✅ *recommended* | Selling specific, real SKUs | Friend must drop real photos into a folder instead of relying on a PDF. |
| **Hybrid** | Premium look | Real product hero shots + AI-generated lifestyle bedroom backdrops. Most flexible, most work. |

> **For a product business, use real product photos.** Customers expect to see the
> actual bedsheet they can buy. AI-generated patterns won't match the real catalogue.

---

## 3. What Needs to Change (by area)

### 3.1 Input Source
- **Remove:** `menu.pdf` + its food-menu regex parser.
- **Replace with one of:**
  - A `products/` folder of real photos (one subfolder per product), **or**
  - A `products.csv` (columns: `name, description, color, price, photo_folder`).

### 3.2 Content / Prompts (domain swap)
- **Caption voice:** "friendly barista" → premium home-décor brand tone.
- **Image prompts** (only if using AI or hybrid): food-photography script (steam, plating,
  cheese pull) → bedding script (styled bedroom hero, fabric-weave macro, folded stack,
  pattern detail, full lifestyle bedroom).
- **Background rule inverts:** the cafe bot avoided showing interiors. For textiles you
  **want** the product styled on a real bed in a beautiful room.
- **Config rename:** `CAFE_NAME` / `CAFE_LOCATION` → `BRAND_NAME` (location likely irrelevant).

### 3.3 HD Quality (the explicit goal)
Current settings are deliberately **low** for speed/cost. For HD marketing:

| Setting | Current (cafe) | HD target |
|---|---|---|
| Image quality | `quality="low"` | `quality="high"` |
| Resolution | 720×1280 | **1080×1920** |
| ffmpeg preset | `ultrafast` | `medium` / `slow` + higher bitrate |
| Motion | hard cuts | **Ken Burns zoom/pan** (`zoompan` filter) |
| Pacing | fast 1.5s cuts (virality) | slower, elegant (premium feel) |

> The single biggest perceived-quality upgrade is adding **motion** (slow zoom/pan) per
> slide instead of static hard cuts.

### 3.4 Delivery (⚠️ breaks at HD)
A 1080p HD video can exceed the **24MB email attachment limit**. HD likely forces a
**storage + link** approach (see tools below).

### 3.5 Branding for Marketing
The cafe bot only overlaid the item name. Marketing videos want:
- Logo watermark
- Price / offer text
- A closing "Shop Now" CTA slide
- Optional: multiple aspect ratios (9:16 Reels, 1:1 feed, 16:9 web)

---

## 4. Recommended Tools (by capability)

### 🖼️ Images
| Need | Tool | Notes |
|---|---|---|
| AI image generation | **OpenAI `gpt-image-2`** (already wired) | Set `quality="high"`, size `1024x1536` |
| Background removal / clean product cutouts | **Photoroom API** or **remove.bg** | Turn messy product photos into clean cutouts |
| AI lifestyle backdrops (hybrid) | **Photoroom API** / `gpt-image-2` image edit | Place real product into AI-generated bedroom |

### 🎬 Video / Motion
| Need | Tool | Notes |
|---|---|---|
| Slideshow + Ken Burns motion (cheap, reliable) | **ffmpeg `zoompan`** (already installed) | Free, runs in GitHub Actions, good enough for most |
| True AI motion video (premium) | **Runway**, **Kling**, **Luma Dream Machine**, **Pika**, **Sora** | ~$0.05–0.15/sec; cinematic but costs more & slower |

### 🎵 Music
| Tool | Notes |
|---|---|
| **Uppbeat** | Free tier, royalty-free, good for social |
| **Mubert API** | Generates music on demand via API (automatable) |
| **Pixabay Music** | ⚠️ Free API tier did **not** expose music in this project — avoid |
| **Epidemic Sound / Artlist** | Paid, highest quality, best for a real brand |

### ☁️ Storage & Delivery (for HD files)
| Tool | Notes |
|---|---|
| **Cloudinary** ✅ | Built for media, generous free tier, direct video URLs |
| **GitHub Releases** | No new account; upload video as a release asset, email the link |
| **Bunny.net** | Cheap CDN + storage if volume grows |
| **AWS S3 + CloudFront** | Industry standard; overkill for low volume |

### ✍️ Copy / Captions
| Tool | Notes |
|---|---|
| **Anthropic Claude** (already wired) | Caption + image prompts |

### 📧 Email / Notifications
| Tool | Notes |
|---|---|
| **Resend** (already wired) | Verify the recipient address; free tier only sends to verified emails |

### ⏰ Scheduling / Hosting
| Tool | Notes |
|---|---|
| **GitHub Actions** (already wired) | Free cron scheduling; current setup runs daily |

---

## 5. Secrets / Config Needed

Set these as **GitHub repository secrets** (Settings → Secrets and variables → Actions):

```
ANTHROPIC_API_KEY        # Claude — captions & prompts
OPENAI_API_KEY           # gpt-image-2 (only if using AI images)
RESEND_API_KEY           # email delivery
OWNER_EMAIL              # where the daily video is sent
BRAND_NAME               # e.g. "Cosy Home Linens"
CLOUDINARY_URL           # if using Cloudinary for HD delivery
PHOTOROOM_API_KEY        # if using background removal
MUBERT_API_KEY           # if auto-generating music
```

A template lives in `.env.example` — copy it to `.env` for local testing
(never commit `.env`).

---

## 6. Suggested Build Order

1. **Decide:** AI images vs real photos vs hybrid (Section 2).
2. **Swap the input** (PDF parser → product folder/CSV).
3. **Rewrite the prompts** for the bedding domain.
4. **Bump quality to HD** + add `zoompan` motion.
5. **Switch delivery** to Cloudinary/GitHub Releases (HD exceeds email limits).
6. **Add branding** (logo, CTA slide, offer text).
7. **Test** via manual GitHub Actions trigger, then enable the daily schedule.

---

## 7. Cost Notes

- `gpt-image-2` at `quality="high"` is **notably more expensive** per image than the
  cafe's `"low"` setting — budget accordingly if generating 8 images/day.
- True AI motion video (Runway/Kling/etc.) runs ~$0.50–$2.00 per finished clip.
- ffmpeg `zoompan` motion is **free** and is the recommended starting point.
- Cloudinary, GitHub Actions, Resend, Uppbeat all have **free tiers** sufficient for
  one daily video.

---

*This bot's existing code (`post_generator.py`) is the working reference implementation.
Start there and adapt section by section using this guide.*
