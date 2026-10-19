"""Generate WhatsApp/Telegram-ready share text files for every published video.

Local + one read-only API call (channel id). No quota-expensive writes.

Usage:
    python generate_share_kit.py

Writes to H:\\DuaVideoGenerator\\share_kit\\<dua_id>.txt plus INDEX.md.
"""

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
DATA = os.path.join(PROJECT, "data")
UT_PATH = os.path.join(DATA, "upload_state_channel1.json")
SH_PATH = os.path.join(DATA, "shorts_state_channel1.json")
DUAS_PATH = os.path.join(DATA, "duas.json")
TOKEN_PATH = os.path.join(DATA, "yt_token_channel1.json")
CH_INFO = os.path.join(DATA, "channel_info.json")
KIT_DIR = os.path.join(PROJECT, "share_kit")

CHANNEL_HANDLE = "Noor-e-Iman"


def load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        return {}


def get_channel_id():
    cached = load_json(CH_INFO)
    cid = cached.get("id")
    if cid:
        return cid, cached
    sys.path.insert(0, SCRIPTS)
    import youtube_auth

    youtube_auth.set_token_path(os.path.abspath(TOKEN_PATH))
    cred = youtube_auth.get_credentials()
    if not cred:
        return None, None
    from googleapiclient.discovery import build

    yt = build("youtube", "v3", credentials=cred)
    r = yt.channels().list(part="snippet,statistics", mine=True).execute()
    item = (r.get("items") or [{}])[0]
    info = {
        "id": item.get("id"),
        "title": item.get("snippet", {}).get("title"),
        "url": "https://www.youtube.com/channel/{}".format(item.get("id")),
        "subs": item.get("statistics", {}).get("subscriberCount"),
        "videos": item.get("statistics", {}).get("videoCount"),
    }
    tmp = CH_INFO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CH_INFO)
    return info.get("id"), info


def build_text(dua, video_id, is_short, cid, cinfo):
    title = dua.get("title") or "Dua"
    ref = (dua.get("reference") or "").strip()
    arabic = (dua.get("arabic") or "").strip()
    urdu = (dua.get("urdu") or "").strip()
    if is_short:
        watch = "https://youtube.com/shorts/{}".format(video_id)
    else:
        watch = "https://youtu.be/{}".format(video_id)
    sub = "https://www.youtube.com/channel/{}?sub_confirmation=1".format(cid) if cid else ""
    lines = []
    head = title
    if ref:
        head += "  🔖 {}".format(ref)
    lines.append(head)
    lines.append("")
    lines.append("🤲 " + arabic)
    lines.append("")
    lines.append("🕌 ترجمہ: " + urdu)
    lines.append("")
    lines.append("🎬 مکمل دعا/ویدیو دیکھیں: " + watch)
    if sub:
        lines.append("👍 سبسکرائب کریں: " + sub)
    lines.append("")
    lines.append("#Dua #IslamicShorts #Urdu #Islam #Quran #Zikar")
    return "\n".join(lines)


def main():
    os.makedirs(KIT_DIR, exist_ok=True)
    ut = load_json(UT_PATH)
    sh = load_json(SH_PATH)
    duas_raw = load_json(DUAS_PATH)
    duas = duas_raw if isinstance(duas_raw, list) else duas_raw.get("duas", [])
    dmap = {d.get("id"): d for d in duas if d.get("id")}

    cid, cinfo = get_channel_id()
    if not cinfo:
        return {"ok": False, "note": "no channel info"}
    print("channel:", cinfo.get("title"), "| subs:", cinfo.get("subs"), "| videos:", cinfo.get("videos"), flush=True)

    written = 0
    index = []
    ids = set()
    for dua_id, rec in sh.items():
        if rec and rec.get("video_id") and dua_id:
            ids.add((dua_id, "short", rec["video_id"]))
    for dua_id, rec in ut.items():
        if rec and rec.get("status") == "uploaded" and rec.get("video_id") and dua_id:
            ids.add((dua_id, "long", rec["video_id"]))

    for dua_id, kind, video_id in sorted(ids):
        dua = dmap.get(dua_id) or {}
        if not dua:
            dua = {"title": dua_id.replace("_", " ").title()}
        text = build_text(dua, video_id, kind == "short", cid, cinfo)
        with open(os.path.join(KIT_DIR, dua_id + ".txt"), "w", encoding="utf-8") as f:
            f.write(text + "\n")
        if dua_id not in {x[0] for x in index}:
            index.append((dua_id, dua.get("title") or "", kind, video_id, (dua.get("reference") or "")))
        written += 1

    sub = "https://www.youtube.com/channel/{}?sub_confirmation=1".format(cid)
    md = [
        "# Share Kit — %s" % (cinfo.get("title") or "Noor-e-Iman"),
        "",
        "Subs: {} | Videos: {}".format(cinfo.get("subs"), cinfo.get("videos")),
        "Subscribe: {}".format(sub),
        "",
        "| dua_id | title | kind | video_id | reference |",
        "|---|---|---|---|---|",
    ]
    for dua_id, title, kind, video_id, ref in sorted(index):
        md.append("| {} | {} | {} | {} | {} |".format(dua_id, title, kind, video_id, ref))
    with open(os.path.join(KIT_DIR, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    return {"ok": True, "written": written, "channel": cinfo.get("title"), "subs": cinfo.get("subs")}


if __name__ == "__main__":
    r = main()
    print(json.dumps(r, ensure_ascii=False), flush=True)
