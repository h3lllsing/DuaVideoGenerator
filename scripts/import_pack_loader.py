"""PILLAR 1 · Import-pack loader & validation gate for data/duas.json.

Pipeline readiness tool (audit area 3):
  1. Loads staged packs (default: import_pack_v1/v2/v3.json).
  2. Validates each candidate entry:
       - unique slug id (generated from title when absent)
       - category inside taxonomy v2 + legacy whitelist
       - Urdu translation <= 75 words (hard) / > 60 words (warn)
       - Arabic harakat sanity (diacritics expected on real Quranic text)
       - duplicate guard vs current DB by id AND by normalized arabic
  3. Optional remap of legacy 'general' entries onto taxonomy v2.
  4. Merges valid entries into duas.json (auto-backup) and refreshes
     categories.json counts.

Dry-run by default; pass --apply to write. Exit code 0 = nothing blocking,
exit 2 = at least one entry hard-rejected (report still printed).
"""

import json
import os
import re
import shutil
import sys

PROJECT = r"H:\DuaVideoGenerator"
sys.path.append(PROJECT)

DATA_DIR = os.path.join(PROJECT, "data")
DUAS_FILE = os.path.join(DATA_DIR, "duas.json")
CATS_FILE = os.path.join(DATA_DIR, "categories.json")

TAXONOMY_V2 = (
    "protection",
    "rizq",
    "forgiveness",
    "morning_evening",
    "guidance",
    "health",
    "anxiety_relief",
    "gratitude",
    "family",
    "occasions",
)
LEGACY_CATEGORIES = (
    "bathroom",
    "sleep",
    "food",
    "travel",
    "prayer",
    "morning",
    "evening",
    "general",
)
VALID_CATEGORIES = set(TAXONOMY_V2) | set(LEGACY_CATEGORIES)

URDU_WARN_WORDS = 60
URDU_HARD_WORDS = 75

# theme derivation mirrors make_manifest.CATEGORY_THEME; legacy rows kept
# byte-compatible so existing manifests rebuild identically.
CATEGORY_THEME = {
    "sleep": "mosque",
    "evening": "mosque",
    "morning": "sunset",
    "travel": "sunset",
    "food": "emerald",
    "bathroom": "emerald",
    "prayer": "manuscript",
    # taxonomy v2 aliases (new ids -> theme)
    "protection": "dark",
    "rizq": "emerald",
    "forgiveness": "manuscript",
    "morning_evening": "sunset",
    "guidance": "manuscript",
    "health": "ocean",
    "anxiety_relief": "ocean",
    "gratitude": "eid",
    "family": "royal",
    "occasions": "ramadan",
}
VALID_THEMES = (
    "dark",
    "mosque",
    "sunset",
    "manuscript",
    "emerald",
    "ocean",
    "desert",
    "royal",
    "ramadan",
    "eid",
    "qadr",
)

