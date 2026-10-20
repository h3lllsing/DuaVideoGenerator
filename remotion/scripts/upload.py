"""YouTube Shorts uploader with ledger + quota safety (Pillar 4).

Usage:
  python scripts/upload.py --only id1,id2       # MANUAL selection
  python scripts/upload.py --live --only id1,id2
  python scripts/upload.py --auto 3 --live      # AUTOPILOT: oldest-first
                                 (locks/REF-GUARD/quota auto-respected)
  python scripts/upload.py --only id1,id2 --privacy unlisted
  python scripts/upload.py --token data/yt_token_channel1.json \
         --ledger data/upload_state_channel1.json --auto 3 --live
  python scripts/upload.py --token data/yt_token_channel2.json \
         --ledger data/upload_state_channel2.json --only id1,id2 --live

Safety:
- upload_state.json atomic ledger {dua_id: {status, video_id, ...}}
  prevents double-posting.
- Quota ceiling: max 5 uploads/day (5 x 1600 = 8000 of 10000 units,
  2000-unit reserve for thumbnails.set / quota checks).
- Thumbnail STRICTLY resolved as out/thumbs/<dua_id>.png.
- AUTOPILOT: single-flight lock (.autopilot.lock), append-only
  data/auto_runs.log journal, permanent locks + REF-GUARD honoured,
  oldest-rendered-first picking, hard cap by remaining daily quota.
- EN SUBTITLES: never auto-attached. English .srt files are prepared in the
  background for manual review; captions can only ever be attached after an
  "approved" entry in data/en_review.json (see en_caption_allowed()).

Live mode requires google libs + data/yt_token.json (youtube_auth.py login).
"""

import argparse
import atexit
import contextlib
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(PROJECT, "remotion", "out")
THUMB_DIR = os.path.join(OUT, "thumbs")
DATA_DIR = os.path.join(PROJECT, "remotion", "src", "data")
PUBLIC = os.path.join(PROJECT, "remotion", "public")
PUBLIC_AUDIO = os.path.join(PUBLIC, "audio")
PUBLIC_BG = os.path.join(PUBLIC, "backgrounds")
TEMP = os.path.join(PROJECT, "temp")
LEDGER_PATH = os.path.join(PROJECT, "data", "upload_state.json")
METADATA_PY = os.path.join(PROJECT, "remotion", "scripts", "metadata.py")

UPLOAD_UNITS = 1600
DAILY_BUDGET = 10000
QUOTA_RESERVE = 2000
DAILY_CEILING = (DAILY_BUDGET - QUOTA_RESERVE) // UPLOAD_UNITS  # -> 5
MAX_TITLE = 100
MAX_THUMB_BYTES = 2 * 1024 * 1024

AUTO_LOCK = os.path.join(PROJECT, "data", ".autopilot.lock")
AUTO_LOCK_STALE_SEC = 45 * 60  # crashed-run leftovers expire after 45 min


