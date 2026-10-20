"""Verified English translation for duas, driven by each dua's reference.

Two sources of AUTHENTIC (tasdeeq-shuda) English, never fresh word-by-word
invention:

* Quran dua  -> Sahih International translation fetched from alquran.cloud
                (endpoint /v1/ayah/<s>:<a>/en.sahih or /v1/surah/<n>/en.sahih).
                Fetched once, cached forever in data/verified_en.json.
* Hadith dua -> AI (ai_import) is prompted WITH the exact reference
                (collection + number) and the full Arabic to return the
                widely-accepted English translation. Cached forever too.

Every dua that gets an EN subtitle - verified or not - is ALSO entered into
data/en_review.json as a pending review item. Nothing is ever attached to
YouTube without a human approval in the dashboard.

Cache shapes:
    data/verified_en.json = { dua_id: {en, source, ref, ar, ts} }
         source: "quran-sahih" | "hadith-ai" | "ai-fallback"
    data/en_review.json   = { dua_id: {status, ref, ar, en, source,
                                       queue_ts, reviewed_ts} }
         status: "pending" | "approved" | "rejected"
    data/en_ai_cooldown.json = { normalized_reference: {fails, ts, window_hours} }
         negative cache: a failed hadith-AI attempt for a REFERENCE is recorded
         and skips further AI attempts until the window passes (default 6 hours,
         configurable via HADITH_AI_COOLDOWN_HOURS / --cooldown-hours). One fresh
         attempt is allowed after the window so a recovered AI is auto-repicked.
         Success clears the record immediately. This prevents re-sweeping a
         broken/quota-hit model on every single render.

Off the render critical path you can pre-build in the background:
    python scripts/verified_en.py --build-all
"""

import contextlib
import json
import os
import re
import sys
import time
import urllib.request

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT, "data")
DUAS_PATH = os.path.join(DATA_DIR, "duas.json")
VERIFIED_PATH = os.path.join(DATA_DIR, "verified_en.json")
REVIEW_PATH = os.path.join(DATA_DIR, "en_review.json")
COOLDOWN_PATH = os.path.join(DATA_DIR, "en_ai_cooldown.json")
REMOTION = os.path.join(PROJECT, "remotion")
API_BASE = "http://api.alquran.cloud"

# Hadith-AI negative cache (data/en_ai_cooldown.json), keyed by the
# NORMALIZED REFERENCE so the same hadith reference never re-sweeps the AI on
# every render while it is failing. Window is configurable in hours and
# defaults to HADITH_AI_COOLDOWN_HOURS. One fresh attempt is allowed after
# the window; success clears the record immediately.
HADITH_AI_COOLDOWN_HOURS = 6

# Surah names as they appear in duas.json reference field -> surah number.
# (alquran.cloud name lookup is unreliable for these transliterations.)
SURAH_NUM = {
    "al-a'raf": 7,
    "al-araf": 7,
    "al-anbiya": 21,
    "al-baqarah": 2,
    "al-fatihah": 1,
    "al-furqan": 25,
    "al-kahf": 18,
    "al-ma'idah": 5,
    "al-maidah": 5,
    "al-mu'minun": 23,
    "al-qamar": 54,
    "al-qasas": 28,
    "al-ali-imran": 3,
    "ali-imran": 3,
    "ali 'imran": 3,
    "al-imran": 3,
    "an-naml": 27,
    "ash-shu'ara": 26,
    "ash-shuara": 26,
    "az-zukhruf": 43,
    "bani israel": 17,
    "bani-israel": 17,
    "hud": 11,
    "ibrahim": 14,
    "taha": 20,
    "ta-ha": 20,
    "yusuf": 12,
    "al-asr": 103,
    "asr": 103,
    "ya-sin": 36,
    "yaseen": 36,
    "sad": 38,
    "al-bayyina": 98,
    "al-falaq": 113,
    "an-nas": 114,
    "al-ikhlas": 112,
    "al-ankabut": 29,
    "al-muzzammil": 73,
    "ad-duha": 93,
    "ad-duhha": 93,
}


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or default
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_duas():
    raw = _read_json(DUAS_PATH, [])
    return raw if isinstance(raw, list) else raw.get("duas") or []


