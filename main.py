"""
Dua Video Generator - Main Orchestrator
End-to-end pipeline for generating dua videos
"""

import json
import logging
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from threading import Event, Lock, Thread

import psutil
from moviepy import AudioFileClip

from core.audio_mixer import AudioMixer
from core.dua_database import DB
from core.effect_director import EffectDirector, premium_palette
from core.effects_engine import EffectsEngine as EffectEngine
from core.logging_config import setup_logging
from core.metadata_generator import MetadataGenerator
from core.project_info import PROJECT
from core.quality_checker import QualityChecker
from core.revamp_engine import RevampEngine
from core.scene_engine import SceneRenderer
from core.self_trainer import SelfTrainer
from core.timeline_builder import TimelineBuilder
from core.tts_engine import TTSEngine
from core.video_analyzer import VideoAnalyzer
from core.video_builder import VideoBuilder

logger = logging.getLogger(__name__)

setup_logging()

# ── Temp cleanup on crash/exit ──
import atexit
import contextlib
import signal


def _load_known_dua_ids():
    """Return the set of dua ids so the dashboard cache in temp/ is protected."""
    try:
        db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "duas.json")
        if not os.path.exists(db):
            return set()
        with open(db, encoding="utf-8-sig", errors="replace") as f:
            raw = json.load(f)
        arr = raw if isinstance(raw, list) else raw.get("duas", [])
        return {str(d.get("id") or "") for d in arr if d.get("id")}
    except Exception:
        return set()


def _cleanup_temp():
    """Remove stale temp files from previous crashed runs (older than 1 hour).

    NEVER deletes temp files that belong to a known dua — the Remotion/dashboard
    pipeline reuses those as its audio/timing/look cache and source of truth.
    Only removes leftover clutter that matches no known dua id.
    """
    try:
        temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
        if not os.path.exists(temp_dir):
            return
        now = time.time()
        known = _load_known_dua_ids()
        cleaned = 0
        for f in os.listdir(temp_dir):
            fp = os.path.join(temp_dir, f)
            if not os.path.isfile(fp):
                continue
            base = f.rsplit("_", 1)[0]
            if base in known:
                # belongs to a produced dua -> dashboard cache, DO NOT touch
                continue
            if (now - os.path.getmtime(fp)) > 3600:
                try:
                    os.remove(fp)
                    cleaned += 1
                except OSError:
                    pass
        if cleaned:
            with contextlib.suppress(OSError, ValueError):
                logger.info(
                    f"Cleaned {cleaned} stale temp file(s) from previous run"
                )  # stdout may be closed during atexit
    except (OSError, ValueError):
        pass


atexit.register(_cleanup_temp)


def _signal_cleanup(signum, frame):
    logger.warning(f"Received signal {signum}, cleaning up...")
    _cleanup_temp()
    sys.exit(128 + signum)


signal.signal(signal.SIGINT, _signal_cleanup)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _signal_cleanup)


def dua_video_filename(dua) -> str:
    """
    Compute the output MP4 filename for a dua from its title.
    Keeps the file name readable on PC (title based) and strips
    characters that are invalid in Windows file names.
    """
    title = str(dua.get("title") or "Dua").strip() or "Dua"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", title).strip() or "Dua"
    safe = re.sub(r"\.mp4$", "", safe, flags=re.IGNORECASE).rstrip(". ")
    return f"{safe}.mp4"


