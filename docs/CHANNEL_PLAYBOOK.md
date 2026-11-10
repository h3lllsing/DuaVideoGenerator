# Channel Playbook — Noor-e-Iman

## Channel

- **Name:** Noor-e-Iman
- **Content type:** Islamic dua YouTube Shorts (Arabic + Urdu, TTS, karaoke visuals).

## Content Engine (verified catalog scale)

- Catalog grew **169 → 204 → 226 → 258** duas via batched authentic additions
  (Bukhari/Muslim/Tirmidhi/Abu Dawud/Ibn Majah/Nasai + Quran ayahs).
- Current partition: `{quran: 82, hadith: 165, other: 11}` of **258** (verified).

## Strategy Levers

1. **Content pillars** — prayer (istiftah, takmeel, sajda), sleep/risks, food/iftar, protection (shayateen, dushman, zalim basti), forgiveness, health (dard, aafiyat), patience, family, occasions (hajj/talbiyah, janazah), gratitude, guidance, anxiety relief, general/dua.

2. **Policy risk** — repetitive/mass-produced content within one template; duplicate-content + AI-metadata risk. Mitigation: unique dua per card, verified Arabic, varied backgrounds/categories, narration distinct.

3. **Monetization eligibility** — current posture: videos are dua + TTS + branding; eligibility depends on YouTube policy compliance + watch time; needs fresh YouTube Analytics data (views/retention) — source currently not resolving via portal post-YouTube-connect (Noor-e-Iman).

4. **Growth/retention levers** — karaoke word highlighting, phase-change reveal, backgrounds per category, ending CTA/intro cards; TTS loudness-normalized (-14 LUFS), frame-accurate highlights.

## Open Channel Items

- YouTube views/likes details not appearing on portal after YouTube connect (user-reported) — needs re-auth/re-check (OAuth token state).
- RESOLVED (2026-11-08): analytics reconnect — token status check + `youtube_stats.py --channel channel1` run -> **auth failed - re-login needed**; `youtube_auth.py login` kicked off (OAuth re-auth in progress).
- RESOLVED-PHASE2 (2026-11-10): root cause = `youtube_stats.py` me `--token` relative path (remotion cwd) -> `os.path.abspath` ke zaro ab PROJECT-relative resolve -> re-run -> **ok:true** (Noor-e-Iman: subs 80, views 10311, videos 209; video 9cZqb-6EUXw: views 15, likes 3). OAuth re-login ki zaroorat NAHI thi; token valid tha.
- External alert channel token absent (F-28) — channel health alerts pending.
