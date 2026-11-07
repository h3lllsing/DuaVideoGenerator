# Architecture — Dua Video Generator

> Verified findings from architecture review (2026-10-18, read-only) + post-audit state (2026-10-20+).

## Layered Design (verified)

```
main.py (CLI orchestrator, 1121 lines) -> core/*.py (engine)
core/master_config.py (833 lines, pack/VFX semantics) ; core/master_config imports
core.config (project constants)  -> TWO config layers noted (F-22 RESOLVED via project_info sync)

remotion/ (React/Remotion: Background, DuaVideo, themes, FX; scripts/ Python helpers:
  render, upload, TTS, stats, ai_import, youtube_sync; dashboard/ Node server on 7860)
apps/server/ (Node/TypeScript API on 7871, src/routes: upload.ts)
frontend/wife_app.py (customtkinter offline GUI, no auth)

tests/ -> core/master_config / core modules (pytest; 3 UIs by design)
```

## Verified Import Graph

- No import cycles found (DFS, current code): layering clean
  (`main -> core -> config`; `frontend -> core`; `tests -> core/master_config & scripts`).
- `mega_pack -> main` was a FALSE POSITIVE: mega_pack imports only `core.master_config`.
- Layers preserved; F-22 (config split-brain) RESOLVED 2026-10-20 via `project_info.py` sync
  (`PROJECT.FPS` etc. propagate from root `config.py`).

## Video Data Flow (per dua)

```
data/duas.json -> core (asset_registry, tts_engine, audio_mixer, effect_director,
                  scene_engine, timeline_builder, word_highlight, master_config)
            -> remotion composition (1080x1920, FPS 30, dark template, duration 15)
            -> ffmpeg master audio (loudnorm -14 LUFS) -> render -> upload -> stats
```

- TTS: edge-tts neural voices (`ar-SA-HamedNeural`, `ur-PK-AsadNeural`).
- Word highlight: sidecar word-timings (frame-accurate karaoke).
- Backgrounds: procedural + optional Pexels-generated per category.

## Key Risks / Notes

- F-24: `main.py` god-CLI (1121 lines, ~9% coverage on main) — maintainability risk.
- F-22 resolved; F-19/F-20/F-21 CI-quality risks tracked (mypy numpy-stubs vs py3.11, ruff format repo-wide, npm audit).
