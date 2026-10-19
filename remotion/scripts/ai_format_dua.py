"""AI Format Dua — paste kiya hua dua text format karke library mein add karta hai.

Usage:
  python scripts/ai_format_dua.py --text "paste text" --category general

Reads API config from data/ai_api_config.json.
Returns JSON: {"ok":true,"added":1,"duas":[{"id":"...","title":"..."}]}
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "remotion", "scripts"))
from ai_import import API_KEYS, FREE_MODELS, _is_empty_block, api_base_url, load_existing, save_duas

SYSTEM_PROMPT = """You are an expert Islamic Sunni scholar. The user will paste a dua in any format (Arabic, Urdu, Roman Urdu, mixed). Your job:

1. Extract and correctly identify: Arabic text, Urdu translation, reference/source, category
2. Generate a short Roman Urdu title (2-5 words)
3. Generate a brief Urdu explanation (1-2 lines about when this dua is read)
4. Create a unique snake_case ID from the title

RULES:
- ONLY authentic Sunni duas
- Arabic MUST be original text with harakat/tashkeel if available
- ARABIC + URDU + ENGLISH all three MUST be present in every dua (arabic, urdu, english, titleEn) - no empty fields
- If user provides incomplete info, fill what you can from Islamic knowledge
- If reference is missing, provide the most authentic known source
- Category must be one of: general, prayer, travel, food, sleep, health, study, safety, parents, ramadan, morning_evening, mosque, work, clothing, weather, protection, rizq, forgiveness, guidance, health, anxiety_relief, gratitude, family, occasions, bathroom, morning, evening

Return ONLY a valid JSON array. No markdown, no code blocks.
[{"id":"unique_snake_case_id","title":"Roman Urdu short title","titleEn":"English title","arabic":"full Arabic text with harakat","urdu":"Urdu translation","english":"English translation of the dua","explanation":"brief Urdu explanation","reference":"Sahih Bukhari 1234","category":"prayer"}]"""


def format_and_add(text, category="general"):
    """Call AI API to format pasted dua text and add to library."""
    if not API_KEYS:
        return {"ok": False, "error": "Koi API key configured nahi hai. Pehle API Settings mein key save karo."}

    user_msg = "Dua text to format:\n\n" + text
    if category:
        user_msg += "\n\nCategory hint: " + category

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    existing = load_existing()
    existing_ids = {d.get("id") for d in existing}

    for m in FREE_MODELS:
        payload = json.dumps(
            {
                "model": m,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2000,
            }
        ).encode("utf-8")

        for api_key in API_KEYS:
            req = urllib.request.Request(
                api_base_url() + "/chat/completions",
                data=payload,
                headers={
                    "Authorization": "Bearer " + api_key,
                    "Content-Type": "application/json",
                    "User-Agent": "DuaStudio/0.11",
                },
            )
            try:
                resp = urllib.request.urlopen(req, timeout=60)
                body = resp.read().decode("utf-8", errors="replace")
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"]
                if _is_empty_block(content):
                    continue
                # Parse JSON
                text_clean = content.strip()
                if text_clean.startswith("```"):
                    text_clean = text_clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                duas = json.loads(text_clean)
                if not isinstance(duas, list):
                    duas = [duas]
                # Ensure unique IDs
                for d in duas:
                    base_id = d.get("id", "")
                    suffix = 2
                    while d.get("id") in existing_ids:
                        d["id"] = base_id + "_v" + str(suffix)
                        suffix += 1
                added = save_duas(duas)
                return {"ok": True, "added": len(added), "duas": [{"id": d["id"], "title": d["title"]} for d in added]}
            except Exception:
                continue
        time.sleep(0.5)

    return {"ok": False, "error": "AI se response nahi aaya. API balance check karo."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--category", default="general")
    args = ap.parse_args()

    result = format_and_add(args.text, args.category)
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