NEW_CATEGORY_META = {
    "protection": {
        "name": "Protection & Refuge",
        "name_urdu": "\u062d\u0641\u0627\u0638\u062a \u06a9\u06cc \u062f\u0639\u0627\u0626\u06cc\u06ba",
        "description": "Duas for refuge from evil, enemies, nazar and harm",
        "icon": "\U0001f6e1\ufe0f",
        "color": "#5B8DEF",
    },
    "rizq": {
        "name": "Rizq & Abundance",
        "name_urdu": "\u0631\u0632\u0642 \u0627\u0648\u0631 \u0628\u0631\u06a9\u062a",
        "description": "Sustenance, debt relief and barakah supplications",
        "icon": "\U0001f33e",
        "color": "#D4A017",
    },
    "forgiveness": {
        "name": "Forgiveness & Tawbah",
        "name_urdu": "\u0645\u063a\u0641\u0631\u062a \u0627\u0648\u0631 \u062a\u0648\u0628\u06c1",
        "description": "Istighfar and maghfirat supplications",
        "icon": "\U0001f49a",
        "color": "#6FCF97",
    },
    "morning_evening": {
        "name": "Morning & Evening Adhkar",
        "name_urdu": "\u0635\u0628\u062d \u0648 \u0634\u0627\u0645 \u06a9\u06d2 \u0627\u0630\u06a9\u0627\u0631",
        "description": "Combined subah-o-shaam protection adhkar",
        "icon": "\U0001f304",
        "color": "#E07A5F",
    },
    "guidance": {
        "name": "Guidance & Wisdom",
        "name_urdu": "\u06c1\u062f\u0627\u06cc\u062a \u0627\u0648\u0631 \u0639\u0644\u0645",
        "description": "Hidayah, knowledge and steadfastness duas",
        "icon": "\U0001f9ed",
        "color": "#9B5DE5",
    },
    "health": {
        "name": "Health & Healing",
        "name_urdu": "\u0635\u062d\u062a \u0627\u0648\u0631 \u0634\u0641\u0627",
        "description": "Shifa and relief-from-illness supplications",
        "icon": "\U0001fa7a",
        "color": "#2EC4B6",
    },
    "anxiety_relief": {
        "name": "Anxiety & Relief",
        "name_urdu": "\u067e\u0631\u06cc\u0634\u0627\u0646\u06cc \u0633\u06d2 \u0646\u062c\u0627\u062a",
        "description": "Duas against worry, grief and distress",
        "icon": "\U0001f54a\ufe0f",
        "color": "#118AB2",
    },
    "gratitude": {
        "name": "Gratitude & Dhikr",
        "name_urdu": "\u0634\u06a9\u0631 \u0648 \u0630\u06a9\u0631",
        "description": "Shukar and daily zikr supplications",
        "icon": "\U0001f64f",
        "color": "#F4A261",
    },
    "family": {
        "name": "Family & Children",
        "name_urdu": "\u062e\u0627\u0646\u062f\u0627\u0646 \u0627\u0648\u0631 \u0627\u0648\u0644\u0627\u062f",
        "description": "Spouse, parents and children supplications",
        "icon": "\U0001f468\u200d\U0001f469\u200d\U0001f467",
        "color": "#E76F51",
    },
    "occasions": {
        "name": "Occasions & Sunnah Moments",
        "name_urdu": "\u0645\u0648\u0627\u0642\u0639 \u06a9\u06cc \u062f\u0639\u0627\u0626\u06cc\u06ba",
        "description": "Rain, moon, grave, Hajj, Ramadan and life events",
        "icon": "\U0001f389",
        "color": "#C77DBA",
    },
}

# PILLAR 1 · deterministic remap of the 38 legacy 'general' entries.
GENERAL_REMAP = {
    # guidance (7)
    "rabbana_hasanah": "guidance",
    "rabbi_shrah": "guidance",
    "rabbi_zidni": "guidance",
    "rabbana_latuzigh": "guidance",
    "surah_asr": "guidance",
    "surah_feel": "guidance",
    "surah_quraysh": "guidance",
    # forgiveness (3)
    "rabbi_ghfir": "forgiveness",
    "jahannam_se_azadi_aur_maghfirat_ki_dua": "forgiveness",
    "chhoti_istighfar": "forgiveness",
    # anxiety_relief (4)
    "ham_o_gham": "anxiety_relief",
    "karz_aur_pareshani_se_nijat_ki_dua": "anxiety_relief",
    "susti_aur_pareshani_se_panah": "anxiety_relief",
    "yunus_dua": "anxiety_relief",
    # protection (6)
    "hasbunallah": "protection",
    "gusse_me_panah_ki_dua": "protection",
    "dushman_se_hifazat": "protection",
    "nazar_e_bad_se_hifazat": "protection",
    "waswase_se_panah": "protection",
    "bijli_aur_toofan_ki_dua": "protection",
    # gratitude (1)
    "shukar_aur_zikr_ki_madad": "gratitude",
    # family (3)
    "aulad_ki_hifazat_ki_dua": "family",
    "aulad_ke_liye_dua": "family",
    "miyan_biwi_aur_aulad_ki_bhalai": "family",
    # health (2)
    "ayyub_as_ki_bimarion_aur_takaleef_se_shifa_ki_dua": "health",
    "dard_me_shifa_ki_dua": "health",
    # rizq (1)
    "rizq_aur_ilm_ki_barkat": "rizq",
    # occasions (11)
    "home_enter": "occasions",
    "naye_kapde_pehanne_ki_dua": "occasions",
    "aaine_me_dekhne_ki_dua": "occasions",
    "qabristan_ki_dua": "occasions",
    "barish_ki_dua": "occasions",
    "naya_chand_dekhne_ki_dua": "occasions",
    "cheenk_ki_sunnat_jawab": "occasions",
    "takbeer_e_tashreeq": "occasions",
    "main_roza_daar_hoon": "occasions",
    "arafa_ke_din_ki_dua": "occasions",
    "qadr_ki_raat_ki_dua": "occasions",
}