def autopilot_lock_acquire():
    """Best-effort single-flight guard: scheduler runs never overlap each
    other or a manual portal upload mid-flight. Stale locks (crash) expire."""
    try:
        if os.path.exists(AUTO_LOCK):
            age = time.time() - os.path.getmtime(AUTO_LOCK)
            if age < AUTO_LOCK_STALE_SEC:
                return False, f"another run active ({age / 60.0:.0f}m ago)"
        with open(AUTO_LOCK, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        return True, ""
    except OSError as e:
        return False, str(e)


def autopilot_lock_release():
    with contextlib.suppress(OSError):
        os.remove(AUTO_LOCK)


def auto_log(runs_path, msg):
    """Append-only structured journal: data/auto_runs.log"""
    try:
        with open(runs_path, "a", encoding="utf-8") as f:
            f.write("[{}] {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError as e:
        print("auto-log write fail:", e)


def safe_title(title):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", title or "Dua").strip()
    return re.sub(r"[. ]+$", "", s) or "Dua"


def norm_ref(r):
    return re.sub(r"[^a-z0-9]+", " ", (r or "").lower()).strip()


def manifest_reference(dua_id):
    try:
        m = json.load(open(os.path.join(DATA_DIR, dua_id + ".json"), encoding="utf-8"))
        return norm_ref(m.get("reference"))
    except Exception:
        return ""


# ---------------- EN subtitle review gate ----------------
# English subtitles are generated in the background (make_srt.py ->
# data/verified_en.json + data/en_review.json) but are NEVER attached to
# YouTube. This is deliberate: verified translations need a human approval
# first. do_live_upload() intentionally never calls the youtube captions API.
# If caption attachment is added later it MUST call en_caption_allowed() and
# skip/raise unless it returns True.
EN_REVIEW_PATH = os.path.join(PROJECT, "data", "en_review.json")


def en_caption_allowed(dua_id):
    """True only when the review queue has APPROVED this dua's EN subtitle.

    Returns False when there is no entry, the entry is pending/rejected, or
    the review file is unreadable. Used as the hard gate for any future
    caption-attach call.
    """
    try:
        with open(EN_REVIEW_PATH, encoding="utf-8") as f:
            store = json.load(f)
        entry = store.get(dua_id) or {}
        return entry.get("status") == "approved"
    except (OSError, ValueError):
        return False


# ---------------- ledger ----------------


def load_ledger(path=LEDGER_PATH):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("WARN ledger unreadable, fresh:", e)
    return {}


def _atomic_json_write(path, data):
    """Write JSON atomically via a unique process-safe temp file, so two
    concurrent writers can never clobber the same .tmp inode mid-write."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix="state_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def save_ledger(ledger, path=LEDGER_PATH):
    _atomic_json_write(path, ledger)


def uploads_today(ledger):
    today = date.today().isoformat()
    return sum(
        1 for v in ledger.values() if v.get("status") == "uploaded" and str(v.get("uploaded_at", "")).startswith(today)
    )


def quota_path_for(ledger_path):
    d = os.path.dirname(os.path.abspath(ledger_path)) or "."
    b = os.path.basename(ledger_path)
    b = b.replace("upload_state", "quota_state") if "upload_state" in b else "quota_" + b
    return os.path.join(d, b)


def load_quota(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_quota(q, path):
    cutoff = (date.today() - timedelta(days=60)).isoformat()
    q = {k: v for k, v in q.items() if k >= cutoff}
    _atomic_json_write(path, q)


def units_today(quota):
    try:
        return int(quota.get(date.today().isoformat(), 0))
    except Exception:
        return 0


def record_units(quota_path, units):
    q = load_quota(quota_path)
    t = date.today().isoformat()
    q[t] = int(q.get(t, 0)) + int(units)
    save_quota(q, quota_path)
    return q[t]


def locked_duas():
    try:
        p = os.path.join(PROJECT, "data", "locked_duas.json")
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def archived_ids():
    try:
        duas = json.load(open(os.path.join(PROJECT, "data", "duas.json"), encoding="utf-8"))
        if isinstance(duas, dict):
            duas = duas["duas"]
        return {d["id"] for d in duas if d.get("archived")}
    except Exception:
        return set()


# ---------------- item resolution ----------------


def parse_sidecar(path):
    meta = {"title": None, "description": None, "tags": []}
    try:
        text = open(path, encoding="utf-8").read()
        m = re.search(r"^TITLE:\s*\n(.+)", text, re.M)
        if m:
            meta["title"] = m.group(1).strip()[:MAX_TITLE]
        m = re.search(r"^DESCRIPTION:\s*\n(.*?)\nTAGS:", text, re.S | re.M)
        if m:
            meta["description"] = m.group(1).strip()
        m = re.search(r"^TAGS:\s*\n(.+)$", text, re.M)
        if m:
            meta["tags"] = [t.strip() for t in m.group(1).split(",") if t.strip()]
    except Exception:
        pass
    return meta


def _shrink_thumb(path):
    """In-place downscale so YouTube's 2MB thumbnail limit is met.
    Returns True when the file now fits (or already fit)."""
    if os.path.getsize(path) <= MAX_THUMB_BYTES:
        return True
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        im = Image.open(path)
        w, h = im.size
        target_w = 720
        if w > target_w:
            im = im.resize((target_w, int(h * target_w / w)), Image.LANCZOS)
        im.save(path, optimize=True)
        return os.path.getsize(path) <= MAX_THUMB_BYTES
    except Exception:
        return False


def resolve_item(dua_id):
    reasons = []
    mpath = os.path.join(DATA_DIR, dua_id + ".json")
    if not os.path.exists(mpath):
        return None, ["no manifest"]
    try:
        with open(mpath, encoding="utf-8") as _f:
            manifest = json.load(_f)
    except Exception as e:
        return None, ["corrupt manifest: " + str(e)[:80]]
    if not isinstance(manifest, dict):
        return None, ["manifest not an object"]
    title = manifest.get("title") or dua_id
    ref_raw = (manifest.get("reference") or "").strip()

    mp4 = os.path.join(OUT, safe_title(title) + ".mp4")
    if not os.path.exists(mp4):
        reasons.append("no video: " + os.path.basename(mp4))

    thumb = os.path.join(THUMB_DIR, dua_id + ".png")
    if not os.path.exists(thumb):
        # Legacy renders saved thumbs under title-based names; adopt them
        # (self-healing migration so those items enter the auto pool).
        legacy_thumb = os.path.join(THUMB_DIR, safe_title(title) + ".png")
        if os.path.exists(legacy_thumb):
            try:
                shutil.move(legacy_thumb, thumb)
                reasons.append("thumb migrated (title->id)")
            except OSError:
                thumb = legacy_thumb
    if not os.path.exists(thumb):
        reasons.append("no thumb: " + dua_id + ".png")
    elif not _shrink_thumb(thumb):
        reasons.append("thumb >2MB (shrink failed)")

    sidecar = os.path.join(OUT, safe_title(title) + ".txt")
    if not os.path.exists(sidecar):
        r = subprocess.run([sys.executable, METADATA_PY, dua_id], capture_output=True, text=True)
        if r.returncode != 0:
            reasons.append("sidecar missing & regen failed")
    meta = parse_sidecar(sidecar)
    if not meta["title"]:
        meta["title"] = title[:MAX_TITLE]
        reasons.append("sidecar parse fallback (manifest title)")
    return {"dua_id": dua_id, "mp4": mp4, "thumb": thumb, "reference": ref_raw, "meta": meta}, reasons


def full_cleanup_after_upload(dua_id, title):
    """Remove ALL build artifacts after a successful upload.

    Only the durable record remains: duas.json (Arabic/Urdu text) and the
    upload ledger (upload_state.json). Everything else — narration mp3,
    manifest, background, thumb and temp audio/timing/look files — is
    deleted so no disk space is wasted and nothing can be double-reused.
    Safe: only touched for a video that was just uploaded (success path).
    """
    removed = 0
    paths = []

    try:
        # mastered narration
        paths.append(os.path.join(PUBLIC_AUDIO, dua_id + ".mp3"))
        # manifest (composition spec)
        paths.append(os.path.join(DATA_DIR, dua_id + ".json"))
        # id-based thumbnail
        paths.append(os.path.join(THUMB_DIR, dua_id + ".png"))
        # background assets copied for this dua
        if os.path.isdir(PUBLIC_BG):
            for bf in os.listdir(PUBLIC_BG):
                if bf.startswith(dua_id + "."):
                    paths.append(os.path.join(PUBLIC_BG, bf))
        # temp build files: audio + timing + merged wav + look spec
        if os.path.isdir(TEMP):
            for tf in os.listdir(TEMP):
                if tf.startswith(dua_id + "_"):
                    paths.append(os.path.join(TEMP, tf))
    except OSError as e:
        print("  WARN cleanup enumerate fail:", str(e)[:120])

    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        except OSError as ce:
            print("  WARN cleanup failed:", os.path.basename(p), "-", str(ce)[:100])
    print(f"  FULL-CLEANUP removed {removed} file(s) for {dua_id}")
    return removed


def uniqueness_audit(entries):
    def norm(s):
        return re.sub(r"\s+", " ", s or "").strip().lower()

    seen = {"title": {}, "tags": {}, "desc": {}}
    dups = {"title": [], "tags": [], "desc": []}
    hashes = set()
    for e in entries:
        t = norm(e["title"])
        g = norm(", ".join(e["tags"]))
        d = norm(e["description"].split("--- Disclaimer ---")[0])
        hashes.add(hashlib.sha1(t.encode("utf-8")).hexdigest()[:8])
        for key, val in (("title", t), ("tags", g), ("desc", d)):
            if val in seen[key]:
                dups[key].append((seen[key][val], e["dua_id"]))
            else:
                seen[key][val] = e["dua_id"]
    return dups, len(hashes)


def build_payload(item, privacy, category_id):
    return {
        "snippet": {
            "title": item["meta"]["title"],
            "description": item["meta"]["description"],
            "tags": item["meta"]["tags"],
            "categoryId": category_id,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }


# ---------------- live upload ----------------


def get_youtube_service(token_path=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import youtube_auth

    if token_path:
        youtube_auth.set_token_path(token_path)
    cred = youtube_auth.get_credentials()
    if not cred:
        return None
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=cred)


def do_live_upload(service, item, payload):
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    body = dict(payload)
    media = MediaFileUpload(item["mp4"], chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    attempts = 0
    while response is None:
        try:
            status, response = req.next_chunk()
        except HttpError as e:
            code = getattr(getattr(e, "resp", None), "status", 0) or 0
            if (code >= 500 or code == 429) and attempts < 3:
                attempts += 1
                wait = 2**attempts
                print(f"  retry {attempts}/3 in {wait}s (HTTP {code})", flush=True)
                time.sleep(wait)
                continue
            raise
        except OSError as e:
            if attempts < 3:
                attempts += 1
                wait = 2**attempts
                print(f"  retry {attempts}/3 in {wait}s (network: {str(e)[:80]})", flush=True)
                time.sleep(wait)
                continue
            raise
        if status:
            print(f"\r  upload {int(status.progress() * 100)}%", end="", flush=True)
    print()
    vid = response.get("id")
    if not vid:
        raise RuntimeError("no video id in response: " + json.dumps(response)[:300])
    try:
        service.thumbnails().set(videoId=vid, media_body=item["thumb"]).execute()
    except Exception as e:
        print("  WARN thumbnail attach failed (account verified?):", e)
    # EN subtitle policy: NEVER auto-attach captions. The .en.srt is created
    # in the background purely for manual review (data/en_review.json). Only
    # an "approved" entry could ever be attached - and even then nothing here
    # calls the captions API. This block only reports status for visibility.
    dua_id = item.get("dua_id")
    if dua_id:
        if en_caption_allowed(dua_id):
            print("  EN caption: approved for review, but attach is DISABLED")
        else:
            print("  EN caption: NOT attached (pending manual review)")
    return vid


# ---------------- main ----------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="actually upload (default is dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry-run (default anyway)")
    ap.add_argument("--only", default="", help="comma-separated dua_ids (MANUAL selection)")
    ap.add_argument(
        "--auto",
        type=int,
        default=0,
        metavar="N",
        help="AUTOPILOT: pick up to N oldest rendered-not-"
        "uploaded videos automatically; locks, REF-GUARD "
        "and remaining daily quota all honoured",
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--privacy", default="unlisted", choices=["private", "public", "unlisted"])
    ap.add_argument("--category-id", default="22")
    ap.add_argument(
        "--token",
        default=None,
        help="yt token json path for target channel, e.g. data/yt_token_channel1.json (default data/yt_token.json)",
    )
    ap.add_argument(
        "--ledger",
        default=LEDGER_PATH,
        help="upload state ledger path; use per-channel files "
        "e.g. data/upload_state_channel1.json to keep "
        "channels independent (default data/"
        "upload_state.json)",
    )
    args = ap.parse_args()
    if not args.only.strip() and not (args.auto and args.auto > 0):
        ap.error("either --only id1,id2 or --auto N is required")
    ledger_path = os.path.abspath(args.ledger)
    qpath = quota_path_for(ledger_path)
    token_label = args.token or "data/yt_token.json (default)"
    auto_mode = bool(args.auto and args.auto > 0)
    auto_runs_path = os.path.join(os.path.dirname(ledger_path), "auto_runs.log")
    # Graceful cancel: portal is flag-file likhta hai; hum har video se
    # PEHLE check karte hain - chalta hua upload poora hota hai, agla
    # nahi shuru hota (no orphan uploads, no ledger mismatch).
    cancel_flag = os.path.join(os.path.dirname(ledger_path), ".yt_cancel")

    if auto_mode:
        ok, why = autopilot_lock_acquire()
        if not ok:
            print(f"AUTOPILOT: skip - {why}")
            auto_log(auto_runs_path, "SKIP locked-out :: " + why)
            return 0
        atexit.register(autopilot_lock_release)

    ledger = load_ledger(ledger_path)
    used_today = uploads_today(ledger)
    qunits = units_today(load_quota(qpath))
    quploads = qunits // UPLOAD_UNITS
    eff_used = max(used_today, quploads)
    remaining_today = DAILY_CEILING - eff_used

    if auto_mode:
        auto_log(
            auto_runs_path,
            f"RUN start mode=AUTO n={args.auto} live={bool(args.live)} privacy={args.privacy} "
            f"token={token_label} used_today={eff_used}/{DAILY_CEILING} remaining={max(remaining_today, 0)}",
        )

    all_manifests = sorted(f[:-5] for f in os.listdir(DATA_DIR) if f.endswith(".json"))
    only_set = {x.strip() for x in args.only.split(",") if x.strip()}
    ids = [i for i in all_manifests if not only_set or i in only_set]
    arch = archived_ids()
    locks = locked_duas()
    locked_refs = {}
    for _lk, _lv in locks.items():
        _rn = norm_ref(_lv.get("reference"))
        if _rn:
            locked_refs[_rn] = _lk

    # Content-level guard: collect Arabic text of already-uploaded duas
    # so we don't re-upload the same dua content under a different id.
    def _strip_diacritics(s):
        return re.sub(r"[\u064B-\u065F\u0670\u0640]+", "", s or "")

    def _normalize_ar(s):
        return re.sub(r"\s+", " ", (s or "").strip())

    uploaded_arabic = []
    duas_db = []
    _db_path = os.path.join(PROJECT, "data", "duas.json")
    if os.path.exists(_db_path):
        try:
            _raw = json.load(open(_db_path, encoding="utf-8"))
            duas_db = _raw if isinstance(_raw, list) else _raw.get("duas", [])
        except Exception:
            duas_db = []
    uploaded_ids = {u for u, st in ledger.items() if st.get("status") == "uploaded"}
    for _d in duas_db:
        if _d.get("id") in uploaded_ids:
            _a = _normalize_ar(_strip_diacritics(_d.get("arabic")))
            if _a:
                uploaded_arabic.append(_a)

    def _uploaded_dup(dua_id):
        # candidate Arabic from duas.json (manifest may already be cleaned up)
        cand = next((x for x in duas_db if x.get("id") == dua_id), None)
        if not cand:
            return None
        a = _normalize_ar(_strip_diacritics(cand.get("arabic")))
        if not a:
            return None
        for ua in uploaded_arabic:
            if a == ua:
                return "content duplicate (same Arabic as an already-uploaded dua)"
            if difflib.SequenceMatcher(None, a, ua).ratio() >= 0.90:
                return "content duplicate (~90%+ same Arabic as an already-uploaded dua)"
        return None

    ready, skipped, failed_parse = [], [], []
    for dua_id in ids:
        if dua_id in locks:
            skipped.append((dua_id, "LOCKED (permanent): " + locks[dua_id].get("reason", "")))
            continue
        refn = manifest_reference(dua_id)
        if refn and refn in locked_refs:
            skipped.append((dua_id, "REF-GUARD: same hadith reference as LOCKED " + locked_refs[refn]))
            continue
        if dua_id in arch and dua_id not in only_set:
            skipped.append((dua_id, "archived entry"))
            continue
        if ledger.get(dua_id, {}).get("status") == "uploaded":
            skipped.append((dua_id, "already uploaded (ledger)"))
            continue
        dup_reason = _uploaded_dup(dua_id)
        if dup_reason:
            skipped.append((dua_id, dup_reason))
            continue
        item, reasons = resolve_item(dua_id)
        if item is None or any("no video" in r or "no thumb" in r or ">2MB" in r for r in reasons):
            failed_parse.append((dua_id, "; ".join(reasons)))
        else:
            ready.append((item, reasons))

    if auto_mode:
        # Oldest rendered first (mp4 mtime), hard-capped by N AND quota.
        ready.sort(key=lambda it: os.path.getmtime(it[0]["mp4"]))
        cap = max(min(args.auto, remaining_today), 0)
        dropped = ready[cap:]
        ready = ready[:cap]
        for d_item, _dw in dropped:
            skipped.append((d_item["dua_id"], "auto: deferred (N/quota cap)"))
        print(
            f"AUTO-PICK         : {len(ready)} oldest-first of {len(ready) + len(dropped)} eligible "
            f"({len(dropped)} deferred by N/quota)"
        )
        for sid, why in skipped[:5]:
            auto_log(auto_runs_path, f"SKIP {sid} :: {why}")
        if len(skipped) > 5:
            auto_log(auto_runs_path, f"SKIP ... +{len(skipped) - 5} more (see console)")

    plan_units = min(len(ready), max(remaining_today, 0)) * UPLOAD_UNITS
    print(f"library manifests : {len(ids)}")
    print(f"channel token     : {token_label}")
    print(f"ledger            : {ledger_path}")
    print(f"quota log         : {qpath} ({qunits} units today = {quploads} uploads)")
    print(f"READY             : {len(ready)}")
    print(f"skipped           : {len(skipped)} (archived/done)")
    print(f"not-ready         : {len(failed_parse)}")
    print(
        f"quota             : {eff_used}/{DAILY_CEILING} uploads used today (ledger:{used_today}, quota-log:{quploads}); "
        f"this run plans {plan_units} units ({min(len(ready), max(remaining_today, 0))} x {UPLOAD_UNITS})"
    )
    for sid, why in skipped[:6]:
        print(f"  skip  {sid}: {why}")
    for fid, why in failed_parse[:6]:
        print(f"  nrdy  {fid}: {why}")

    mode = "LIVE" if args.live else "DRY-RUN"
    print(f"\n=== {mode.upper()} MODE | privacy={args.privacy} ===")
    if args.limit > 0:
        ready = ready[: args.limit]

    ok_n = fail_n = 0
    stop_cancel = False
    service = None
    if args.live:
        service = get_youtube_service(args.token)
        if not service:
            print("cannot start live mode without auth")
            return 1

    t0 = time.time()
    audit_entries = []
    for i, (item, warnings) in enumerate(ready, 1):
        if os.path.exists(cancel_flag):
            print(
                f"[{i}/{len(ready)}] CANCEL requested - stopping gracefully "
                "(current video ke baad koi naya upload nahi)"
            )
            if auto_mode:
                auto_log(auto_runs_path, f"CANCELLED by user at {i}/{len(ready)}")
            stop_cancel = True
            break
        if (
            max(uploads_today(load_ledger(ledger_path)), units_today(load_quota(qpath)) // UPLOAD_UNITS)
            >= DAILY_CEILING
        ):
            print(f"[{i}/{len(ready)}] QUOTA CEILING reached - stopping safely")
            if auto_mode:
                auto_log(auto_runs_path, f"QUOTA CEILING stop at {i}/{len(ready)}")
            break
        payload = build_payload(item, args.privacy, args.category_id)
        tags_len = len(", ".join(payload["snippet"]["tags"]))
        print(
            "[{}/{}] {} | '{}' | {}KB thumb | tags:{}ch{}".format(
                i,
                len(ready),
                item["dua_id"],
                payload["snippet"]["title"][:48],
                os.path.getsize(item["thumb"]) // 1024,
                tags_len,
                "  warn: " + "; ".join(warnings) if warnings else "",
            )
        )
        if args.live:
            try:
                vid = do_live_upload(service, item, payload)
                ledger[item["dua_id"]] = {
                    "status": "uploaded",
                    "video_id": vid,
                    "privacy": args.privacy,
                    "locked": True,
                    "units_spent": UPLOAD_UNITS,
                    "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                save_ledger(ledger, ledger_path)
                spent = record_units(qpath, UPLOAD_UNITS)
                print(f"  quota-log: {spent} units today")
                ok_n += 1
                print("  UPLOADED https://youtu.be/" + vid)
                try:
                    mp4_path = item.get("mp4")
                    if mp4_path and os.path.exists(mp4_path):
                        os.remove(mp4_path)
                        print("  CLEANUP removed MP4:", os.path.basename(mp4_path))
                    sidecar_path = os.path.splitext(mp4_path)[0] + ".txt" if mp4_path else None
                    if sidecar_path and os.path.exists(sidecar_path):
                        os.remove(sidecar_path)
                        print("  CLEANUP removed sidecar:", os.path.basename(sidecar_path))
                    full_cleanup_after_upload(item["dua_id"], item["meta"].get("title") or "")
                except OSError as ce:
                    print("  WARN cleanup failed:", str(ce)[:120])
                if auto_mode:
                    auto_log(
                        auto_runs_path,
                        "UPLOADED {} -> https://youtu.be/{} (privacy={})".format(item["dua_id"], vid, args.privacy),
                    )
                time.sleep(2)
            except Exception as e:
                fail_n += 1
                print("  FAIL:", str(e)[:250])
                if auto_mode:
                    auto_log(auto_runs_path, "FAILED {} :: {}".format(item["dua_id"], str(e)[:200]))
        else:
            ok_n += 1
        audit_entries.append(
            {
                "dua_id": item["dua_id"],
                "title": item["meta"]["title"],
                "tags": item["meta"]["tags"],
                "description": item["meta"]["description"],
                "reference": item.get("reference", ""),
            }
        )

    if audit_entries:
        dups, n_hashes = uniqueness_audit(audit_entries)
        n = len(audit_entries)
        print(f"\n=== UNIQUENESS AUDIT ({mode}) ===")
        print(
            "titles       : {} ({}/{})".format(
                "UNIQUE" if not dups["title"] else "DUPLICATES", n - len(dups["title"]), n
            )
        )
        print(
            "tag-sets     : {} ({}/{})".format("UNIQUE" if not dups["tags"] else "DUPLICATES", n - len(dups["tags"]), n)
        )
        print(
            "descriptions : {} ({}/{}, body sans disclaimer)".format(
                "UNIQUE" if not dups["desc"] else "DUPLICATES", n - len(dups["desc"]), n
            )
        )
        print(f"title hashes : {n_hashes}/{n} distinct (sha1[:8])")
        ref_groups = {}
        for e in audit_entries:
            rn = norm_ref(e.get("reference"))
            if rn:
                ref_groups.setdefault(rn, []).append(e["dua_id"])
        shared = {k: v for k, v in ref_groups.items() if len(v) > 1}
        print(f"references   : {len(shared)} shared-ref group(s)")
        for rk, members in sorted(shared.items()):
            print("  REF-SHARED [{}]: {}".format(rk.title()[:40], ", ".join(members)))
        for key, pairs in dups.items():
            for a, b in pairs:
                print(f"  DUP[{key}]: {a} == {b}")
        clean = not any(dups.values()) and n_hashes == n
        print("RESULT: {}".format("PASS" if clean else "WARN"))

    if os.path.exists(cancel_flag):
        with contextlib.suppress(OSError):
            os.remove(cancel_flag)

    print(
        "\n=== SUMMARY ({}) {:.1f}s | ok:{} fail:{}{} | ledger:{} ===".format(
            mode, time.time() - t0, ok_n, fail_n, " | CANCELLED" if stop_cancel else "", ledger_path
        )
    )
    if auto_mode:
        auto_log(
            auto_runs_path,
            "RUN end {}: ok={} fail={} picked={} elapsed={:.1f}s{}".format(
                mode, ok_n, fail_n, len(ready), time.time() - t0, " | CANCELLED" if stop_cancel else ""
            ),
        )
    return 1 if fail_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
