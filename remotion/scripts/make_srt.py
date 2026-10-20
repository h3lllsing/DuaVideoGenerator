"""Generate SRT subtitle files from word-timing manifest data.

For each dua it reads the existing remotion/src/data/<dua_id>.json manifest
(which holds arabicWords/urduWords as {t, start, end} timings) and groups the
words into readable phrase-level lines (3-4 words / ~2s each) rather than one
word per line.

Outputs (saved alongside the rendered video in remotion/out):
    <safe_title>.ar.srt  - Arabic lines
    <safe_title>.ur.srt  - Urdu lines
    <safe_title>.en.srt  - English translation of the Arabic lines:
                           FIRST the reference-based AUTHENTIC translation is
                           tried via verified_en.py (Quran -> Sahih
                           International from alquran.cloud, cached forever;
                           hadith -> AI prompted with the exact reference).
                           Only if no verified source exists does it fall
                           back to the global word glossary
                           data/srt_en_tokens.json (grown over time) and then
                           whole-line AI. Every generated EN is also queued
                           in data/en_review.json for mandatory human review -
                           it is NEVER attached to YouTube automatically.

Usage:
    python make_srt.py --dua-id rabbana_hasanah
    python make_srt.py --dua-id rabbana_hasanah --out out  --no-en

Output: JSON on the LAST stdout line: {"ok":true,"files":[...]}
"""

import argparse
import contextlib
import json
import os
import re
import sys

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REMOTION = os.path.join(PROJECT, "remotion")
DEFAULT_DATA = os.path.join(REMOTION, "src", "data")
DEFAULT_OUT = os.path.join(REMOTION, "out")
LOCAL_EN_PATH = os.path.join(PROJECT, "data", "srt_en.json")
LOCAL_EN_TOKENS_PATH = os.path.join(PROJECT, "data", "srt_en_tokens.json")
DUAS_PATH = os.path.join(PROJECT, "data", "duas.json")

MAX_WORDS = 4
MAX_SPAN = 2.0


