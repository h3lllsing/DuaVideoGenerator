"""Per-platform caption formatting.

``common.format_caption`` does the limit enforcement; this module decides
*which* text a platform gets. Each platform has different conventions:
TikTok rewards a short hook plus hashtags, Instagram a longer description
with a soft call to action, Facebook the fullest text (63k ceiling).
"""

from __future__ import annotations

import os
import re

from common import CAPTION_LIMITS, SHARE_KIT, load_json, DATA_DIR

# Hashtags are appended, not invented, so the caption always reflects the
# source share_kit file. Keep the block under this many tags for readability.
MAX_TAGS = 12


def _strip_existing_tags(text: str) -> tuple:
    lines = [ln for ln in (text or "").splitlines()]
    body, tags = [], []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") and all(w.startswith("#") for w in stripped.split() if w):
            tags.extend(stripped.split())
        elif stripped:
            body.append(stripped)
    return "\n".join(body).strip(), tags


def _tags_for(dua_id: str) -> list:
    """Derive a small tag set from the catalog entry."""
    path = os.path.join(DATA_DIR, "duas.json")
    try:
        duas = load_json(path, []) or []
    except Exception:
        return ["#dua", "#islamicreminder"]
    entry = next((d for d in duas if isinstance(d, dict) and d.get("id") == dua_id), {})
    tags = ["#dua", "#islamicreminder", "#shorts"]
    title = (entry.get("title") or dua_id).replace("_", " ")
    head = "".join(w[0] for w in title.split()[:3])
    if head:
        tags.append("#" + head.lower())
    reference = (entry.get("reference") or "").strip()
    return tags


def build_caption(dua_id: str, platform: str, text: str = None, include_tags: bool = True) -> str:
    """Return the caption body for one platform, limit-enforced."""
    if text is None:
        from common import load_caption

        text = load_caption(dua_id)
    body, tags = _strip_existing_tags(text)
    if not include_tags:
        return _limit(body, platform)
    merged = []
    for tag in tags + _tags_for(dua_id):
        if tag not in merged and len(merged) < MAX_TAGS:
            merged.append(tag)
    if not merged:
        return _limit(body, platform)
    if platform == "tiktok":
        # TikTok reads short: trim the body hard, then the tag block.
        limit = CAPTION_LIMITS["tiktok"]
        room = limit - sum(len(t) + 1 for t in merged) - 1
        if room < 40:
            merged = merged[:5]
            room = limit - sum(len(t) + 1 for t in merged) - 1
        body = body[: max(room, 0)]
    joined = (body + "\n" if body else "") + " ".join(merged)
    return _limit(joined, platform)


def _limit(text: str, platform: str) -> str:
    limit = CAPTION_LIMITS.get(platform, 2200)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0]


def preview(dua_id: str, platform: str) -> dict:
    """Caption length report for the dashboard / debugging."""
    caption = build_caption(dua_id, platform)
    limit = CAPTION_LIMITS.get(platform, 2200)
    return {
        "dua_id": dua_id,
        "platform": platform,
        "length": len(caption),
        "limit": limit,
        "within_limit": len(caption) <= limit,
        "caption": caption,
    }