class DuaVideoPipeline:
    """
    End-to-end pipeline to generate a Dua video from start to finish.
    """

    def __init__(self):
        """Initialize pipeline components."""
        self.tts = TTSEngine()
        self.effect_engine = EffectEngine()
        self.director = EffectDirector(fps=PROJECT.FPS, canvas=(PROJECT.VIDEO_WIDTH, PROJECT.VIDEO_HEIGHT))
        self.video_builder = VideoBuilder()
        self.revamp_engine = RevampEngine()
        self.quality_checker = QualityChecker()
        self.metadata_generator = MetadataGenerator()
        self.self_trainer = SelfTrainer()
        self.video_analyzer = VideoAnalyzer()
        self.temp_dir = PROJECT.TEMP_DIR
        self.output_dir = PROJECT.OUTPUT_DIR
        self._cancel_requested = False
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # PERFORMANCE FIX: Thread pool for parallel audio processing
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dua_audio")
        self._scene_renderer = SceneRenderer(fps=PROJECT.FPS)

        # BATCH QUEUE: queue-based batch processing system
        self._batch_queue: Queue = Queue()
        self._batch_stop = Event()
        self._batch_worker: Thread | None = None
        self._batch_total = 0
        self._batch_done = 0
        self._batch_failed = 0
        self._batch_results: list[dict] = []
        self._batch_lock = Lock()

        # Verify temp directory is writable
        _test_file = os.path.join(self.temp_dir, ".write_test")
        try:
            with open(_test_file, "w") as f:
                f.write("ok")
            os.remove(_test_file)
        except OSError as e:
            logger.error(f"Temp directory not writable: {self.temp_dir} - {e}")
            raise

    # ── Memory Monitoring & Progress Reporting ──────────────────────

    _MEMORY_WARN_MB = 1024  # warn when RSS exceeds 1 GB

    def _check_memory(self, step_name: str):
        """Log current process RSS; warn if above threshold."""
        try:
            mem_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        except Exception:
            return
        if mem_mb >= self._MEMORY_WARN_MB:
            logger.warning("[MEM] %s — %.0f MB (threshold %d MB)", step_name, mem_mb, self._MEMORY_WARN_MB)
        else:
            logger.info("[MEM] %s — %.0f MB", step_name, mem_mb)

    def _report_progress(self, step: int, total: int, label: str, dua_id: str = "", elapsed: float = 0.0):
        """Emit a one-line progress snapshot."""
        pct = int(step / total * 100) if total else 0
        ts = f" ({elapsed:.0f}s elapsed)" if elapsed else ""
        dua_tag = f" [{dua_id}]" if dua_id else ""
        logger.info(">>> [%d/%d %2d%%] %s%s%s", step, total, pct, label, dua_tag, ts)

    def __del__(self):
        """Cleanup thread pool on object destruction."""
        self.shutdown()

    def shutdown(self):
        """Shutdown thread pool executor, batch worker, and clear caches."""
        self.cancel_batch()
        if hasattr(self, "_executor") and self._executor:
            self._executor.shutdown(wait=False)
        if hasattr(self, "_scene_renderer") and self._scene_renderer:
            self._scene_renderer.clear_cache()
        logger.debug("DuaVideoPipeline resources cleaned up")

    # ── Batch Queue System ──────────────────────────────────────────

    _SENTINEL = None  # poison pill to stop the worker

    def _batch_worker_loop(self):
        """Worker thread: pull (dua_id, kwargs) from queue until sentinel."""
        while True:
            item = self._batch_queue.get()
            if item is self._SENTINEL:
                self._batch_queue.task_done()
                break
            dua_id, kwargs = item
            try:
                ok = self.generate_video(dua_id, **kwargs)
                with self._batch_lock:
                    self._batch_done += 1
                    self._batch_results.append({"dua_id": dua_id, "ok": ok})
                    if not ok:
                        self._batch_failed += 1
            except Exception:
                logger.exception("Batch worker exception for %s", dua_id)
                with self._batch_lock:
                    self._batch_done += 1
                    self._batch_failed += 1
                    self._batch_results.append({"dua_id": dua_id, "ok": False})
            finally:
                self._batch_queue.task_done()

    def add_to_batch(self, dua_id: str, *, theme: str = "dark", effect: str = "auto", dry_run: bool = False):
        """
        Enqueue a single dua for background batch processing.

        The worker thread processes items sequentially (one video at a time)
        so pipeline resources are never shared across concurrent renders.

        Args:
            dua_id: Dua identifier from the database.
            theme: Video theme (default: dark).
            effect: Visual effect (default: auto).
            dry_run: If True, validate only without generating.

        Raises:
            RuntimeError: If the batch worker is not running.
        """
        if self._batch_worker is None or not self._batch_worker.is_alive():
            raise RuntimeError("Batch worker not running. Call start_batch() first.")
        self._batch_queue.put((dua_id, {"theme": theme, "effect": effect, "dry_run": dry_run}))

    def start_batch(
        self, dua_ids: list[str] | None = None, *, theme: str = "dark", effect: str = "auto", dry_run: bool = False
    ):
        """
        Start (or enqueue into an existing) batch run.

        If *dua_ids* is None, all duas from the database are queued.
        A daemon worker thread processes the queue sequentially.

        Args:
            dua_ids: Specific dua IDs to process, or None for all.
            theme: Video theme for every dua.
            effect: Visual effect for every dua.
            dry_run: If True, validate only.
        """
        if self._batch_worker is not None and self._batch_worker.is_alive():
            # Worker already running — just enqueue more items
            pass
        else:
            # Fresh worker
            self._batch_stop.clear()
            with self._batch_lock:
                self._batch_total = 0
                self._batch_done = 0
                self._batch_failed = 0
                self._batch_results = []
            self._batch_worker = Thread(target=self._batch_worker_loop, daemon=True, name="batch_worker")
            self._batch_worker.start()

        if dua_ids is None:
            duas = DB.get_all_duas()
            dua_ids = [d.get("id") for d in duas if d.get("id")]

        with self._batch_lock:
            self._batch_total += len(dua_ids)

        for did in dua_ids:
            self._batch_queue.put((did, {"theme": theme, "effect": effect, "dry_run": dry_run}))

        logger.info("Batch started: %d dua(s) queued.", len(dua_ids))

    def get_batch_status(self) -> dict:
        """
        Return current batch progress.

        Returns:
            dict with keys: total, done, failed, pending, running, results.
        """
        with self._batch_lock:
            total = self._batch_total
            done = self._batch_done
            failed = self._batch_failed
            results = list(self._batch_results)
        running = self._batch_worker is not None and self._batch_worker.is_alive()
        return {
            "total": total,
            "done": done,
            "failed": failed,
            "pending": total - done,
            "running": running,
            "results": results,
        }

    def cancel_batch(self):
        """
        Cancel the batch worker: drain remaining queue items and stop.
        In-progress video will finish; no new videos start after drain.
        """
        self._batch_stop.set()
        # Drain remaining items so the worker doesn't block on get()
        while not self._batch_queue.empty():
            try:
                self._batch_queue.get_nowait()
                self._batch_queue.task_done()
            except Empty:
                break
        # Send sentinel so worker exits its loop
        self._batch_queue.put(self._SENTINEL)
        if self._batch_worker is not None and self._batch_worker.is_alive():
            self._batch_worker.join(timeout=5)
        self._batch_worker = None

    def _prepare_audio_track(self, ar_audio: str, ur_audio: str, merged_audio: str, gap_seconds: float = 0.3):
        """
        Merge spoken audio, apply the VIDEO-002 duration policy (15-25s), and
        pad the audio track with trailing silence to match the final video
        duration so the video builder never trims visual hold time.

        AUDIO-001: downstream audio is lossless 48 kHz WAV; the SPEECH-ONLY
        track is loudness-normalized (two-pass LINEAR loudnorm, -14 LUFS /
        -1.0 dBTP) BEFORE VIDEO-002 padding, so the hold silence is never
        normalized and speech timing is preserved.

        Speech is never stretched, duplicated, or truncated.

        Returns:
            dict {"final_duration", "visual_hold", "reason"} on success, or
            None on hard failure (speech exceeding the maximum duration).
        """
        if not AudioMixer.merge_audio_sequential([ar_audio, ur_audio], merged_audio, gap_seconds=gap_seconds):
            logger.error("Failed to merge audio.")
            return None

        speech_clip = AudioFileClip(merged_audio)
        try:
            speech_duration = speech_clip.duration
        finally:
            speech_clip.close()

        timeline = AudioMixer.compute_video_timeline(speech_duration)
        if not timeline["valid"]:
            logger.error("%s", timeline["reason"])
            return None

        final_duration = timeline["final_duration"]

        # AUDIO-001: normalize speech BEFORE padding (never the hold silence).
        base, ext = os.path.splitext(merged_audio)
        normalized_audio = f"{base}.normalized{ext}"
        ok, _ = AudioMixer.normalize_loudness(merged_audio, normalized_audio)
        if ok:
            src = [normalized_audio]
            gap = 0.0
        else:
            logger.warning("[AUDIO-001] Loudness normalization unavailable; proceeding with unnormalized audio.")
            src = [ar_audio, ur_audio]
            gap = gap_seconds

        if not AudioMixer.merge_audio_sequential(src, merged_audio, gap_seconds=gap, pad_to_duration=final_duration):
            logger.error("Failed to pad audio track with visual hold.")
            return None

        if os.path.exists(normalized_audio):
            with contextlib.suppress(OSError):
                os.remove(normalized_audio)

        logger.info(f"[2/5] Audio ready. {timeline['reason']}")
        return timeline

    def _prepare_audio_track_parallel(self, ar_audio: str, ur_audio: str, merged_audio: str, gap_seconds: float = 0.3):
        """
        PERFORMANCE FIX: Parallel audio processing using ThreadPoolExecutor.
        Merges and normalizes audio in parallel threads.
        """

        def _merge_task():
            return AudioMixer.merge_audio_sequential([ar_audio, ur_audio], merged_audio, gap_seconds=gap_seconds)

        def _normalize_task(input_path, output_path):
            return AudioMixer.normalize_loudness(input_path, output_path)

        # Execute merge in thread pool
        merge_future = self._executor.submit(_merge_task)
        if not merge_future.result():
            logger.error("Failed to merge audio.")
            return None

        # Get speech duration
        speech_clip = AudioFileClip(merged_audio)
        try:
            speech_duration = speech_clip.duration
        finally:
            speech_clip.close()

        timeline = AudioMixer.compute_video_timeline(speech_duration)
        if not timeline["valid"]:
            logger.error("%s", timeline["reason"])
            return None

        final_duration = timeline["final_duration"]

        # Normalize in parallel with duration calculation
        base, ext = os.path.splitext(merged_audio)
        normalized_audio = f"{base}.normalized{ext}"

        # Execute normalization in thread pool
        normalize_future = self._executor.submit(_normalize_task, merged_audio, normalized_audio)

        # Wait for normalization to complete
        ok = normalize_future.result()
        if ok:
            src = [normalized_audio]
            gap = 0.0
        else:
            logger.warning("[AUDIO-001] Loudness normalization unavailable; proceeding with unnormalized audio.")
            src = [ar_audio, ur_audio]
            gap = gap_seconds

        # Pad audio track
        if not AudioMixer.merge_audio_sequential(src, merged_audio, gap_seconds=gap, pad_to_duration=final_duration):
            logger.error("Failed to pad audio track with visual hold.")
            return None

        if os.path.exists(normalized_audio):
            with contextlib.suppress(OSError):
                os.remove(normalized_audio)

        logger.info(f"[2/5] Audio ready (parallel). {timeline['reason']}")
        return timeline

    def _enforce_quality_gate(self, quality_results: dict) -> bool:
        """
        VIDEO-002 hard gate. Resolution (VIDEO-001), duration (15-50s), and
        FPS (exactly 30) failures abort generation. Other checks (e.g. file
        size) remain advisory.
        """
        if quality_results["valid"]:
            logger.info("Quality check passed!")
            return True

        logger.error("Quality check failed:")
        for issue in quality_results["issues"]:
            logger.error(f"  - {issue}")
        info = quality_results.get("video_info", {})
        width = info.get("width", 0)
        height = info.get("height", 0)
        duration = info.get("duration", 0)
        fps = info.get("fps", 0)

        if not self.quality_checker.validate_resolution(width, height):
            logger.error("Video resolution is not exactly 1080x1920. Generation FAILED.")
            return False
        if not self.quality_checker.validate_duration(duration):
            logger.error(
                f"Video duration {duration:.1f}s is outside the required 15-50 second window. Generation FAILED."
            )
            return False
        if not self.quality_checker.validate_fps(fps):
            logger.error(f"Video FPS {fps:.1f} is not exactly 30. Generation FAILED.")
            return False
        return True

    def _check_disk_space(self) -> bool:
        """Pre-flight: return True if enough disk space, False to abort."""
        try:
            usage = shutil.disk_usage(self.temp_dir)
            free_mb = usage.free / (1024 * 1024)
            min_disk = getattr(__import__("config"), "DISK_SPACE_MIN_MB", 500)
            if free_mb < min_disk:
                logger.error(f"Low disk space: {free_mb:.0f}MB free. Need at least {min_disk}MB. Aborting.")
                return False
        except Exception:
            logger.warning("Could not check disk space", exc_info=True)
        return True

    def _make_temp_paths(self, prefix: str):
        """Return (ar_audio, ur_audio, ar_timing, ur_timing, temp_files)."""
        ar_audio = os.path.join(self.temp_dir, f"{prefix}_ar.mp3")
        ur_audio = os.path.join(self.temp_dir, f"{prefix}_ur.mp3")
        ar_timing = os.path.join(self.temp_dir, f"{prefix}_ar_timing.jsonl")
        ur_timing = os.path.join(self.temp_dir, f"{prefix}_ur_timing.jsonl")
        temp_files = [ar_audio, ur_audio, ar_timing, ur_timing]
        return ar_audio, ur_audio, ar_timing, ur_timing, temp_files

    def _cleanup_temp(self, temp_files):
        """Remove temp files, ignoring errors."""
        for tf in temp_files:
            try:
                if os.path.exists(tf):
                    os.remove(tf)
            except OSError:
                pass

    def generate_video(self, dua_id: str, theme: str = "dark", effect: str = "auto", dry_run: bool = False) -> bool:
        """
        Main entry point: Takes a Dua ID and generates the final MP4.

        Args:
            dua_id: Dua identifier
            theme: Video theme
            effect: Visual effect
            dry_run: If True, validate inputs without generating video
        """
        logger.info("=" * 50)
        logger.info(f"STARTING GENERATION FOR: {dua_id}")
        if dry_run:
            logger.info("[DRY RUN] Validation only - no video will be generated")
        logger.info("=" * 50)
        start_time = time.time()
        self._cancel_requested = False

        # 1. Fetch Dua Data
        dua_data = DB.get_dua_by_id(dua_id)
        if not dua_data:
            logger.error(f"Dua with ID '{dua_id}' not found in database.")
            return False

        if dry_run:
            category = dua_data.get("category", "general")
            arabic_text = dua_data.get("arabic", "")
            urdu_text = dua_data.get("urdu", "")
            title = dua_data.get("title", "Dua")
            effect = effect or "auto"
            # Build timeline to estimate duration
            ar_voice = dua_data.get("voice_arabic") or self.tts.pick_voice(dua_id, "ar")
            ur_voice = dua_data.get("voice_urdu") or self.tts.pick_voice(dua_id, "ur")
            prosody_ar = TTSEngine.PROSODY.get("ar", {})
            prosody_ur = TTSEngine.PROSODY.get("ur", {})
            # Estimate duration from text length (~150ms/word Arabic, ~200ms/word Urdu)
            ar_words = len(arabic_text.split())
            ur_words = len(urdu_text.split())
            est_ar = ar_words * 0.15
            est_ur = ur_words * 0.20
            est_total = est_ar + est_ur + 0.3  # gap
            # Pad to VIDEO-002 window
            if est_total < 15:
                est_total = 15.0
            elif est_total > 25:
                est_total = min(est_total, 50.0)
            output_category_dir = os.path.join(self.output_dir, category)
            output_path = os.path.join(output_category_dir, dua_video_filename(dua_data))
            logger.info("=" * 50)
            logger.info("[DRY RUN] WHAT WOULD BE DONE:")
            logger.info(f"  Dua title     : {title}")
            logger.info(f"  Dua ID        : {dua_id}")
            logger.info(f"  Category      : {category}")
            logger.info(f"  Arabic voice  : {ar_voice}")
            logger.info(f"  Urdu voice    : {ur_voice}")
            logger.info(
                f"  Prosody AR    : rate={prosody_ar.get('rate', 'default')}, pitch={prosody_ar.get('pitch', 'default')}"
            )
            logger.info(
                f"  Prosody UR    : rate={prosody_ur.get('rate', 'default')}, pitch={prosody_ur.get('pitch', 'default')}"
            )
            logger.info(f"  Est. duration : ~{est_total:.1f}s (ar={est_ar:.1f}s, ur={est_ur:.1f}s)")
            logger.info(f"  Effect        : {effect}")
            logger.info(f"  Output path   : {output_path}")
            logger.info(f"  Arabic length : {len(arabic_text)} chars ({ar_words} words)")
            logger.info(f"  Urdu length   : {len(urdu_text)} chars ({ur_words} words)")
            logger.info("[DRY RUN] TTS, video rendering, and audio SKIPPED.")
            logger.info("=" * 50)
            return True

        # Pre-flight: disk space check (need ~500MB free minimum)
        if not self._check_disk_space():
            return False

        category = dua_data.get("category", "general")
        arabic_text = dua_data.get("arabic", "")
        urdu_text = dua_data.get("urdu", "")
        title = dua_data.get("title", "Dua")

        logger.info(f"Category    : {category}")
        logger.info(f"Title       : {title}")
        logger.info("Arabic      : [Arabic text loaded]")
        logger.info("Urdu        : [Urdu text loaded]")

        # 2. Generate TTS (Arabic + Urdu)
        # Word-boundary timing is captured (optional, backward compatible) to
        # prepare future audio-synchronized highlighting; it never blocks audio.
        logger.info("[1/5] Generating TTS...")
        ar_audio, ur_audio, ar_timing, ur_timing, temp_files = self._make_temp_paths(dua_id)

        try:
            return self._run_pipeline(
                dua_data, ar_audio, ur_audio, ar_timing, ur_timing, temp_files, start_time, dua_id, theme, effect
            )
        finally:
            self._cleanup_temp(temp_files)

    def _run_pipeline(
        self, dua_data, ar_audio, ur_audio, ar_timing, ur_timing, temp_files, start_time, dua_id, theme, effect
    ) -> bool:
        category = dua_data.get("category", "general")
        arabic_text = dua_data.get("arabic", "")
        urdu_text = dua_data.get("urdu", "")
        title = dua_data.get("title", "Dua")

        # STYLE-ROTATION: explicit per-dua override wins, else pool rotation
        ar_voice = dua_data.get("voice_arabic") or self.tts.pick_voice(dua_id, "ar")
        ur_voice = dua_data.get("voice_urdu") or self.tts.pick_voice(dua_id, "ur")
        logger.info(f"Arabic voice : {ar_voice}")
        logger.info(f"Urdu voice   : {ur_voice}")

        ar_ok, ur_ok = self.tts.generate_both(
            arabic_text,
            urdu_text,
            ar_audio,
            ur_audio,
            ar_timing=ar_timing,
            ur_timing=ur_timing,
            ar_voice=ar_voice,
            ur_voice=ur_voice,
        )
        if not ar_ok:
            logger.error("Failed to generate Arabic TTS.")
            return False
        if not ur_ok:
            logger.error("Failed to generate Urdu TTS.")
            return False
        self._check_memory("TTS")
        self._report_progress(1, 5, "TTS Generated", dua_id, time.time() - start_time)
        if self._cancel_requested:
            logger.info("Generation cancelled by user.")
            return False

        # 3. Merge Audio + apply VIDEO-002 duration policy (15-25s, padded hold)
        logger.info("[2/5] Merging Audio (parallel)...")
        merged_audio = os.path.join(self.temp_dir, f"{dua_id}_merged.wav")
        timeline = self._prepare_audio_track_parallel(ar_audio, ur_audio, merged_audio, gap_seconds=0.3)
        if timeline is None:
            return False
        duration_seconds = timeline["final_duration"]
        self._check_memory("Audio Merge")
        self._report_progress(2, 5, f"Audio merged ({duration_seconds:.1f}s)", dua_id, time.time() - start_time)
        if self._cancel_requested:
            logger.info("Generation cancelled by user.")
            return False

        # 4. Generate Frames (TimelineBuilder + SceneEngine, VISUAL Phase 3)
        #    Audio is immutable; the visual timeline adapts to measured TTS
        #    durations + VIDEO-002 final_duration. Speech text is never altered.
        logger.info("[3/5] Generating frames (this takes time)...")
        ar_dur = TTSEngine.get_audio_duration(ar_audio)
        ur_dur = TTSEngine.get_audio_duration(ur_audio)

        # VISUAL Phase 4: WordBoundary sidecars drive word highlighting.
        # Missing/corrupt sidecars simply disable highlighting (never blocks).
        ar_words = TTSEngine.parse_word_boundaries(ar_timing)
        ur_words = TTSEngine.parse_word_boundaries(ur_timing)

        plan = TimelineBuilder(fps=PROJECT.FPS).build(
            dua_id=dua_id,
            arabic_text=arabic_text,
            urdu_text=urdu_text,
            title=title,
            arabic_duration=ar_dur,
            urdu_duration=ur_dur,
            final_duration=duration_seconds,
            category=category,
            palette=premium_palette(dua_id),
            word_events={"arabic": ar_words, "urdu": ur_words},
            highlight_style=dua_data.get("highlight_style", ""),
            gradient_kind=dua_data.get("gradient_kind", ""),
        )
        if not plan["valid"]:
            logger.error(f"TimelineBuilder failed: {plan['reason']}")
            return False

        has_effect = effect and effect != "none"
        if has_effect:
            frames = SceneRenderer(fps=PROJECT.FPS).render(
                plan["timeline"], seed=dua_id, dua_id=dua_id, category=dua_data.get("category")
            )
            self._check_memory("Scene Render")
            self._report_progress(3, 5, f"Frames rendered ({len(frames)} frames)", dua_id, time.time() - start_time)
        else:
            frames = SceneRenderer(fps=PROJECT.FPS).render_stream(
                plan["timeline"], seed=dua_id, dua_id=dua_id, category=dua_data.get("category")
            )
            self._check_memory("Scene Render (stream)")
            self._report_progress(3, 5, "Frames rendered (stream)", dua_id, time.time() - start_time)

        # Optional visual effect post-processing (frame-level).
        # "auto" + the new AI effects use the EffectDirector brain; legacy
        # effect names keep the original frame-level path for compatibility.
        if has_effect:
            if effect in ("auto", "bloom_glow", "gold_shimmer", "breathing", "rtl_reveal", "glitch_v2", "word_pulse"):
                fxplan = self.director.plan(
                    dua_data, plan, {"arabic": ar_words, "urdu": ur_words}, effect_request=effect, dua_id=dua_id
                )
                frames = self.effect_engine.apply_plan(frames, fxplan["frame_plan"])
                self._check_memory(f"Effects ({effect})")
                self._report_progress(4, 5, f"Effect: {effect}", dua_id, time.time() - start_time)
                logger.info("      %s", fxplan["summary"])
            else:
                frames = self.effect_engine.apply_to_frames(frames, effect)
                self._check_memory(f"Effects ({effect})")
                self._report_progress(4, 5, f"Effect: {effect}", dua_id, time.time() - start_time)
            if self._cancel_requested:
                logger.info("Generation cancelled by user.")
                return False

        # 5. Build Video
        logger.info("[4/5] Assembling video...")
        output_category_dir = os.path.join(self.output_dir, category)
        os.makedirs(output_category_dir, exist_ok=True)
        output_path = os.path.join(output_category_dir, dua_video_filename(dua_data))

        success = self.video_builder.build_video(frames=frames, output_path=output_path, audio_path=merged_audio)

        if not success:
            logger.error("Failed to build video.")
            return False
        self._check_memory("Video Encoding")
        self._report_progress(5, 5, "Video assembled", dua_id, time.time() - start_time)
        if self._cancel_requested:
            logger.info("Generation cancelled by user.")
            return False

        # 6. Quality Check (VIDEO-002 hard gate: resolution + duration + FPS)
        logger.info("[5/5] Quality check...")
        quality_results = self.quality_checker.check_video(output_path)

        if not self._enforce_quality_gate(quality_results):
            return False

        # 7. Generate Metadata
        metadata = self.metadata_generator.generate(arabic_text, urdu_text, category)

        elapsed = time.time() - start_time
        logger.info("=" * 50)
        logger.info("[SUCCESS] Video saved to:")
        logger.info(output_path)
        logger.info(f"   Duration: {duration_seconds:.2f}s")
        logger.info(f"   Size: {os.path.getsize(output_path) / 1024:.1f} KB")
        logger.info(f"   Time Taken: {elapsed:.1f}s")
        logger.info("YouTube Metadata:")
        logger.info(f"   Title: {metadata['title']}")
        logger.info(f"   Tags: {len(metadata['tags'])} tags")
        logger.info("=" * 50)
        return True

    def generate_custom_video(
        self, arabic_text: str, urdu_text: str, title: str = "", effect: str = "neon_glow"
    ) -> bool:
        """
        Generate video from custom dua input.

        Args:
            arabic_text: Arabic dua text
            urdu_text: Urdu translation
            title: Optional title
            effect: Effect to use

        Returns:
            True if successful
        """
        logger.info("=" * 50)
        logger.info("GENERATING CUSTOM DUA VIDEO")
        logger.info("=" * 50)
        start_time = time.time()

        # Local AI agent removed: category uses the deterministic safe default.
        category = "general"

        # Pre-flight: disk space check
        if not self._check_disk_space():
            return False

        # Generate TTS
        logger.info("[1/5] Generating TTS...")
        ar_audio, ur_audio, ar_timing, ur_timing, temp_files = self._make_temp_paths("custom")

        try:
            return self._run_custom_pipeline(
                arabic_text, urdu_text, title, effect, category, ar_audio, ur_audio, ar_timing, ur_timing, start_time
            )
        finally:
            self._cleanup_temp(temp_files)

    def _run_custom_pipeline(
        self, arabic_text, urdu_text, title, effect, category, ar_audio, ur_audio, ar_timing, ur_timing, start_time
    ) -> bool:
        ar_ok, ur_ok = self.tts.generate_both(
            arabic_text, urdu_text, ar_audio, ur_audio, ar_timing=ar_timing, ur_timing=ur_timing
        )
        if not ar_ok:
            logger.error("Failed to generate Arabic TTS.")
            return False
        if not ur_ok:
            logger.error("Failed to generate Urdu TTS.")
            return False
        self._check_memory("TTS")
        self._report_progress(1, 5, "TTS Generated", "custom", time.time() - start_time)

        # Merge Audio + apply VIDEO-002 duration policy (15-25s, padded hold)
        logger.info("[2/5] Merging Audio (parallel)...")
        merged_audio = os.path.join(self.temp_dir, "custom_merged.wav")
        timeline = self._prepare_audio_track_parallel(ar_audio, ur_audio, merged_audio, gap_seconds=0.3)
        if timeline is None:
            return False
        duration_seconds = timeline["final_duration"]
        self._check_memory("Audio Merge")
        self._report_progress(2, 5, f"Audio merged ({duration_seconds:.1f}s)", "custom", time.time() - start_time)

        # Generate Frames (TimelineBuilder + SceneEngine, VISUAL Phase 3)
        #    Audio is immutable; the visual timeline adapts to measured TTS
        #    durations + VIDEO-002 final_duration. Speech text is never altered.
        logger.info("[3/5] Generating frames (this takes time)...")
        ar_dur = TTSEngine.get_audio_duration(ar_audio)
        ur_dur = TTSEngine.get_audio_duration(ur_audio)

        # VISUAL Phase 4: WordBoundary sidecars drive word highlighting.
        # Missing/corrupt sidecars simply disable highlighting (never blocks).
        ar_words = TTSEngine.parse_word_boundaries(ar_timing)
        ur_words = TTSEngine.parse_word_boundaries(ur_timing)

        plan = TimelineBuilder(fps=PROJECT.FPS).build(
            dua_id="custom",
            arabic_text=arabic_text,
            urdu_text=urdu_text,
            title=title,
            arabic_duration=ar_dur,
            urdu_duration=ur_dur,
            final_duration=duration_seconds,
            category=category,
            palette=premium_palette("custom"),
            word_events={"arabic": ar_words, "urdu": ur_words},
            highlight_style="",
            gradient_kind="",
        )
        if not plan["valid"]:
            logger.error(f"TimelineBuilder failed: {plan['reason']}")
            return False

        has_effect = effect and effect != "none"
        if has_effect:
            frames = SceneRenderer(fps=PROJECT.FPS).render(
                plan["timeline"], seed="custom", dua_id="custom", category=category
            )
            self._check_memory("Scene Render")
            self._report_progress(3, 5, f"Frames rendered ({len(frames)} frames)", "custom", time.time() - start_time)
        else:
            frames = SceneRenderer(fps=PROJECT.FPS).render_stream(
                plan["timeline"], seed="custom", dua_id="custom", category=category
            )
            self._check_memory("Scene Render (stream)")
            self._report_progress(3, 5, "Frames rendered (stream)", "custom", time.time() - start_time)

        # Optional visual effect post-processing (frame-level).
        if has_effect:
            dua_data = {
                "id": "custom",
                "category": category,
                "arabic": arabic_text,
                "urdu": urdu_text,
                "title": title or "Custom Dua",
            }
            if effect in ("auto", "bloom_glow", "gold_shimmer", "breathing", "rtl_reveal", "glitch_v2", "word_pulse"):
                fxplan = self.director.plan(
                    dua_data, plan, {"arabic": ar_words, "urdu": ur_words}, effect_request=effect, dua_id="custom"
                )
                frames = self.effect_engine.apply_plan(frames, fxplan["frame_plan"])
                self._check_memory(f"Effects ({effect})")
                self._report_progress(4, 5, f"Effect: {effect}", "custom", time.time() - start_time)
                logger.info("      %s", fxplan["summary"])
            else:
                frames = self.effect_engine.apply_to_frames(frames, effect)
                self._check_memory(f"Effects ({effect})")
                self._report_progress(4, 5, f"Effect: {effect}", "custom", time.time() - start_time)

        # Build Video
        logger.info("[4/5] Assembling video...")
        custom_dir = os.path.join(self.output_dir, "custom")
        os.makedirs(custom_dir, exist_ok=True)

        import datetime

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(custom_dir, f"custom_{timestamp}.mp4")
        success = self.video_builder.build_video(frames=frames, output_path=output_path, audio_path=merged_audio)

        if not success:
            logger.error("Failed to build video.")
            return False
        self._check_memory("Video Encoding")
        self._report_progress(5, 5, "Video assembled", "custom", time.time() - start_time)

        # Quality Check (VIDEO-002 hard gate: resolution + duration + FPS)
        logger.info("[5/5] Quality check...")
        quality_results = self.quality_checker.check_video(output_path)

        if not self._enforce_quality_gate(quality_results):
            return False

        # Generate Metadata
        metadata = self.metadata_generator.generate(arabic_text, urdu_text, category)

        # Save metadata
        metadata_path = os.path.join(custom_dir, f"metadata_{timestamp}.json")
        self.metadata_generator.save_metadata(metadata, metadata_path)

        elapsed = time.time() - start_time
        logger.info("=" * 50)
        logger.info("[SUCCESS] Video saved to:")
        logger.info(output_path)
        logger.info(f"   Duration: {duration_seconds:.2f}s")
        logger.info(f"   Size: {os.path.getsize(output_path) / 1024:.1f} KB")
        logger.info(f"   Time Taken: {elapsed:.1f}s")
        logger.info("YouTube Metadata:")
        logger.info(f"   Title: {metadata['title']}")
        logger.info(f"   Tags: {len(metadata['tags'])} tags generated")
        logger.info(f"   Hashtags: {len(metadata['hashtags'])} hashtags generated")
        logger.info(f"Metadata saved to: {metadata_path}")
        logger.info("=" * 50)
        return True

    def scan_sample_videos(self):
        """Scan sample videos to learn visual styles."""
        logger.info("=" * 50)
        logger.info("SCANNING SAMPLE VIDEOS")
        logger.info("=" * 50)
        logger.info(f"Place your sample videos in: {self.video_analyzer.samples_dir}")
        logger.info("Supported formats: .mp4, .avi, .mov, .mkv, .webm")

        styles = self.video_analyzer.scan_all_samples()

        if styles:
            logger.info("Scanning complete!")
            logger.info(f"Total styles learned: {len(styles)}")
        else:
            logger.info("No styles learned. Please add sample videos.")

    def show_learning_stats(self):
        """Show AI learning statistics."""
        logger.info("=" * 50)
        logger.info("AI LEARNING STATISTICS")
        logger.info("=" * 50)

        stats = self.self_trainer.get_learning_stats()

        logger.info(f"Total Feedback: {stats['total_feedback']}")
        logger.info(f"Average Rating: {stats['average_rating']:.1f}/5")
        logger.info(f"Best Effect: {stats['best_effect']}")
        logger.info(f"Best Color: {stats['best_color']}")

        if stats["effect_averages"]:
            logger.info("Effect Ratings:")
            for effect, rating in stats["effect_averages"].items():
                logger.info(f"  {effect}: {rating:.1f}/5")

        if stats["color_averages"]:
            logger.info("Color Ratings:")
            for color, rating in stats["color_averages"].items():
                logger.info(f"  {color}: {rating:.1f}/5")

        logger.info("=" * 50)

    def interactive_menu(self):
        """
        Shows a menu to the user and handles selection.
        """
        while True:
            logger.info("=" * 50)
            logger.info("     DUA VIDEO GENERATOR - INTERACTIVE MODE")
            logger.info("     Author: MASOOD NASIR")
            logger.info("     Channel: @bushranasir1075")
            logger.info("=" * 50)

            logger.info("Available Options:")
            logger.info("-" * 40)
            logger.info(" 1. Select Dua from Database")
            logger.info(" 2. Enter Custom Dua")
            logger.info(" 3. Generate ALL Duas (Batch)")
            logger.info(" 4. AI Mode (Process custom dua)")
            logger.info(" 5. Scan Sample Videos")
            logger.info(" 6. Learning Statistics")
            logger.info(" 7. Settings")
            logger.info(" 0. Exit")
            logger.info("-" * 40)

            choice = input("\nSelect an option (0-7): ").strip()

            if choice == "0":
                logger.info("Exiting. Goodbye!")
                return

            elif choice == "1":
                self._select_from_database()

            elif choice == "2":
                self._enter_custom_dua()

            elif choice == "3":
                self._batch_mode()

            elif choice == "4":
                self._ai_mode()

            elif choice == "5":
                self.scan_sample_videos()

            elif choice == "6":
                self.show_learning_stats()

            elif choice == "7":
                self._show_settings()

            else:
                logger.info("Invalid option. Please enter 0-7.")

    def _select_from_database(self):
        """Select dua from database."""
        duas = DB.get_all_duas()
        if not duas:
            logger.info("No Duas found in the database.")
            return

        logger.info("Available Duas:")
        logger.info("-" * 40)
        for idx, dua in enumerate(duas, 1):
            title = dua.get("title", "Unknown")
            category = dua.get("category", "general")
            logger.info(f"{idx:3}. {title}  [{category}]")

        logger.info("-" * 40)
        logger.info(" 0. Back to Main Menu")

        while True:
            try:
                choice = input("\nSelect a Dua (enter number): ").strip()
                if choice == "0":
                    return

                idx = int(choice)
                if 1 <= idx <= len(duas):
                    selected = duas[idx - 1]
                    dua_id = selected.get("id")
                    if dua_id:
                        self.generate_video(dua_id)
                    else:
                        logger.error("Selected Dua has no ID.")
                else:
                    logger.info(f"Please enter a number between 1 and {len(duas)}.")
            except ValueError:
                logger.info("Invalid input. Please enter a number.")

    def _enter_custom_dua(self):
        """Enter custom dua text."""
        logger.info("=" * 50)
        logger.info("ENTER CUSTOM DUA")
        logger.info("=" * 50)

        arabic_text = input("\nEnter Arabic text: ").strip()
        if not arabic_text:
            logger.error("Arabic text is required!")
            return

        urdu_text = input("Enter Urdu translation: ").strip()
        if not urdu_text:
            logger.error("Urdu translation is required!")
            return

        title = input("Enter Title (optional): ").strip()

        self.generate_custom_video(arabic_text, urdu_text, title)

    def _batch_mode(self):
        """Generate all duas in batch mode."""
        duas = DB.get_all_duas()
        if not duas:
            logger.info("No Duas found in the database.")
            return

        logger.info("=" * 50)
        logger.info("BATCH MODE: Generating all Duas...")
        logger.info("=" * 50)

        total = len(duas)
        success_count = 0

        for idx, dua in enumerate(duas, 1):
            dua_id = dua.get("id")
            title = dua.get("title", "Unknown")
            logger.info("[%d/%d] Processing: %s (%s)", idx, total, title, dua_id)
            logger.info("-" * 30)

            if self.generate_video(dua_id):
                success_count += 1
            else:
                logger.error("[%d/%d] Failed for %s", idx, total, title)

        logger.info("=" * 50)
        logger.info("BATCH COMPLETE! Successfully generated %d/%d videos.", success_count, total)
        logger.info("=" * 50)

    def _ai_mode(self):
        """AI mode for processing custom dua with advanced features."""
        logger.info("=" * 50)
        logger.info("AI MODE - ADVANCED DUA PROCESSING")
        logger.info("=" * 50)

        arabic_text = input("\nEnter Arabic text: ").strip()
        if not arabic_text:
            logger.error("Arabic text is required!")
            return

        urdu_text = input("Enter Urdu/Roman Urdu/English translation: ").strip()
        if not urdu_text:
            logger.error("Translation is required!")
            return

        title = input("Enter Title (optional): ").strip()

        # Ask for effect selection
        effects = self.revamp_engine.get_available_effects()
        colors = self.revamp_engine.get_available_colors()

        logger.info("Available Effects:")
        for idx, effect in enumerate(effects, 1):
            logger.info(f"  {idx}. {effect}")

        logger.info("Available Colors:")
        for idx, color in enumerate(colors, 1):
            logger.info(f"  {idx}. {color}")

        effect_choice = input("\nSelect effect (number or 'ai' for recommendation): ").strip()

        if effect_choice.lower() == "ai":
            recommendation = self.self_trainer.get_recommendation()
            effect = recommendation.get("best_effect", "neon_glow")
            color = recommendation.get("best_color", "gold")
            logger.info(f"AI recommends: {effect} effect with {color} colors")
        else:
            try:
                effect_idx = int(effect_choice) - 1
                effect = effects[effect_idx]
            except (ValueError, IndexError):
                effect = "neon_glow"

            color_choice = input("Select color (number): ").strip()
            try:
                color_idx = int(color_choice) - 1
                color = colors[color_idx]
            except (ValueError, IndexError):
                color = "gold"

        # Generate video
        self.generate_custom_video(arabic_text, urdu_text, title, effect)

        # Ask for feedback
        logger.info("Rate this video (1-5 stars):")
        try:
            rating = int(input("Rating: ").strip())
            if 1 <= rating <= 5:
                video_data = {
                    "id": f"custom_{int(time.time())}",
                    "effect": effect,
                    "color": color,
                    "duration": 0,  # Will be updated
                }
                self.self_trainer.save_feedback(video_data, rating)
                logger.info("Thank you for your feedback!")
        except ValueError:
            logger.info("Invalid rating. Skipping.")

    def _show_settings(self):
        """Show settings menu."""
        logger.info("=" * 50)
        logger.info("SETTINGS")
        logger.info("=" * 50)

        logger.info("1. View Project Info")
        logger.info("2. View Security Info")
        logger.info("3. Back to Main Menu")

        choice = input("\nSelect (1-3): ").strip()

        if choice == "1":
            logger.info(PROJECT.get_summary())
        elif choice == "2":
            logger.info("Security: AES-128-CBC Encryption (Fernet)")
            logger.info("Key Derivation: PBKDF2-HMAC-SHA256")
            logger.info("Iterations: 600,000")
        elif choice == "3":
            return
        else:
            logger.info("Invalid option.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dua Video Generator")
    parser.add_argument("--dua", type=str, help="Generate video for specific dua ID")
    parser.add_argument("--theme", type=str, default="dark", help="Video theme (default: dark)")
    parser.add_argument("--effect", type=str, default="auto", help="Visual effect (default: auto)")
    parser.add_argument("--batch", action="store_true", help="Generate all missing videos")
    parser.add_argument("--list", action="store_true", help="List all dua IDs")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, no video generation")
    args = parser.parse_args()

    try:
        pipeline = DuaVideoPipeline()
        if args.dua:
            ok = pipeline.generate_video(args.dua, theme=args.theme, effect=args.effect, dry_run=args.dry_run)
            sys.exit(0 if ok else 1)
        elif args.batch:
            pipeline._batch_mode()
        elif args.list:
            from scripts.cmd_list import cmd_list

            cmd_list()
        else:
            pipeline.interactive_menu()
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