def load_local_en():
    """Load local per-dua English gloss (dua_id -> {"words":[gloss per arabic word]})."""
    try:
        with open(LOCAL_EN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_local_en_tokens():
    """Load global Arabic-token -> English glossary.

    JSON shape: {"raw": {arabic: english}, "gloss": {normalized: english}}.
    """
    try:
        with open(LOCAL_EN_TOKENS_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def norm_token(t):
    import unicodedata

    t = unicodedata.normalize("NFKC", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return (
        t.replace("إ", "ا")
        .replace("أ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
        .replace("ى", "ي")
        .replace("ی", "ي")
        .replace("ة", "ه")
        .replace("ک", "ك")
    )


def gloss_from_tokens(arabic_words, tokens):
    """Build per-word English gloss array from the global token glossary.

    Returns (gloss_array, missing_words) where missing_words are the exact
    Arabic tokens (as written in the manifest) with NO entry in the glossary.
    """
    raw = tokens.get("raw") or {}
    gloss = tokens.get("gloss") or {}
    out = []
    missing = []
    for w in arabic_words:
        t = (w.get("t") or "").strip()
        if not t:
            out.append("")
            continue
        eng = raw.get(t)
        if eng is None:
            eng = gloss.get(norm_token(t))
        out.append(eng or "")
        if not eng:
            missing.append(t)
    return out, missing


def save_local_en_tokens(tokens):
    """Persist the (possibly grown) global glossary atomically.

    Returns True on success, False/None on failure. Keeps the existing
    on-disk file untouched when the write can't complete."
    """
    tmp = LOCAL_EN_TOKENS_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tokens, f, ensure_ascii=False, indent=1)
        os.replace(tmp, LOCAL_EN_TOKENS_PATH)
        return True
    except OSError:
        return False


def grow_tokens(tokens, word_map):
    """Insert fresh translations {arabic_token: english} into the glossary.

    Writes BOTH the raw key (exact token) and the normalized gloss key so
    future lookups hit regardless of tashkeel/orthography variants.
    """
    raw = tokens.setdefault("raw", {})
    gloss = tokens.setdefault("gloss", {})
    for t, en in word_map.items():
        t = (t or "").strip()
        en = (en or "").strip()
        if not t or not en:
            continue
        raw[t] = en
        gloss[norm_token(t)] = en
    return tokens


def ai_translate_words(words):
    """Translate a batch of Arabic words to English via ai_import infra.

    Only the words MISSING from the glossary are sent here (one batched
    call). Returns (word_map, None) on success or (None, err) on failure,
    where word_map is {arabic_token: english_gloss}.
    """
    try:
        sys.path.insert(0, os.path.join(REMOTION, "scripts"))
        from ai_import import API_KEYS, call_api, keyless_enabled
    except Exception as e:
        return None, f"AI infra load fail: {e}"

    if not API_KEYS and not keyless_enabled():
        return None, "Koi API key configured nahi hai - en.srt skipped"

    system = (
        "You are an expert Islamic translator. Translate each single Arabic "
        "word/token to a natural, concise English gloss suitable for a "
        "subtitle. Return ONLY a valid JSON array of strings, same order and "
        "count as input, one gloss per word. No markdown, no code fences."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(words, ensure_ascii=False)},
    ]
    keys = list(API_KEYS) if API_KEYS else [None]
    last_err = "no key tried"
    for key in keys:
        content, model = call_api(messages, key, require_dua=False)
        if content:
            parsed = _parse_ts(content)
            if parsed is not None and len(parsed) == len(words):
                return dict(zip(words, [str(x).strip() for x in parsed], strict=False)), None
            last_err = f"bad response ({model})"
        else:
            last_err = "all models failed"
    return None, last_err


def safe_title(title):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", title or "Dua").strip()


def fmt_ts(secs):
    secs = max(0.0, float(secs))
    ms = int(round(secs * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def group_words(words, max_words=MAX_WORDS, max_span=MAX_SPAN):
    """Group timed words into phrase lines of ~max_words or ~max_span secs.

    Returns list of (start, end, text, [word_indices]).
    """
    lines = []
    cur = []
    for idx, w in enumerate(words):
        if not cur:
            cur.append((idx, w))
            continue
        span = w["end"] - cur[0][1]["start"]
        if len(cur) < max_words and span <= max_span:
            cur.append((idx, w))
        else:
            lines.append((cur[0][1]["start"], cur[-1][1]["end"], " ".join(x["t"] for _, x in cur), [i for i, _ in cur]))
            cur = [(idx, w)]
    if cur:
        lines.append((cur[0][1]["start"], cur[-1][1]["end"], " ".join(x["t"] for _, x in cur), [i for i, _ in cur]))
    return lines


def en_from_glossary(ar_idx, gloss):
    """Build English line texts from per-word glosses aligned with arabicWords."""
    return [" ".join(gloss[i] for i in idxs if i < len(gloss) and gloss[i]) for (_, _, _, idxs) in ar_idx]


def srt_from_lines(lines):
    """Render SRT blocks from list of (start, end, text[, indices])."""
    blocks = []
    for i, (st, en, text, *_rest) in enumerate(lines, 1):
        blocks.append(f"{i}\n{fmt_ts(st)} --> {fmt_ts(en)}\n{text}\n")
    return "\n".join(blocks)


def load_dua_meta(dua_id):
    """Look up a dua's title/reference/arabic from data/duas.json."""
    try:
        with open(DUAS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        list_ = raw if isinstance(raw, list) else raw.get("duas") or []
        for d in list_:
            if d.get("id") == dua_id:
                return d
    except (OSError, ValueError):
        pass
    return None


def verified_en_source(dua_id):
    """Return (verified_full_text, source) if a verified translation exists.

    Uses remotion/scripts/verified_en.py: Quran refs -> Sahih International
    (alquran.cloud, cached forever), hadith refs -> AI prompted with the exact
    reference (cached). Returns (None, None) when no verified translation is
    available (caller then falls back to glossary/AI and queues for review).
    """
    try:
        sys.path.insert(0, os.path.join(REMOTION, "scripts"))
        import verified_en

        dua = verified_en.get_dua(dua_id)
        if not dua:
            return None, None
        en, source, _warn = verified_en.get_or_build_verified(dua)
        if en and source in ("quran-sahih", "hadith-ai"):
            return en, source
        return None, None
    except Exception:
        return None, None


def queue_en_review(dua_id, ref, ar, en, source):
    """Register an EN translation into the manual review queue (pending)."""
    try:
        sys.path.insert(0, os.path.join(REMOTION, "scripts"))
        import verified_en

        verified_en.queue_for_review(dua_id, ref, ar, en, source)
        return True
    except Exception:
        return False


def ai_translate_lines(lines):
    """Translate Arabic line texts to English via ai_import infa."""
    try:
        sys.path.insert(0, os.path.join(REMOTION, "scripts"))
        from ai_import import API_KEYS, call_api, keyless_enabled
    except Exception as e:
        return None, f"AI infra load fail: {e}"

    if not API_KEYS and not keyless_enabled():
        return None, "Koi API key configured nahi hai - en.srt skipped"

    system = (
        "You are an expert Islamic translator. Translate each Arabic dua line "
        "to natural, concise English subtitle text. Faithful, respectful, "
        "short enough for a subtitle. "
        "Return ONLY a valid JSON array of strings, same order and count as "
        "input. No markdown, no code fences."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(lines, ensure_ascii=False)},
    ]
    keys = list(API_KEYS) if API_KEYS else [None]
    last_err = "no key tried"
    for key in keys:
        content, model = call_api(messages, key, require_dua=False)
        if content:
            parsed = _parse_ts(content)
            if parsed is not None and len(parsed) == len(lines):
                return parsed, None
            last_err = f"bad response ({model})"
        else:
            last_err = "all models failed"
    return None, last_err


def _parse_ts(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dua-id", required=True)
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--no-en", action="store_true", help="skip AI English translation")
    args = ap.parse_args()

    manifest_path = os.path.join(args.data, args.dua_id + ".json")
    if not os.path.exists(manifest_path):
        print(json.dumps({"ok": False, "error": "manifest not found: " + manifest_path}, ensure_ascii=False))
        return 1
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"manifest read fail: {e}"}, ensure_ascii=False))
        return 1

    ar_lines = group_words(manifest.get("arabicWords") or [])
    ur_lines = group_words(manifest.get("urduWords") or [])
    if not ar_lines and not ur_lines:
        print(json.dumps({"ok": False, "error": "no word timing data in manifest"}, ensure_ascii=False))
        return 1

    title = manifest.get("title") or args.dua_id
    base = os.path.join(args.out, safe_title(title))
    os.makedirs(args.out, exist_ok=True)

    files_written = []
    for ext, lines in ((".ar", ar_lines), (".ur", ur_lines)):
        if not lines:
            continue
        p = base + ext + ".srt"
        with open(p, "w", encoding="utf-8") as f:
            f.write(srt_from_lines(lines))
        files_written.append(p)

    en = False
    en_warn = None
    en_path = base + ".en.srt"
    en_new_words = 0
    if not args.no_en and ar_lines:
        en_texts = None
        source = "ai"
        local_en = load_local_en().get(args.dua_id) or {}
        gloss = local_en.get("words") or []
        used = "per-dua"
        grow_map = {}
        missing = []
        en_meta = load_dua_meta(args.dua_id)

        # 1) Verified authentic translation (Quran Sahih Int / hadith AI):
        #    poora ayat/hadith ka tasdeeq-shuda tarjuma, word-by-word nahi.
        verified_en, verified_source = verified_en_source(args.dua_id)
        if verified_en:
            st, en_ = ar_lines[0][0], ar_lines[-1][1]
            timed = [(st, en_, verified_en)]
            with open(en_path, "w", encoding="utf-8") as f:
                f.write(srt_from_lines(timed))
            files_written.append(en_path)
            en = True
            source = verified_source
            # Review queue me entry verified_en_source() ke andar
            # get_or_build_verified() khud add karti hai (approval = gate)
            # — yahan dobara queue nahi karte.

        # 2) Fallback: glossary-first (grows over time), then line AI.
        elif not gloss:
            words = manifest.get("arabicWords") or []
            tokens = load_local_en_tokens()
            gloss, missing = gloss_from_tokens(words, tokens)
            used = "tokens"
            if missing:
                # Sirf naye (glossary se missing) lafz AI ko jayen.
                uniq_missing = []
                for _t in missing:
                    if _t not in uniq_missing:
                        uniq_missing.append(_t)
                word_map, w_err = ai_translate_words(uniq_missing)
                if word_map:
                    grow_map = grow_tokens(tokens, word_map)
                    en_new_words = len(word_map)
                    if not save_local_en_tokens(grow_map):
                        en_warn = "glossary save fail (words translated but not persisted)"
                    else:
                        en_warn = None
                    # Glossary ab updated hai - dobara lookup, missing local hojaayega.
                    gloss, missing = gloss_from_tokens(words, grow_map)
                    used = "tokens-grown"
                else:
                    en_warn = w_err
        if not verified_en and gloss and not missing:
            en_texts = en_from_glossary(ar_lines, gloss)
            if any(en_texts):
                source = (
                    "local"
                    if used == "per-dua"
                    else ("local-tokens-grown" if used == "tokens-grown" else "local-tokens")
                )
            else:
                en_texts = None
        if not verified_en and en_texts is None:
            source = "ai"
            en_texts, en_warn = ai_translate_lines([t for (_, _, t, _) in ar_lines])
        if not verified_en and en_texts:
            timed = []
            for (st, en_, _, _), t in zip(ar_lines, en_texts, strict=False):
                timed.append((st, en_, str(t).strip()))
            with open(en_path, "w", encoding="utf-8") as f:
                f.write(srt_from_lines(timed))
            files_written.append(en_path)
            en = True
            # Fallback translations review queue me jaati hain - YouTube se
            # pehle insaan ka approval lazmi.
            queue_en_review(
                args.dua_id,
                (en_meta or {}).get("reference"),
                (en_meta or {}).get("arabic") or " ".join(w.get("t", "") for w in (manifest.get("arabicWords") or [])),
                " ".join(str(t).strip() for t in en_texts),
                source,
            )

    print(
        json.dumps(
            {
                "ok": True,
                "duaId": args.dua_id,
                "title": title,
                "totalDuration": manifest.get("totalDuration"),
                "arLines": len(ar_lines),
                "urLines": len(ur_lines),
                "en": en,
                "enSource": source if en else None,
                "enNewWords": en_new_words if en else None,
                "enWarn": en_warn,
                "files": files_written,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