def load_verified():
    return _read_json(VERIFIED_PATH, {})


def save_verified(store):
    _write_json(VERIFIED_PATH, store)


def load_review():
    return _read_json(REVIEW_PATH, {})


def save_review(store):
    _write_json(REVIEW_PATH, store)


def _cooldown_key(ref):
    """Normalize a reference so the same hadith source shares one record."""
    return norm_ref(ref or "")


def ai_cooldown_active(ref, hours=None):
    """True while a recorded AI failure for this reference is still inside the
    cooldown window -> caller should skip the AI attempt entirely.

    hours overrides HADITH_AI_COOLDOWN_HOURS for that check, enabling the
    dashboard/CLI to tune the window without touching the stored record.
    """
    key = _cooldown_key(ref)
    if not key:
        return False
    rec = _read_json(COOLDOWN_PATH, {}).get(key)
    if not rec:
        return False
    window = int((hours if hours is not None else int(rec.get("window_hours") or HADITH_AI_COOLDOWN_HOURS)) * 3600)
    return (time.time() - int(rec.get("ts", 0))) < window


def _record_ai_failure(ref, hours=None):
    """Record a failed AI attempt so further attempts are suppressed for the
    window. Consecutive failures raise a counter (observability only); the
    window itself stays at the configured hours."""
    key = _cooldown_key(ref)
    if not key:
        return
    store = _read_json(COOLDOWN_PATH, {})
    rec = store.get(key) or {"fails": 0}
    rec["fails"] = int(rec.get("fails", 0)) + 1
    rec["ts"] = int(time.time())
    rec["window_hours"] = hours if hours is not None else HADITH_AI_COOLDOWN_HOURS
    store[key] = rec
    _write_json(COOLDOWN_PATH, store)


def _clear_ai_failure(ref):
    """Immediately drop any failure record for this reference (AI succeeded)."""
    key = _cooldown_key(ref)
    if not key:
        return
    store = _read_json(COOLDOWN_PATH, {})
    if store.pop(key, None) is not None:
        _write_json(COOLDOWN_PATH, store)


def get_dua(dua_id):
    for d in load_duas():
        if d.get("id") == dua_id:
            return d
    return None


def norm_ref(r):
    """Normalize a reference string for matching: lowercase, strip punctuation."""
    if not r:
        return ""
    return re.sub(r"[^a-z0-9 ]+", " ", (r or "").lower()).strip()


_QURAN_RE = re.compile(r"(?P<surah>\d{1,3})\s*[:]\s*(?P<a1>\d{1,3})\s*(?:-\s*(?P<a2>\d{1,3}))?")
_SURAH_NAME_RE = re.compile(
    r"(?P<kind>surah|quran surah)\s+(?P<name>[a-z'\u2019-][a-z'\u2019 -]*?)\s*"
    r"(?P<a1>\d{1,3})\s*(?:[:]\s*(?P<a2>\d{1,3})\s*(?:-\s*(?P<a3>\d{1,3}))?)?"
)
_HADITH_RE = re.compile(
    r"(sahih\s+muslim|sahih\s+bukhari|sunan\s+(?:abi|abu)\s+(?:dawud|dawood|dawd)|"
    r"abu\s+(?:dawud|dawood|dawd)|"
    r"sunan\s+an-nasa'i|sunan\s+an-nasai|sunan\s+ibn\s+majah|sunan\s+tirmidhi|"
    r"sunan\s+(?:al[- ])?tirmidhi|jami(?:'|`)?[\s-]+(?:at[\s-]+)?tirmidhi|"
    r"jami\s+tirmidhi|tirmizi|musnad\s+ahmad|muwatta\s+malik|"
    r"al-mu'jam\s+al-kabir(?:\s+tabarani)?|sharh\s+as-sunnah(?:\s+baghawi)?|"
    r"riyad\s+al-salihin|al-adab\s+al-mufrad)\s*[:#.-]?\s*(\d+)"
)


