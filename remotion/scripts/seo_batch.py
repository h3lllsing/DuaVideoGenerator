"""SEO batch: refresh title/description/tags for every published video.

Applies the same metadata engine as pipeline uploads (metadata.py) to all
videos already live (longs from upload_state + shorts from shorts_state).

Usage:
    python seo_batch.py --dry-run
    python seo_batch.py
    python seo_batch.py --only dua1,dua2

Write op: videos().update(part=snippet) = 50 quota units each.
"""

import argparse
import contextlib
import json
import os
import sys
import time

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
DATA = os.path.join(PROJECT, "data")
UT_PATH = os.path.join(DATA, "upload_state_channel1.json")
SH_PATH = os.path.join(DATA, "shorts_state_channel1.json")
DUAS_PATH = os.path.join(DATA, "duas.json")
TOKEN_PATH = os.path.join(DATA, "yt_token_channel1.json")

CATEGORY_ID = "22"


def load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        return {}


def get_service():
    import youtube_auth

    youtube_auth.set_token_path(os.path.abspath(TOKEN_PATH))
    cred = youtube_auth.get_credentials()
    if not cred:
        return None
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=cred)


def build_meta(dua, rot, is_short):
    from metadata import build_description, build_tags

    title = dua.get("title") or "Dua"
    ref = (dua.get("reference") or "").strip()
    full_title = f"{title} | {ref}" if ref else title
    tags = build_tags(dua, rot)
    desc = build_description(dua, rot, {})
    if is_short:
        if "shorts" not in tags:
            tags.insert(0, "shorts")
        if "#Shorts" not in desc:
            desc = desc.rstrip() + "\n#Shorts\n"
    return {"title": full_title[:100], "description": desc, "tags": tags}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    ut = load_json(UT_PATH)
    sh = load_json(SH_PATH)
    duas_raw = load_json(DUAS_PATH)
    duas = duas_raw if isinstance(duas_raw, list) else duas_raw.get("duas", [])
    dmap = {d.get("id"): d for d in duas if d.get("id")}

    targets = {}
    for dua_id, rec in ut.items():
        if rec and rec.get("status") == "uploaded" and rec.get("video_id") and dua_id and rec.get("via") != "short":
            targets[dua_id] = {"video_id": rec["video_id"], "kind": "long"}
    for dua_id, rec in sh.items():
        if rec and rec.get("video_id") and dua_id:
            targets[dua_id] = {"video_id": rec["video_id"], "kind": "short"}

    if args.only:
        sel = set(args.only.split(","))
        targets = {k: v for k, v in targets.items() if k in sel}

    plan = []
    for dua_id in sorted(targets):
        t = targets[dua_id]
        dua = dmap.get(dua_id) or {}
        if not dua:
            dua = {"title": dua_id.replace("_", " ").title()}
        from metadata import Rot

        meta = build_meta(dua, Rot(dua_id), t["kind"] == "short")
        plan.append({"dua_id": dua_id, "video_id": t["video_id"], "kind": t["kind"], "meta": meta})
    print(f"seo targets: {len(plan)}", flush=True)
    if args.dry_run:
        print(
            json.dumps(
                {"ok": True, "dryRun": True, "pending": len(plan), "ids": [p["dua_id"] for p in plan]},
                ensure_ascii=False,
            )
        )
        return 0

    yt = get_service()
    if not yt:
        print(json.dumps({"ok": False, "error": "auth"}))
        return 1

    done, failed = [], []
    for p in plan:
        try:
            body = {
                "id": p["video_id"],
                "snippet": {
                    "title": p["meta"]["title"],
                    "description": p["meta"]["description"],
                    "tags": p["meta"]["tags"],
                    "categoryId": CATEGORY_ID,
                    "defaultLanguage": "en",
                },
            }
            yt.videos().update(part="snippet", body=body).execute()
            done.append(p["dua_id"])
        except Exception as e:
            failed.append({"dua_id": p["dua_id"], "video_id": p["video_id"], "error": str(e)[-160:]})
        time.sleep(0.4)
    print(json.dumps({"ok": True, "updated": len(done), "failed": len(failed), "errors": failed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