_DIACRITICS = re.compile(r"[\u064b-\u0652\u0670]")


def slugify(text):
    s = str(text).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def norm_arabic(s):
    stripped = _DIACRITICS.sub("", s)
    stripped = stripped.replace("\u0640", "")
    return re.sub(r"\s+", " ", stripped).strip()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_db():
    raw = load_json(DUAS_FILE)
    return (raw["duas"] if isinstance(raw, dict) and "duas" in raw else raw), (isinstance(raw, dict))


def validate_entry(e, idx, taken_ids, taken_arabic):
    issues, warns = [], []
    title = str(e.get("title") or e.get("title_en") or "").strip()
    arabic = str(e.get("arabic") or "").strip()
    urdu = str(e.get("urdu") or "").strip()
    reference = str(e.get("reference") or "").strip()

    if not title or not arabic or not urdu:
        issues.append(f"missing core field(s) title/arabic/urdu @row{idx}")

    uid = slugify(e.get("id") or title or f"dua_{idx}")
    if not uid:
        issues.append(f"unsluggable id @row{idx}")
    elif uid in taken_ids:
        issues.append(f"duplicate id '{uid}' (already in DB/batch)")

    nar = norm_arabic(arabic)
    if nar and nar in taken_arabic:
        issues.append(f"duplicate arabic content @row{idx} ({title[:32]})")

    cat = str(e.get("category") or "general").strip()
    if cat not in VALID_CATEGORIES:
        issues.append(f"invalid category '{cat}' @row{idx}")

    uw = len(urdu.split()) if urdu else 0
    if uw > URDU_HARD_WORDS:
        issues.append(f"urdu {uw} words > {URDU_HARD_WORDS} cap @row{idx}")
    elif uw > URDU_WARN_WORDS:
        warns.append(f"urdu {uw} words (> {URDU_WARN_WORDS} comfort) {uid}")

    if arabic and len(nar) > 15 and not _DIACRITICS.search(arabic):
        issues.append(f"missing harakat on long arabic @row{idx} ({title[:32]})")

    if not reference:
        warns.append(f'empty reference -> fallback "Custom" {uid}')
    return uid, issues, warns


# STYLE-ROTATION v2 (2026-08-23): mirrors make_manifest.CATEGORY_ROTATIONS
CATEGORY_ROTATIONS = {
    "protection": ("desert", "qadr"),
    "guidance": ("royal", "manuscript"),
    "gratitude": ("eid", "emerald"),
    "health": ("ocean", "emerald"),
}
GENERAL_ROTATION = ("manuscript", "dark", "royal", "emerald")


def _seed_pick(seq, seed):
    return seq[sum(map(ord, str(seed))) % len(seq)]


def build_entry(e, uid):
    template = str(e.get("template") or "").strip().lower()
    # Non-dark explicit choice wins; dark stamps = legacy default -> rotation.
    if template in VALID_THEMES and template != "dark":
        pass
    else:
        cat = str(e.get("category") or "general")
        if cat == "general":
            template = _seed_pick(GENERAL_ROTATION, uid)
        elif cat in CATEGORY_ROTATIONS:
            template = _seed_pick(CATEGORY_ROTATIONS[cat], uid)
        else:
            template = CATEGORY_THEME.get(cat, "dark")
    return {
        "id": uid,
        "category": str(e.get("category") or "general").strip(),
        "title": str(e.get("title") or "").strip(),
        "title_en": str(e.get("title_en") or "").strip(),
        "arabic": str(e.get("arabic") or "").strip(),
        "urdu": str(e.get("urdu") or "").strip(),
        "transliteration": str(e.get("transliteration") or "").strip(),
        "explanation": str(e.get("explanation") or "").strip(),
        "reference": str(e.get("reference") or "Custom").strip() or "Custom",
        "voice_arabic": str(e.get("voice_arabic") or "ar-SA-HamedNeural"),
        "voice_urdu": str(e.get("voice_urdu") or "ur-PK-AsadNeural"),
        "template": template,
        "duration": int(e.get("duration") or 15),
        "bismillah": e.get("bismillah", True),
    }