def parse_reference(ref):
    """Return {"quran": [surah, ayah_start, ayah_end_or_None], "hadith": [...]}.

    Encoding rules:
      no range  -> [surah, a, a]
      range     -> [surah, a1, a2]
      whole surah (e.g. "Quran Surah Al-Asr 103") -> [surah, None, None];
                    fetch_en_ayahs expands it to the surah's full ayah count.
    """
    out = {"quran": None, "hadith": None}
    if not ref:
        return out
    low = ref.lower().replace("\u2019", "'")
    hadith_ms = _HADITH_RE.findall(low)

    # Prefer an explicit numeric quran form.
    m = _QURAN_RE.search(low)
    if m:
        out["quran"] = [
            int(m.group("surah")),
            int(m.group("a1")),
            int(m.group("a2")) if m.group("a2") else int(m.group("a1")),
        ]

    # Named-surah form covers the remaining refs.
    m2 = _SURAH_NAME_RE.search(low)
    if m2:
        name = m2.group("name").strip()
        num = SURAH_NUM.get(name)
        if num:
            if m2.group("a2"):
                a3 = int(m2.group("a3")) if m2.group("a3") else None
                out["quran"] = [num, int(m2.group("a2")), a3 if a3 else int(m2.group("a2"))]
            elif not (m and m.group("surah")) and m2.group("a1"):
                only = int(m2.group("a1"))
                # "Surah Ibrahim 40" -> ayah 40 of surah 14 (only != num).
                # "Quran Surah Al-Asr 103" -> whole surah (only == num).
                if only == num and m2.group("kind") == "quran surah":
                    out["quran"] = [num, None, None]
                else:
                    out["quran"] = [num, only, only]

    if hadith_ms:
        out["hadith"] = [[c, int(n)] for (c, n) in hadith_ms]
    return out


def verse_count(surah):
    """Number of ayahs in a surah (looked up once and cached in module)."""
    if not hasattr(verse_count, "_cache"):
        verse_count._cache = {}
    if surah in verse_count._cache:
        return verse_count._cache[surah]
    try:
        req = urllib.request.Request(API_BASE + "/v1/surah/%d" % surah, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        n = len(data["data"]["ayahs"])
        verse_count._cache[surah] = n
        return n
    except Exception:
        return None


def fetch_en_ayahs(surah, a1, a2=None):
    """Fetch Sahih International English for ayahs [a1..a2] (or single a1).

    Returns list of English strings in ayah order, or None on network error.
    """
    if a2 is None:
        a2 = a1
    out = []
    n = verse_count(surah)
    if n is None:
        return None
    a2 = min(a2, n)
    for a in range(a1, a2 + 1):
        url = "%s/v1/ayah/%d:%d/en.sahih" % (API_BASE, surah, a)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            out.append(data["data"]["text"].strip())
        except Exception:
            return None
    return out


def ai_hadith_translation(reference, arabic, title):
    """Translate a hadith dua via AI prompted with the exact reference.

    Returns (en_text, model) or (None, err). The AI is told to give the
    established, widely-accepted English rendering - not a fresh paraphrase.
    """
    try:
        sys.path.insert(0, os.path.join(REMOTION, "scripts"))
        from ai_import import API_KEYS, call_api, keyless_enabled
    except Exception as e:
        return None, f"AI infra load fail: {e}"
    if not API_KEYS and not keyless_enabled():
        return None, "Koi API key configured nahi hai"
    system = (
        "You are an expert Islamic translator. The user gives you the source "
        "reference of a hadith (collection and number) together with the "
        "Arabic dua text. Provide the authentic, widely-accepted English "
        "translation of this exact hadith/dua - e.g. the rendering found in "
        "standard published editions (such as Dar-us-Salam's Sahih series). "
        "Do NOT paraphrase or invent. Return ONLY the English translation "
        "text, no commentary, no citation, no markdown."
    )
    prompt = f"REFERENCE: {reference}\nTITLE: {title}\nARABIC: {arabic}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    keys = list(API_KEYS) if API_KEYS else [None]
    last_err = "no key tried"
    for key in keys:
        content, model = call_api(messages, key, require_dua=False)
        if content:
            text = str(content).strip()
            if len(text) > 15:
                return text, model
            last_err = f"bad response ({model})"
        else:
            last_err = "all models failed"
    return None, last_err


def ai_fallback_translation(ar_lines):
    """AI whole-line translation (fallback when no verified source exists)."""
    try:
        sys.path.insert(0, os.path.join(REMOTION, "scripts"))
        from ai_import import API_KEYS, call_api, keyless_enabled
    except Exception as e:
        return None, f"AI infra load fail: {e}"
    if not API_KEYS and not keyless_enabled():
        return None, "Koi API key configured nahi hai"
    system = (
        "You are an expert Islamic translator. Translate each Arabic dua "
        "line to natural, concise English subtitle text. Faithful, "
        "respectful, short enough for a subtitle. Return ONLY a valid JSON "
        "array of strings, same order and count as input. No markdown."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(ar_lines, ensure_ascii=False)},
    ]
    keys = list(API_KEYS) if API_KEYS else [None]
    last_err = "no key tried"
    for key in keys:
        content, model = call_api(messages, key, require_dua=False)
        if content:
            text = str(content).strip()
            m = re.search(r"\[.*\]", text, re.S)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                    if isinstance(parsed, list) and len(parsed) == len(ar_lines):
                        return parsed, model
                except Exception:
                    pass
            last_err = f"bad response ({model})"
        else:
            last_err = "all models failed"
    return None, last_err


