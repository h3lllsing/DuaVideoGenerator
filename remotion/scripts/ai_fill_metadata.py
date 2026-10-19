"""AI Fill Metadata — existing dua ka missing Arabic/Urdu/Explanation generate karta hai.

Usage:
  python scripts/ai_fill_metadata.py --title "Dua Title" --reference "Sahih Bukhari 123" --category prayer

Reads API config from data/ai_api_config.json (same as ai_import.py).
Returns JSON: {"ok":true,"arabic":"...","urdu":"...","explanation":"..."}
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "remotion", "scripts"))
from ai_import import API_KEYS, FREE_MODELS, _is_empty_block, api_base_url

SYSTEM_PROMPT = """You are an expert Islamic Sunni scholar. The user will give you a dua title, reference, and category.

Generate the COMPLETE metadata for this dua:
1. "arabic": Full authentic Arabic dua text with diacritics (tashkeel). MUST be accurate Quranic/Hadith Arabic.
2. "urdu": Complete respectful Urdu translation of the dua.
3. "explanation": Brief 1-2 line explanation in Urdu about when/why this dua is read. Keep it short.

RULES:
- ONLY authentic Sunni duas from Quran/Hadith
- Arabic MUST be original text, NOT transliteration
- Urdu MUST be accurate and respectful
- If reference is provided, dua MUST match that specific hadith
- NEVER include Shia/Sufi innovations

Return ONLY a valid JSON object. No markdown, no code blocks.
{"arabic":"...","urdu":"...","explanation":"..."}"""


def fill_metadata(title, reference="", category="general"):
    """Call AI API to generate metadata for an existing dua."""
    if not API_KEYS:
        return {"ok": False, "error": "Koi API key configured nahi hai. AI Import modal mein jaake API save karo."}

    user_msg = "Dua: " + title
    if reference:
        user_msg += "\nReference: " + reference
    if category:
        user_msg += "\nCategory: " + category

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    api_url = api_base_url() + "/chat/completions"
    models_to_try = FREE_MODELS

    for m in models_to_try:
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
                api_url,
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
                # Parse JSON from response
                text = content.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                data = json.loads(text)
                if isinstance(data, dict) and ("arabic" in data or "urdu" in data):
                    return {
                        "ok": True,
                        "arabic": data.get("arabic", ""),
                        "urdu": data.get("urdu", ""),
                        "explanation": data.get("explanation", ""),
                    }
            except Exception:
                continue
        time.sleep(0.5)

    return {"ok": False, "error": "AI se response nahi aaya. API balance check karo."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--reference", default="")
    ap.add_argument("--category", default="general")
    args = ap.parse_args()

    result = fill_metadata(args.title, args.reference, args.category)
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
