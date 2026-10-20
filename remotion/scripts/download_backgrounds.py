"""Download HD portrait background images + videos from Pexels (free, monetization-safe)
for each dua category, save them locally, and register them in the asset manifest.

Usage:
    python scripts/download_backgrounds.py            # images only (Option A/B)
    python scripts/download_backgrounds.py --videos   # images + videos (Option C)
    python scripts/download_backgrounds.py --category prayer  # single category

Requires PEXELS_KEY env var or --key argument.
"""

import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

PEXELS_IMAGES = "https://api.pexels.com/v1/search"
PEXELS_VIDEOS = "https://api.pexels.com/videos/search"
PEXELS_PAGE = 1
PEXELS_PER_PAGE = 80  # Pexels soft max per_page

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# location: <root>/remotion/scripts/<file> -> root is 3 dirname up. But we want
# the project ROOT (H:\DuaVideoGenerator), which is 3 up from this script.
# __file__ = <root>/remotion/scripts/download_backgrounds.py
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BG_DIR = os.path.join(ROOT, "assets", "backgrounds")
IMG_DIR = os.path.join(BG_DIR, "images")
VID_DIR = os.path.join(BG_DIR, "videos")
MANIFEST_PATH = os.path.join(BG_DIR, "manifest.json")

# Category -> Pexels search terms (mosque / nature / thematic)
CATEGORY_QUERIES = {
    "prayer": "mosque prayer islam",
    "morning": "sunrise morning sky nature",
    "evening": "sunset evening sky clouds",
    "sleep": "night sky stars moon",
    "food": "halal food dining table meal",
    "travel": "mountain travel landscape road",
    "bathroom": "water drops clean blue",
    "protection": "hands dua prayer muslim",
    "forgiveness": "clouds sky light rays",
    "guidance": "quran islamic book lamp",
    "rizzq": "nature green wheat field",
    "health": "green nature wellness leaves",
    "family": "family silhouette sunset",
    "gratitude": "sunrise light nature serene",
    "occasions": "eid lantern mosque ornament",
    "anxiety_relief": "calm ocean sea waves",
    "general": "abstract dark texture elegant",
}
CATEGORY_VIDEO_QUERIES = {
    "prayer": "mosque islam",
    "morning": "sunrise sky",
    "evening": "sunset sky clouds",
    "sleep": "night stars moon",
    "food": "food cooking kitchen meal",
    "travel": "mountain landscape",
    "bathroom": "water drops blue",
    "protection": "hands prayer",
    "forgiveness": "clouds sky light",
    "guidance": "quran book islamic",
    "rizzq": "green field wheat",
    "health": "nature leaves wellness",
    "family": "family silhouette",
    "gratitude": "sunrise light serene",
    "occasions": "mosque eid lantern",
    "anxiety_relief": "ocean sea waves calm",
    "general": "abstract dark texture",
}
LICENSE = "Pexels License"  # monetization-safe, no attribution required


def http_request(url, headers=None):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DuaVideoGenerator/1.0",
            **(headers or {}),
        },
    )
    return urllib.request.urlopen(req, timeout=30)


