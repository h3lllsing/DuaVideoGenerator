"""YouTube-ready <Title>.txt sidecar generator (v2 - Pillar 4).

Usage: python scripts/metadata.py <dua_id>

Diversity strategy (anti-repetitive-content):
- Tag pools per category mixing English + Roman Urdu + Urdu script,
  plus content-derived tags from title/reference words.
- Description blocks (opener / reference box / CTA / footer) rotate
  deterministically per dua_id (stable across regeneration runs).
- Hashtags selected from rotating pool, never a fixed constant string.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import sys

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG_PATH = os.path.join(PROJECT, "remotion", "dashboard", "config.json")

MAX_TITLE = 95
MAX_DESC = 4500
MAX_TAGS_LINE = 480

DISCLAIMER = (
    "\n\n--- Disclaimer ---\nEducational & Islamic Dua reference. Sources cited from authentic Hadith/Quranic texts."
)


def safe_title(title):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", title or "Dua").strip()
    return re.sub(r"[. ]+$", "", s) or "Dua"


def clean(s):
    """Drop lone surrogates / invalid code points from DB text."""
    return (s or "").encode("utf-8", "ignore").decode("utf-8", "ignore").strip()


class Rot:
    """Deterministic per-dua rotation (stable output across reruns)."""

    def __init__(self, dua_id):
        digest = hashlib.sha1(dua_id.encode("utf-8")).digest()
        self.bytes = digest

    def pick(self, seq, salt=0):
        return seq[self.bytes[salt % len(self.bytes)] % len(seq)]

    def idx(self, n, salt=0):
        return self.bytes[(salt * 7 + 3) % len(self.bytes)] % n


BASE_TAGS_EN = [
    "islamic dua",
    "daily dua shorts",
    "muslim prayer",
    "sunnah reminder",
    "authentic hadith dua",
    "quran wa hadith",
]
URDU_GENERIC_TAGS = [
    "\u0627\u0633\u0644\u0627\u0645\u06cc \u062f\u0639\u0627",
    "\u0645\u0633\u0644\u0645\u0627\u0646 \u062f\u0639\u0627\u0626\u06cc\u06ba",
    "\u0631\u0648\u062d\u0627\u0646\u06cc \u0633\u06a9\u0648\u0646",
    "\u062f\u0639\u0627 \u0627\u0648\u0631 \u0630\u06a9\u0631",
]

CATEGORY_SEO = {
    "morning": {
        "en": ["morning dua", "subah ki dua", "morning azkar"],
        "roman": ["subah ki dua", "sunnah morning routine"],
        "ur": ["\u0635\u0628\u062d \u06a9\u06cc \u062f\u0639\u0627"],
        "hash": "#MorningDua",
    },
    "evening": {
        "en": ["evening dua", "shaam ki dua"],
        "roman": ["shaam ki dua", "evening azkar"],
        "ur": ["\u0634\u0627\u0645 \u06a9\u06cc \u062f\u0639\u0627"],
        "hash": "#EveningDua",
    },
    "sleep": {
        "en": ["sleep dua", "bedtime sunnah"],
        "roman": ["sone ki dua", "raat ki dua"],
        "ur": ["\u0633\u0648\u0646\u06d2 \u06a9\u06cc \u062f\u0639\u0627"],
        "hash": "#SleepDua",
    },
    "food": {
        "en": ["food dua", "eating sunnah"],
        "roman": ["khane ki dua", "bismillah se khana"],
        "ur": ["\u06a9\u06be\u0627\u0646\u06d2 \u06a9\u06cc \u062f\u0639\u0627"],
        "hash": "#FoodDua",
    },
    "travel": {
        "en": ["travel dua", "journey prayer", "safar ki dua"],
        "roman": ["safar ki dua", "travel sunnah"],
        "ur": ["\u0633\u0641\u0631 \u06a9\u06cc \u062f\u0639\u0627"],
        "hash": "#TravelDua",
    },
    "bathroom": {
        "en": ["bathroom exit dua", "islamic etiquette"],
        "roman": ["bathroom ki dua", "washroom dua"],
        "ur": ["\u0628\u0627\u062a\u200c\u0631\u0648\u0645 \u06a9\u06cc \u062f\u0639\u0627"],
        "hash": "#SunnahDua",
    },
    "prayer": {
        "en": ["salah dua", "namaz dua", "after prayer dhikr"],
        "roman": ["namaz ke baad ki dua", "salah ke baad azkar"],
        "ur": [
            "\u0646\u0645\u0627\u0632 \u06a9\u06cc \u062f\u0639\u0627",
            "\u062f\u0639\u0627 \u0645\u0633\u062c\u0648\u062f",
        ],
        "hash": "#SalahDua",
    },
    "protection": {
        "en": ["protection dua", "hifazat ki dua", "refuge prayer"],
        "roman": ["hifazat ki dua", "shar se hifazat"],
        "ur": [
            "\u062d\u0641\u0627\u0638\u062a \u06a9\u06cc \u062f\u0639\u0627",
            "\u062f\u0639\u0627\u0621\u0650 \u062d\u0641\u0627\u0638\u062a",
        ],
        "hash": "#Hifazat",
    },
    "forgiveness": {
        "en": ["istighfar", "forgiveness dua", "tawbah prayer"],
        "roman": ["dua e maghfirat", "istighfar ki dua", "tawbah ki dua"],
        "ur": [
            "\u062f\u0639\u0627\u0621\u0650 \u0645\u063a\u0641\u0631\u062a",
            "\u0627\u0633\u062a\u063a\u0641\u0627\u0631",
        ],
        "hash": "#Istighfar",
    },
    "guidance": {
        "en": ["guidance dua", "hidayat prayer"],
        "roman": ["hidayat ki dua", "raste ki dua"],
        "ur": ["\u062f\u0639\u0627\u0621\u0650 \u06c1\u062f\u0627\u06cc\u062a"],
        "hash": "#Guidance",
    },
    "health": {
        "en": ["shifa dua", "healing prayer", "sickness dua"],
        "roman": ["sehat ki dua", "shifa ki dua", "bimari ki dua"],
        "ur": ["\u062f\u0639\u0627\u0621\u0650 \u0634\u0641\u0627"],
        "hash": "#ShifaDua",
    },
    "anxiety_relief": {
        "en": ["anxiety relief dua", "stress relief prayer", "gham ki dua"],
        "roman": ["pareshani ki dua", "gham se nijat ki dua"],
        "ur": ["\u062f\u0639\u0627\u0621\u0650 \u0631\u0641\u0639 \u06c1\u0645"],
        "hash": "#AnxietyRelief",
    },
    "rizq": {
        "en": ["rizq dua", "abundance prayer", "sustenance dua"],
        "roman": ["rizq mein barkat ki dua", "rizq ki dua"],
        "ur": ["\u062f\u0639\u0627\u0621\u0650 \u0631\u0632\u0642"],
        "hash": "#RizqDua",
    },
    "family": {
        "en": ["family dua", "parents dua", "children prayer"],
        "roman": ["maa baap ki dua", "aulad ki dua"],
        "ur": [
            "\u062f\u0639\u0627\u0621\u0650 \u0627\u0648\u0644\u0627\u062f",
            "\u0645\u0627\u06ba \u0628\u0627\u067e \u06a9\u06d2 \u0644\u06cc\u06d2 \u062f\u0639\u0627",
        ],
        "hash": "#FamilyDua",
    },
    "gratitude": {
        "en": ["gratitude dhikr", "shukar dua"],
        "roman": ["shukar ki dua", "alhamdulillah reminder"],
        "ur": ["\u0634\u06a9\u0631 \u06a9\u06cc \u062f\u0639\u0627"],
        "hash": "#Gratitude",
    },
    "occasions": {
        "en": ["sunnah occasions dua", "daily life duas"],
        "roman": ["masnoon duain", "roz ki duain"],
        "ur": ["\u0645\u0633\u0646\u0648\u0646 \u062f\u0639\u0627\u0626\u06cc\u06ba"],
        "hash": "#MasnoonDua",
    },
    "morning_evening": {
        "en": ["morning evening azkar", "daily adhkar"],
        "roman": ["subah o shaam ke azkar", "rozana ki duain"],
        "ur": ["\u0627\u0630\u06a9\u0627\u0631 \u0635\u0628\u062d \u0648 \u0645\u0633\u0627\u0621"],
        "hash": "#Azkar",
    },
    "general": {
        "en": ["general dua", "everyday islamic prayer"],
        "roman": ["jami dua", "mukhtasar dua"],
        "ur": ["\u062f\u0639\u0627\u0626\u06cc\u06ba \u0645\u0633\u0646\u0648\u0646\u06c1"],
        "hash": "#DailyDua",
    },
}

HASHTAG_POOL = [
    "#IslamicShorts",
    "#DailyDua",
    "#Sunnah",
    "#MuslimTikTok",
    "#QuranRecitation",
    "#PeacefulReminder",
    "#DuaForYou",
    "#IslamicReminder",
    "#Allah",
    "#Muslim",
]

OPENERS = [
    "",
    "",
    "\U0001f64f Ye dua sunein, dohrayein aur yaad karein:",
    "\U0001f64f Aaj ki sunnah dua - chand second mein seekhein:",
    "\u2728 Ek aur masnoon dua aapke liye:",
]

CTAS = [
    "Subscribe karein rozani ek nayi dua ke liye.",
    "Agar faida hua to Like & Share zaroor karein.",
    "Channel ko follow karein - daily authentic duain.",
    "Apne doston ko bhejein - sadqa jariya ban jayega.",
    "Save karein aur har roz parhein.",
    "Comment mein 'Ameen' likhein - dusron ko bhi dua milegi.",
]

FOOTERS = [
    "{channel}",
    "{channel} | {handle}",
    "Follow: {handle}",
    "",
]


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def content_words(text, min_len=4, limit=6):
    stop = {"ki", "ka", "ke", "se", "aur", "the", "for", "with", "from", "part"}
    words = re.findall(rf"[A-Za-z]{{{min_len},}}", text or "")
    out, seen = [], set()
    for w in words:
        lw = w.lower()
        if lw in stop or lw in seen:
            continue
        seen.add(lw)
        out.append(lw)
        if len(out) >= limit:
            break
    return out


def ref_keywords(reference):
    toks = re.findall(r"[A-Za-z]{3,}", reference or "")
    named = [
        t.lower()
        for t in toks
        if t.lower() in ("dawud", "tirmidhi", "bukhari", "muslim", "nasai", "majah", "quran", "surah")
    ]
    return named[:4]


def build_tags(dua, rot):
    cat = CATEGORY_SEO.get(dua.get("category"), CATEGORY_SEO["general"])
    pool = []
    rk = ref_keywords(dua.get("reference"))
    if rk:
        pool.append(" ".join(rk))
    pool += cat["en"][:2]
    pool.append(rot.pick(cat["roman"]))
    pool.append(rot.pick(cat["ur"]))
    part_no = dua.get("part")
    if part_no:
        pool.append("{} part {}".format(cat["en"][0], part_no))
    pool += content_words(dua.get("title_en") or dua.get("title") or "")
    pool += BASE_TAGS_EN
    pool += URDU_GENERIC_TAGS
    seen, final = set(), []
    for t in pool:
        t = t.strip().lower()
        if not t or t in seen:
            continue
        seen.add(t)
        final.append(t)
    while len(", ".join(final)) > MAX_TAGS_LINE and len(final) > 8:
        final.pop()
    return final


def hashtag_line(dua, rot):
    cat = CATEGORY_SEO.get(dua.get("category"), CATEGORY_SEO["general"])
    tw = "".join(w.capitalize() for w in (dua.get("title") or "Dua").split()[:2])
    picks = ["#Shorts", cat["hash"], "#" + tw]
    extra = rot.pick(HASHTAG_POOL, salt=11)
    more = rot.pick([h for h in HASHTAG_POOL if h != extra], salt=23)
    picks += [extra, more]
    seen, out = set(), []
    for h in picks:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return " ".join(out)


def ref_box(reference, rot):
    if not reference:
        return ""
    if rot.idx(2, salt=5) == 0:
        return f"\U0001f4d6 Reference: {reference}\n"
    bar = "-" * min(38, 12 + len(reference))
    return f"{bar}\n\U0001f4d6 {reference}\n{bar}\n"


def build_description(dua, rot, cfg):
    parts = []
    opener = rot.pick(OPENERS, salt=1)
    if opener:
        parts.append(opener)
    parts.append((dua.get("arabic") or "").strip())
    parts.append("")
    parts.append((dua.get("urdu") or "").strip())
    expl = (dua.get("explanation") or "").strip()
    if expl:
        parts.append("")
        parts.append("\u2139\ufe0f " + expl)
    box = ref_box(dua.get("reference"), rot)
    if box:
        parts.append("")
        parts.append(box.rstrip())
    cta = rot.pick(CTAS, salt=2)
    if cta:
        parts.append("")
        parts.append(cta)
    footer = rot.pick(FOOTERS, salt=3).format(
        channel=(cfg.get("channelName") or "Dua Channel").strip(), handle=(cfg.get("handle") or "").strip()
    )
    if footer.strip():
        parts.append("")
        parts.append(footer)
    tags_line = hashtag_line(dua, rot)
    body = "\n".join(parts).strip()
    room = MAX_DESC - len(tags_line) - 6 - len(DISCLAIMER)
    if len(body) > room:
        body = body[:room].rstrip()
    return body + "\n\n" + tags_line + "\n" + DISCLAIMER + "\n"


def main():
    dua_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not dua_id:
        print("usage: python scripts/metadata.py <dua_id>")
        return 1
    duas = load_json(os.path.join(PROJECT, "data", "duas.json"))
    if not isinstance(duas, list):
        duas = duas.get("duas", [])
    d = next(x for x in duas if x["id"] == dua_id)
    for k in ("title", "title_en", "reference", "arabic", "urdu", "explanation"):
        if isinstance(d.get(k), str):
            d[k] = clean(d[k])

    title = d.get("title", "Dua")
    ref = (d.get("reference") or "").strip()
    full_title = f"{title} | {ref}" if ref else title
    if len(full_title) > MAX_TITLE:
        full_title = full_title[:MAX_TITLE].rsplit(" ", 1)[0]

    rot = Rot(dua_id)
    cfg = {}
    if os.path.exists(CFG_PATH):
        with contextlib.suppress(Exception):
            cfg = load_json(CFG_PATH)

    lines = [
        "TITLE:",
        full_title,
        "",
        "DESCRIPTION:",
        build_description(d, rot, cfg),
        "TAGS:",
        ", ".join(build_tags(d, rot)),
        "",
    ]
    out = os.path.join(PROJECT, "remotion", "out", safe_title(title) + ".txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("metadata:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