def refresh_categories(duas):
    cats_raw = load_json(CATS_FILE)
    cats = cats_raw["categories"] if isinstance(cats_raw, dict) else cats_raw
    by_id = {c.get("id"): c for c in cats}
    for cid, meta in NEW_CATEGORY_META.items():
        if cid not in by_id:
            entry = {"id": cid, "dua_count": 0}
            entry.update(meta)
            cats.append(entry)
            by_id[cid] = entry
    counts = {}
    for d in duas:
        counts[d.get("category")] = counts.get(d.get("category"), 0) + 1
    for c in cats:
        c["dua_count"] = counts.get(c.get("id"), 0)
    out = {
        "categories": sorted(cats, key=lambda c: c["id"]),
        "total_duas": len(duas),
        "total_categories": len(cats),
    }
    return out


def main():
    argv = sys.argv[1:]
    apply = "--apply" in argv
    remap = "--remap-general" in argv
    packs = [a.split("=", 1)[1] for a in argv if a.startswith("--packs=")]
    packs = packs or ["v1", "v2", "v3"]

    duas, nested = load_db()
    print(f"[db] {len(duas)} duas loaded")

    # ---- optional remap of legacy 'general' ------------------------------
    remapped = 0
    if remap:
        for d in duas:
            if d.get("category") == "general" and d["id"] in GENERAL_REMAP:
                d["category"] = GENERAL_REMAP[d["id"]]
                remapped += 1
        print(f"[remap] {remapped}/38 general entries moved onto taxonomy v2")

    # ---- validate staged packs ------------------------------------------
    taken_ids = {d.get("id") for d in duas}
    taken_arabic = {norm_arabic(d.get("arabic", "")) for d in duas}
    candidates, rejected, warned, merged = [], [], [], []
    for ver in packs:
        path = os.path.join(DATA_DIR, f"import_pack_{ver}.json")
        if not os.path.exists(path):
            print(f"[pack {ver}] MISSING: {path}")
            continue
        rows = load_json(path)
        rows = rows["duas"] if isinstance(rows, dict) and "duas" in rows else rows
        ok = rej = 0
        for i, e in enumerate(rows, 1):
            uid, issues, warns = validate_entry(e, i, taken_ids, taken_arabic)
            for w in warns:
                warned.append(f"[{ver}] {w}")
            if issues:
                rej += 1
                for msg in issues:
                    rejected.append(f"[{ver}] {msg}")
                continue
            taken_ids.add(uid)
            taken_arabic.add(norm_arabic(str(e.get("arabic") or "")))
            candidates.append(build_entry(e, uid))
            ok += 1
        print(f"[pack {ver}] {len(rows)} rows -> {ok} pass, {rej} reject")

    merged = candidates
    print(f"\n[merge] {len(merged)} new entries would be added (dry-run={not apply})")
    for w in warned[:20]:
        print("  WARN:", w)
    for r in rejected[:20]:
        print("  REJECT:", r)
    if len(rejected) > 20:
        print(f"  ... +{len(rejected) - 20} more rejects")

    if apply:
        backup = DUAS_FILE.replace(".json", ".pre_pillar1.backup.json")
        shutil.copyfile(DUAS_FILE, backup)
        print("[backup]", backup)
        final = duas + merged
        with open(DUAS_FILE, "w", encoding="utf-8") as f:
            json.dump(final if not nested else {"duas": final}, f, ensure_ascii=False, indent=2)
        cats_out = refresh_categories(final)
        with open(CATS_FILE, "w", encoding="utf-8") as f:
            json.dump(cats_out, f, ensure_ascii=False, indent=1)
        print(
            f"[write] duas.json -> {len(final)} duas; "
            f"categories.json -> {cats_out['total_categories']} cats, "
            f"total_duas={cats_out['total_duas']}"
        )
    else:
        print("[dry-run] no files written (pass --apply)")

    return 2 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
