"""Build local playlist grouping plan (creation/inserts happen post-quota).

Local only. Writes data/playlist_plan_channel1.json.
"""

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
DATA = os.path.join(PROJECT, "data")
with open(os.path.join(DATA, "upload_state_channel1.json"), encoding="utf-8-sig") as fh:
    ut = json.load(fh)
with open(os.path.join(DATA, "shorts_state_channel1.json"), encoding="utf-8-sig") as fh:
    sh = json.load(fh)
with open(os.path.join(DATA, "duas.json"), encoding="utf-8-sig") as fh:
    duas_raw = json.load(fh)
duas = duas_raw if isinstance(duas_raw, list) else duas_raw.get("duas", [])
dmap = {d.get("id"): d for d in duas if d.get("id")}

ids = {}
for dua_id, rec in ut.items():
    if rec and rec.get("video_id") and dua_id:
        ids[dua_id] = rec["video_id"]
for dua_id, rec in sh.items():
    if rec and rec.get("video_id") and dua_id:
        ids[dua_id] = ids.get(dua_id) or rec["video_id"]

PLAYLISTS = [
    (
        "nafs",
        "Maut Aur Qabr Ki Fikr",
        ["maut", "qabr", "qabristan", "akhirat", "aakhri", "kalma", "ruswai", "jahannam", "hashr", "hisab"],
    ),
    (
        "khof",
        "Khof Aur Hifazat",
        ["khof", "hifazat", "panah", "dushman", "khatra", "bala", "nazar", "toofan", "neki", "burai", "sharr"],
    ),
    (
        "rizq",
        "Rizq Aur Barkat",
        ["rizq", "barkat", "karobar", "tijarat", "kamai", "halal", "faqr", "ghurbat", "qarz", "tangdasti", "hamdardi"],
    ),
    (
        "ilm",
        "Ilm Aur Hidayat",
        ["ilm", "hidayat", "zikr", "nafe", "samajh", "fahm", "siraat", "rasta", "siddha", "talab", "kushadgi", "aqal"],
    ),
    (
        "sabr",
        "Sabr Aur Shifa",
        ["sabr", "shifa", "sehat", "sehat", "jism", "dard", "sukoon", "dil", "gussa", "tangdasti", "bemari"],
    ),
    ("family", "Ghar Aur Riste", ["aulad", "jivan", "sathi", "shadi", "dulha", "ghar", "rishte", "joru", "pasand"]),
    (
        "raat",
        "Rojana Masnoon Duaein",
        ["sone", "roza", "kholne", "masjid", "azan", "kutte", "murgh", "khana", "kapre", "bazar"],
    ),
    (
        "mausam",
        "Mausam Aur Pani",
        ["barish", "badal", "chand", "garaj", "hawa", "toofan", "samandar", "samundari", "gharq", "taharat", "nafi"],
    ),
]

matched, used = {}, set()
plan = []
for key, title, kws in PLAYLISTS:
    members = []
    for dua_id, vid in sorted(ids.items()):
        if dua_id in used:
            continue
        d = dmap.get(dua_id) or {}
        hay = (dua_id + " " + (d.get("title") or "")).lower()
        if any(k in hay for k in kws):
            members.append({"dua_id": dua_id, "video_id": vid, "title": (d.get("title") or dua_id)})
            used.add(dua_id)
    if members:
        plan.append({"key": key, "title": title, "members": members})

leftover = [did for did in ids if did not in used]
extra = []
for dua_id in sorted(leftover):
    d = dmap.get(dua_id) or {}
    extra.append(
        {
            "dua_id": dua_id,
            "video_id": ids[dua_id],
            "title": (d.get("title") or dua_id),
            "category": d.get("category") or "",
        }
    )
if extra:
    plan.append({"key": "other", "title": "Baaki Duaein", "members": extra})

out = {
    "channel": "Noor-e-Iman",
    "playlists": plan,
    "total_videos": len(ids),
    "total_in_playlists": sum(len(p["members"]) for p in plan),
}
tmp = os.path.join(DATA, "playlist_plan_channel1.json") + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
os.replace(tmp, os.path.join(DATA, "playlist_plan_channel1.json"))
print(
    json.dumps(
        {"ok": True, "total_videos": len(ids), "playlists": [(p["key"], p["title"], len(p["members"])) for p in plan]},
        ensure_ascii=False,
    )
)