def queue_for_review(dua_id, ref, ar, en, source, status="pending"):
    """Add/update this dua's EN entry in the review queue.

    A re-run never silently resets an existing approval: when the entry is
    already "approved"/"rejected" AND the English text is unchanged, the
    terminal status is preserved (render pipeline re-queues every time).
    Only a NEW translation (changed text) downgrades back to pending.
    """
    store = load_review()
    entry = store.get(dua_id) or {}
    prev_status = entry.get("status")
    prev_en = entry.get("en")
    changed = en is not None and en != prev_en
    if prev_status in ("approved", "rejected") and not changed:
        status = prev_status
    entry.update(
        {
            "status": status,
            "ref": ref or entry.get("ref"),
            "ar": ar,
            "en": en,
            "source": source,
            "queue_ts": entry.get("queue_ts") or int(time.time()),
            "reviewed_ts": entry.get("reviewed_ts"),
        }
    )
    store[dua_id] = entry
    save_review(store)
    return entry


def set_review_status(dua_id, status, note=None):
    store = load_review()
    if dua_id not in store:
        return False
    store[dua_id]["status"] = status
    store[dua_id]["reviewed_ts"] = int(time.time())
    if note:
        store[dua_id]["note"] = note
    save_review(store)
    return True


def get_verified(dua_id):
    """Return cached verified entry {en, source, ref, ar, ts} or None."""
    return load_verified().get(dua_id)


def cache_verified(dua_id, en, source, ref, ar):
    store = load_verified()
    store[dua_id] = {
        "en": en,
        "source": source,
        "ref": ref,
        "ar": ar,
        "ts": int(time.time()),
    }
    save_verified(store)


def quran_verified(dua):
    """Try to build a verified Quran translation for a dua from its reference.

    Returns (en_text, ref) or (None, None). result['quran'] sentinel: a whole
    surah is encoded with ayah range 1..count saturating the surah length.
    """
    ref = dua.get("reference") or ""
    parsed = parse_reference(ref)
    q = parsed["quran"]
    if not q:
        return None, None
    surah, a1, a2 = q
    if a1 is None:  # whole-surah encoding
        n = verse_count(surah)
        if n is None:
            return None, None
        a1, a2 = 1, n
    en_ayahs = fetch_en_ayahs(surah, a1, a2)
    if en_ayahs is None:
        return None, None
    return " ".join(en_ayahs), ref