def download(path, url, retries=2):
    for attempt in range(retries + 1):
        try:
            data = http_request(url).read()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            if len(data) < 1000:
                raise ValueError("too small download (likely error)")
            return path
        except Exception:
            if attempt >= retries:
                raise
            time.sleep(2)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(assets):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "schema_version": 1,
                "description": "Pexels background assets (images + optional videos) "
                "auto-registered by download_backgrounds.py. "
                "Pexels License, monetization-safe.",
                "assets": assets,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"[manifest] wrote {len(assets)} assets -> {MANIFEST_PATH}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("PEXELS_KEY", ""))
    ap.add_argument("--videos", action="store_true", help="also download moving video backgrounds (Option C)")
    ap.add_argument("--category", default="all")
    ap.add_argument("--per-category", type=int, default=32, help="number of images per category (default 32)")
    ap.add_argument("--videos-per-category", type=int, default=8, help="number of videos per category (default 8)")
    args = ap.parse_args()

    if not args.key:
        print("ERR: no Pexels key. set PEXELS_KEY or pass --key")
        return 1

    queries = CATEGORY_QUERIES
    categories = list(queries.keys()) if args.category == "all" else [args.category]

    existing = {}
    if os.path.exists(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, encoding="utf-8") as fh:
                existing = {a["id"]: a for a in json.load(fh).get("assets", [])}
        except Exception:
            existing = {}

    new_assets = list(existing.values())
    existing_ids = set(existing.keys())
    added = 0

    for cat in categories:
        query = queries.get(cat, "nature")
        print(f"\n=== category: {cat} (query: {query}) ===")
        page = 1
        got_new = 0
        while got_new < args.per_category:
            url = (
                f"{PEXELS_IMAGES}?query={urllib.parse.quote(query)}"
                f"&orientation=portrait&per_page={PEXELS_PER_PAGE}&page={page}"
            )
            try:
                resp = json.loads(http_request(url, {"Authorization": args.key}).read().decode("utf-8"))
            except Exception as e:
                print(f"  ! search failed {cat} page {page}: {e}")
                break
            photos = resp.get("photos", [])
            print(f"  page {page}: {len(photos)} portrait photos (total results {resp.get('total_results', '?')})")
            if not photos:
                break

            for _i, ph in enumerate(photos):
                if got_new >= args.per_category:
                    break
                ph_id = ph.get("id")
                asset_id = f"pix_{cat}_{ph_id}"
                if asset_id in existing_ids:
                    continue
                # prefer portrait large2x (up to ~4x) -> crop as needed; webformat is safe too
                url_large = (
                    ph.get("src", {}).get("portrait")
                    or ph.get("src", {}).get("large2x")
                    or ph.get("src", {}).get("large")
                    or ph.get("src", {}).get("original")
                ) or ""
                if not url_large:
                    continue
                fname = f"{cat}_{ph_id}.jpg"
                path = os.path.join(IMG_DIR, fname)
                try:
                    download(path, url_large)
                except Exception as e:
                    print(f"  ! dl fail {fname}: {e}")
                    continue
                new_assets.append(
                    {
                        "id": asset_id,
                        "file": os.path.join("images", fname),
                        "categories": [cat],
                        "license": LICENSE,
                        "checksum_sha256": sha256(path),
                        "approved": True,
                        "resolution_width": ph.get("width", 0),
                        "resolution_height": ph.get("height", 0),
                        "source_url": ph.get("url", ""),
                        "author": (ph.get("photographer") or ""),
                        "notes": "downloaded by download_backgrounds.py",
                    }
                )
                existing_ids.add(asset_id)
                got_new += 1
                added += 1
                print(f"  + {fname} ({ph.get('width')}x{ph.get('height')})")

            # Pexels caps at 80 results per query via paging; stop when done
            page += 1
            if page > 40:
                break
            time.sleep(0.3)

        # videos (Option C)
        if args.videos:
            vquery = CATEGORY_VIDEO_QUERIES.get(cat, "nature")
            vpage = 1
            vgot = 0
            while vgot < args.videos_per_category:
                vurl = (
                    f"{PEXELS_VIDEOS}?query={urllib.parse.quote(vquery)}"
                    f"&orientation=portrait&per_page={PEXELS_PER_PAGE}&page={vpage}"
                )
                try:
                    vresp = json.loads(http_request(vurl, {"Authorization": args.key}).read().decode("utf-8"))
                except Exception as e:
                    print(f"  ! video search failed {cat} page {vpage}: {e}")
                    vresp = {}
                vids = vresp.get("videos", [])
                if not vids:
                    break
                for _vi, vid in enumerate(vids):
                    if vgot >= args.videos_per_category:
                        break
                    # pick the smallest file that is >= 720 height (keep size sane)
                    vfiles = vid.get("video_files", [])
                    vfiles = [f for f in vfiles if f.get("height", 0) >= 720 and f.get("link")]
                    vfiles.sort(key=lambda f: (f["width"] * f["height"]))
                    if not vfiles:
                        continue
                    vfile = vfiles[0]
                    asset_id = f"vid_{cat}_{vid.get('id')}"
                    if asset_id in existing_ids:
                        continue
                    url_v = vfile["link"]
                    fname = f"{cat}_{vid.get('id')}.mp4"
                    path = os.path.join(VID_DIR, fname)
                    try:
                        download(path, url_v)
                    except Exception as e:
                        print(f"  ! video dl fail {fname}: {e}")
                        continue
                    new_assets.append(
                        {
                            "id": asset_id,
                            "file": os.path.join("videos", fname),
                            "categories": [cat],
                            "license": LICENSE,
                            "checksum_sha256": sha256(path),
                            "approved": True,
                            "resolution_width": vfile.get("width", 0),
                            "resolution_height": vfile.get("height", 0),
                            "source_url": vid.get("url", ""),
                            "author": (vid.get("user", {}).get("name", "") or ""),
                            "notes": "video background by download_backgrounds.py",
                        }
                    )
                    existing_ids.add(asset_id)
                    vgot += 1
                    added += 1
                    print(f"  + VIDEO {fname} ({vfile.get('width')}x{vfile.get('height')})")
                    time.sleep(0.5)
                vpage += 1
                if vpage > 40:
                    break
                time.sleep(0.3)

        time.sleep(0.5)

    if new_assets:
        build_manifest(new_assets)
    print(f"\nDONE: added {added} new assets (total in manifest: {len(new_assets)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
