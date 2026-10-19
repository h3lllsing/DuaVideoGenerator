import asyncio
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor

import imageio_ffmpeg
import numpy as np
from moviepy import AudioFileClip, concatenate_audioclips
import contextlib

logger = logging.getLogger(__name__)

try:
    import config
except Exception:
    logger.debug("config not available for audio mixer")
    config = None  # type: ignore[assignment]

__all__ = ["AudioMixer"]

# Thread pool for offloading blocking moviepy write_audiofile calls
# so they don't block the main thread / event loop.
_AUDIO_THREAD_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audio_io")

# AUDIO-001: 48 kHz PCM/WAV downstream intermediate (lossless; single AAC at end)
# PILLAR 2: broadcast retarget - platform anchor -14 LUFS / -1.0 dBTP
DEFAULT_SAMPLE_RATE = 48000
LOUDNESS_TARGET = -14.0  # LUFS integrated (YouTube Shorts / TikTok anchor)
TRUE_PEAK_TARGET = -1.0  # dBTP ceiling
LRA_TARGET = 11.0


class AudioMixer:
    """
    Handles merging of multiple audio files (Arabic + Urdu) into a single track.
    Currently supports sequential concatenation (Arabic plays first, then Urdu).
    Also computes the VIDEO-002 duration policy (15-25 seconds) from speech audio.
    """

    @staticmethod
    def compute_video_timeline(
        speech_duration: float,
        min_duration: float | None = None,
        max_duration: float | None = None,
        default_hold: float = 0.5,
    ) -> dict:
        """
        Compute the final video duration and visual hold from spoken audio duration.

        VIDEO-002 duration policy:
          A) speech < min_duration  -> pad with VISUAL hold so final == min_duration
          B) min <= speech+hold <= max -> valid (hold shrinks as speech approaches max)
          C) speech > max_duration  -> hard failure (speech must NEVER be cut)
          D) final outside [min, max]  -> hard failure

        Speech is never stretched, duplicated, or truncated. Padding is visual
        hold only (silence appended to the audio track by the caller via
        pad_to_duration in merge_audio_sequential).

        Args:
            speech_duration: Duration of the merged spoken audio (Arabic+gap+Urdu).
            min_duration: Minimum video duration (default: config VIDEO_MIN_DURATION=15).
            max_duration: Maximum video duration (default: config VIDEO_MAX_DURATION=50).
            default_hold: Preferred visual hold applied when speech is within range.

        Returns:
            dict: {"valid": bool, "final_duration": float|None,
                   "visual_hold": float, "reason": str}
        """
        if min_duration is None:
            min_duration = float(getattr(config, "VIDEO_MIN_DURATION", 15))
        if max_duration is None:
            max_duration = float(getattr(config, "VIDEO_MAX_DURATION", 50))

        if speech_duration < 0:
            return {
                "valid": False,
                "final_duration": None,
                "visual_hold": 0.0,
                "reason": f"Invalid speech duration: {speech_duration}",
            }

        # Case C: speech itself exceeds the maximum -> hard failure, never cut speech.
        if speech_duration > max_duration:
            return {
                "valid": False,
                "final_duration": None,
                "visual_hold": 0.0,
                "reason": (
                    f"Speech duration {speech_duration:.2f}s exceeds the maximum "
                    f"{max_duration:.2f}s. Spoken audio cannot be cut. "
                    "Shorten the dua text or split it into separate videos."
                ),
            }

        # Case A: speech below minimum -> pad visual hold up to the minimum.
        if speech_duration < min_duration:
            hold = min_duration - speech_duration
            final_duration = min_duration
            reason = f"padded: speech {speech_duration:.2f}s + visual hold {hold:.2f}s (final {final_duration:.2f}s)"
        else:
            # Case B: speech within range -> add default hold, but never exceed max.
            hold = min(default_hold, max_duration - speech_duration)
            hold = max(0.0, hold)
            final_duration = speech_duration + hold
            reason = f"speech {speech_duration:.2f}s + visual hold {hold:.2f}s (final {final_duration:.2f}s)"

        # Case D: safety net for any float edge cases.
        eps = 1e-6
        if not (min_duration - eps <= final_duration <= max_duration + eps):
            return {
                "valid": False,
                "final_duration": None,
                "visual_hold": 0.0,
                "reason": (
                    f"Final duration {final_duration:.2f}s is outside the required "
                    f"{min_duration:.2f}-{max_duration:.2f}s window."
                ),
            }

        return {
            "valid": True,
            "final_duration": round(final_duration, 6),
            "visual_hold": round(hold, 6),
            "reason": reason,
        }

    @staticmethod
    def _get_sample_rate(sample_rate):
        if sample_rate:
            return sample_rate
        return int(getattr(config, "AUDIO_SAMPLE_RATE", DEFAULT_SAMPLE_RATE))

    @staticmethod
    def merge_audio_sequential(
        audio_paths: list,
        output_path: str,
        gap_seconds: float = 0.5,
        pad_to_duration: float | None = None,
        sample_rate: int | None = None,
    ) -> bool:
        """
        Merges multiple audio files one after another with a small gap.

        AUDIO-001: downstream intermediates are lossless 48 kHz stereo
        PCM/WAV (pcm_s16le). Speech is never stretched, duplicated, or
        re-encoded to a lossy format here.

        Args:
            audio_paths: List of paths to audio files (e.g., ['ar.mp3', 'ur.mp3']).
            output_path: Path for the final merged .wav file.
            gap_seconds: Silence gap between clips (in seconds).
            pad_to_duration: If set, append trailing silence so the merged track
                             reaches exactly this duration (VIDEO-002 visual
                             hold; speech is never stretched or duplicated).
            sample_rate: Target sample rate (default: config AUDIO_SAMPLE_RATE).

        Returns:
            bool: True if successful, False otherwise.
        """
        clips = []
        final_clip = None
        try:
            sample_rate = AudioMixer._get_sample_rate(sample_rate)

            # Ensure temp directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            for path in audio_paths:
                if os.path.exists(path):
                    clip = AudioFileClip(path, fps=sample_rate)
                    clips.append(clip)

                    # Add a silent gap after each clip except the last
                    if gap_seconds > 0 and len(clips) < len(audio_paths):
                        clips.append(AudioMixer._make_silence(gap_seconds, sample_rate))
                else:
                    logger.warning("Audio file not found: %s", path)

            if not clips:
                logger.error("No valid audio clips to merge.")
                return False

            # VIDEO-002: append trailing silence so the track reaches the target
            # duration. This creates the visual-hold window; speech is unchanged.
            if pad_to_duration is not None:
                speech_duration = sum(c.duration for c in clips)
                if pad_to_duration > speech_duration + 1e-6:
                    hold = pad_to_duration - speech_duration
                    logger.info(
                        "Padding track with %.2fs trailing silence (speech %.2fs -> %.2fs)",
                        hold,
                        speech_duration,
                        pad_to_duration,
                    )
                    clips.append(AudioMixer._make_silence(hold, sample_rate))
                elif pad_to_duration < speech_duration - 1e-6:
                    logger.warning(
                        "pad_to_duration %.2fs is shorter than speech %.2fs; speech will NOT be trimmed.",
                        pad_to_duration,
                        speech_duration,
                    )

            # Concatenate all clips
            final_clip = concatenate_audioclips(clips)

            # Write lossless PCM/WAV (AUDIO-001: no lossy re-encode here).
            # Offload to thread pool so FFmpeg doesn't block the main thread.
            future = _AUDIO_THREAD_POOL.submit(
                final_clip.write_audiofile,
                output_path,
                codec="pcm_s16le",
                fps=sample_rate,
                logger=None,
            )
            future.result(timeout=300)

            logger.info("Successfully merged audio to: %s", output_path)
            return True

        except Exception as e:
            logger.error("Error merging audio: %s", e)
            import traceback

            traceback.print_exc()
            return False

        finally:
            for clip in clips:
                with contextlib.suppress(OSError, ValueError):
                    clip.close()
            if final_clip is not None:
                with contextlib.suppress(OSError, ValueError):
                    final_clip.close()

    @staticmethod
    def merge_audio_crossfade(
        audio_paths: list,
        output_path: str,
        crossfade_seconds: float = 0.3,
        pad_to_duration: float | None = None,
        sample_rate: int | None = None,
    ) -> bool:
        """
        Merges multiple audio files with a cross-fade overlap between clips.

        Each clip's end overlaps with the next clip's start by crossfade_seconds,
        creating a smooth transition instead of a hard cut + silence gap.

        Args:
            audio_paths: List of paths to audio files.
            output_path: Path for the final merged .wav file.
            crossfade_seconds: Overlap duration in seconds (default 0.3).
            pad_to_duration: If set, append trailing silence to reach this duration.
            sample_rate: Target sample rate (default: config AUDIO_SAMPLE_RATE).

        Returns:
            bool: True if successful, False otherwise.
        """
        from moviepy import CompositeAudioClip

        clips = []
        final = None
        try:
            sample_rate = AudioMixer._get_sample_rate(sample_rate)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            for ap in audio_paths:
                if os.path.exists(ap):
                    clips.append(AudioFileClip(ap, fps=sample_rate))
                else:
                    logger.warning("Audio file not found: %s", ap)

            if not clips:
                logger.error("No valid audio clips to crossfade.")
                return False

            # Apply cross-fade: offset each clip and set crossfadein
            if len(clips) > 1 and crossfade_seconds > 0:
                cf = min(crossfade_seconds, min(c.duration for c in clips) / 2)
                offset = 0
                for i, c in enumerate(clips):
                    c.start = offset
                    if i > 0:
                        c.crossfadein(cf)
                    offset += c.duration - (cf if i > 0 else 0)
                final = CompositeAudioClip(clips)
            else:
                final = concatenate_audioclips(clips)

            # Pad to target duration
            if pad_to_duration is not None:
                speech_dur = final.duration
                if pad_to_duration > speech_dur + 1e-6:
                    hold = pad_to_duration - speech_dur
                    logger.info("Crossfade: padding %.2fs trailing silence", hold)
                    silence = AudioMixer._make_silence(hold, sample_rate)
                    silence.start = final.duration
                    final = CompositeAudioClip([final, silence])

            # Offload blocking FFmpeg write to thread pool
            future = _AUDIO_THREAD_POOL.submit(
                final.write_audiofile,
                output_path,
                codec="pcm_s16le",
                fps=sample_rate,
                nbytes=2,
                logger=None,
            )
            future.result(timeout=300)

            logger.info("Crossfade merged audio to: %s", output_path)
            return True

        except Exception as e:
            logger.error("Error crossfade merging: %s", e)
            import traceback

            traceback.print_exc()
            return False

        finally:
            for c in clips:
                with contextlib.suppress(OSError, ValueError):
                    c.close()
            if final is not None:
                with contextlib.suppress(OSError, ValueError):
                    final.close()

    @staticmethod
    async def _measure_loudness_async(input_path: str) -> dict:
        """
        Async: Measure EBU R128 loudness using bundled ffmpeg (loudnorm,
        print_format=json). Non-blocking subprocess.
        """
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-i",
                input_path,
                "-af",
                "loudnorm=I={}:TP={}:LRA={}:print_format=json".format(LOUDNESS_TARGET, TRUE_PEAK_TARGET, LRA_TARGET),
                "-f",
                "null",
                "-",
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120,
            )
            stderr_text = stderr.decode("utf-8", errors="replace")
            out = {}
            for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
                m = re.search(r'"{}"\s*:\s*"(-?[\d.]+)"'.format(key), stderr_text)
                if m:
                    out[key] = float(m.group(1))
            return out
        except Exception as e:
            logger.error("Loudness measurement failed: %s", e)
            return {}

    @staticmethod
    def measure_loudness(input_path: str) -> dict:
        """
        Measure EBU R128 loudness of an audio file using the bundled ffmpeg
        (loudnorm, print_format=json). Pure measurement; nothing is written.

        Returns:
            dict with input_i (LUFS), input_tp (dBTP), input_lra, input_thresh,
            target_offset, or an empty dict on failure.
        """
        return asyncio.run(AudioMixer._measure_loudness_async(input_path))

    @staticmethod
    async def _normalize_loudness_async(input_path: str, output_path: str, sample_rate: int | None = None) -> tuple:
        """
        Async: AUDIO-001 two-pass LINEAR ffmpeg loudnorm.
        Non-blocking subprocess calls.
        """
        try:
            sample_rate = AudioMixer._get_sample_rate(sample_rate)
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

            measured = await AudioMixer._measure_loudness_async(input_path)
            if not measured.get("input_i"):
                logger.warning("loudnorm measure failed; skipping normalization.")
                return False, {}

            af = (
                "loudnorm=I={}:TP={}:LRA={}:measured_I={}:measured_TP={}:"
                "measured_LRA={}:measured_thresh={}:offset={}:linear=true".format(
                    LOUDNESS_TARGET,
                    TRUE_PEAK_TARGET,
                    LRA_TARGET,
                    measured["input_i"],
                    measured["input_tp"],
                    measured["input_lra"],
                    measured["input_thresh"],
                    measured.get("target_offset", 0),
                )
            )
            cmd = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                input_path,
                "-af",
                af,
                "-ar",
                str(sample_rate),
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                output_path,
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=300,
            )
            if process.returncode != 0 or not os.path.exists(output_path):
                err_text = stderr.decode("utf-8", errors="replace")
                logger.error("loudnorm apply failed: %s", err_text[-400:])
                return False, {}

            logger.info("Loudness normalized %.1f LUFS -> %d LUFS", measured["input_i"], LOUDNESS_TARGET)
            return True, await AudioMixer._measure_loudness_async(output_path)
        except Exception as e:
            logger.error("Normalization error: %s", e)
            return False, {}

    @staticmethod
    def normalize_loudness(input_path: str, output_path: str, sample_rate: int | None = None) -> tuple:
        """
        AUDIO-001: two-pass LINEAR ffmpeg loudnorm.

        Pass 1 measures EBU R128 loudness (print_format=json). Pass 2 applies
        a LINEAR gain (linear=true with measured values) targeting
        LOUDNESS_TARGET (-14 LUFS) integrated and TRUE_PEAK_TARGET (-1 dBTP)
        true peak. Linear mode preserves sample positions exactly, so speech
        duration and WordBoundary timing are unchanged. Dynamic loudnorm is
        never used.

        Returns:
            (bool ok, dict measured_out). measured_out contains the measured
            loudness of the OUTPUT file (input_i/input_tp of the result).
        """
        return asyncio.run(AudioMixer._normalize_loudness_async(input_path, output_path, sample_rate))

    @staticmethod
    def _make_silence(duration: float, sample_rate: int = DEFAULT_SAMPLE_RATE):
        """Create a silent stereo audio clip of the given duration."""
        from moviepy import AudioClip

        def make_silence(t):
            return np.zeros(2)  # Stereo silence

        return AudioClip(make_silence, duration=duration, fps=sample_rate)