def get_or_build_verified(dua, ar_lines=None):
    """Main entry: return (en_text, source, warn).

    Priority:
      1. verified_en.json cache.
      2. Quran reference -> Sahih International (fetched once, cached).
      3. Hadith reference -> AI prompted with reference (cached).
      4. None (caller falls back to glossary/line AI).
    Every generated result is queued for review (pending).
    """
    dua_id = dua.get("id")
    cached = get_verified(dua_id)
    if cached:
        queue_for_review(dua_id, dua.get("reference"), cached.get("ar"), cached["en"], cached["source"])
        return cached["en"], cached["source"], None

    ref = dua.get("reference") or ""
    ar = dua.get("arabic") or ""
    title = dua.get("title") or dua_id

    en, src = quran_verified(dua)
    if en:
        cache_verified(dua_id, en, "quran-sahih", ref, ar)
        queue_for_review(dua_id, ref, ar, en, "quran-sahih")
        return en, "quran-sahih", None

    hadith = parse_reference(ref)["hadith"]
    if hadith:
        if ai_cooldown_active(ref):
            return None, None, ("hadith AI cooldown active (skip attempt; retry after %dh)" % HADITH_AI_COOLDOWN_HOURS)
        en, warn = ai_hadith_translation(ref, ar, title)
        if en:
            _clear_ai_failure(ref)
            cache_verified(dua_id, en, "hadith-ai", ref, ar)
            queue_for_review(dua_id, ref, ar, en, "hadith-ai")
            return en, "hadith-ai", warn
        _record_ai_failure(ref)
        return None, None, warn

    return None, None, None


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--dua-id")
    ap.add_argument(
        "--build-all",
        action="store_true",
        help="Pre-build verified EN for every dua in the background (Quran via Sahih Int, hadith via AI)",
    )
    ap.add_argument("--force", action="store_true", help="With --build-all: ignore AI cooldown and retry now")
    ap.add_argument("--limit", type=int, default=0, help="With --build-all: stop after N duas (0 = all)")
    ap.add_argument(
        "--cooldown-hours",
        type=float,
        default=0,
        help=f"Override the hadith-AI cooldown window in hours (default module HADITH_AI_COOLDOWN_HOURS = {HADITH_AI_COOLDOWN_HOURS:g})",
    )
    args = ap.parse_args()

    if args.cooldown_hours > 0:
        globals()["HADITH_AI_COOLDOWN_HOURS"] = args.cooldown_hours

    if args.build_all:
        if args.force:
            _write_json(COOLDOWN_PATH, {})
        built = failed = other = seen = 0
        for d in load_duas():
            p = parse_reference(d.get("reference") or "")
            if not p["quran"] and not p["hadith"]:
                other += 1
                continue
            en, source, warn = get_or_build_verified(d)
            if en:
                built += 1
                print("  OK   %-45s %s" % (d.get("id"), source))
            else:
                failed += 1
                print("  FAIL %-45s %s" % (d.get("id"), warn or "no source"))
            seen += 1
            if args.limit and seen >= args.limit:
                break
        print(json.dumps({"ok": True, "built": built, "failed": failed, "no_reference": other}, ensure_ascii=False))
        raise SystemExit(0)

    if not args.dua_id:
        ap.error("--dua-id required (or use --build-all)")
    dua = get_dua(args.dua_id)
    if not dua:
        print(json.dumps({"ok": False, "error": "dua not found in duas.json"}, ensure_ascii=False))
        raise SystemExit(1)
    en, source, warn = get_or_build_verified(dua)
    print(
        json.dumps({"ok": bool(en), "duaId": args.dua_id, "source": source, "warn": warn, "en": en}, ensure_ascii=False)
    )
