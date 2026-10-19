import logging
import os
from typing import cast
import shutil
import subprocess
import traceback

import imageio
import imageio_ffmpeg
import numpy as np
from moviepy import AudioFileClip, VideoFileClip
from PIL import Image

logger = logging.getLogger(__name__)

try:
    import config
except Exception:
    logger.debug("config not available, using defaults")
    config = None  # type: ignore[assignment]

__all__ = ["VideoBuilder"]


class VideoBuilder:
    """
    Assembles frames into a video and syncs audio.
    Uses imageio for fast frame writing and moviepy for audio mixing.
    """

    def __init__(self, fps: int | None = None, resolution: tuple = (1080, 1920)):
        """
        Args:
            fps: Frames per second. Defaults to config.VIDEO_FPS (30) so the
                container framerate always matches the pipeline's render FPS;
                a mismatch would fail the exact-FPS quality gate.
            resolution: (width, height) for output video.
        """
        if fps is None:
            fps = int(getattr(config, "VIDEO_FPS", 30))
        self.fps = fps
        self.width, self.height = resolution

        # Load FFmpeg encoding config from config.py
        self.crf = getattr(config, "FFMPEG_CRF", 15) if config else 15
        self.preset = getattr(config, "FFMPEG_PRESET", "slow") if config else "slow"
        self.profile = getattr(config, "FFMPEG_PROFILE", "high") if config else "high"
        self.level = getattr(config, "FFMPEG_LEVEL", "4.1") if config else "4.1"
        self.gop = getattr(config, "FFMPEG_GOP", 30) if config else 30
        self.movflags = getattr(config, "FFMPEG_MOVFLAGS", "+faststart") if config else "+faststart"
        self.pix_fmt = getattr(config, "FFMPEG_PIX_FMT", "yuv420p") if config else "yuv420p"
        self.sharpen = getattr(config, "FFMPEG_SHARPEN", True) if config else True
        self.color_grade = getattr(config, "FFMPEG_COLOR_GRADE", True) if config else True
        self.loudness = getattr(config, "FFMPEG_LOUDNESS", True) if config else True

    def _mux_direct(self, video_path: str, audio_path: str, output_path: str) -> bool:
        """
        AUDIO-001 + Phase 2: Mux video + audio with full post-processing.
        Re-encodes video with YouTube-optimized settings + sharpening +
        color grading + loudness normalization in a single FFmpeg pass.
        """
        try:
            sample_rate = int(getattr(config, "AUDIO_SAMPLE_RATE", 48000))
            bitrate = str(getattr(config, "AUDIO_BITRATE", "192k"))
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

            # Trim guard
            trim_arg = []
            with VideoFileClip(video_path) as vc, AudioFileClip(audio_path) as ac:
                vdur, adur = vc.duration, ac.duration
            if vdur > adur:
                trim_arg = ["-t", f"{adur:.4f}"]
            elif adur > vdur:
                trim_arg = ["-t", f"{vdur:.4f}"]

            # Build video filter chain for post-processing
            vf_parts = []
            if self.sharpen:
                vf_parts.append("unsharp=5:5:0.8:3:3:0.4")
            if self.color_grade:
                vf_parts.append("eq=saturation=1.15:contrast=1.05:brightness=0.02")
            vf_str = ",".join(vf_parts) if vf_parts else None

            # Build audio filter for loudness normalization. The spoken track is
            # ALREADY normalized upstream (AudioMixer.normalize_loudness, two-pass
            # LINEAR -14 LUFS / -1.0 dBTP, AUDIO-001). Re-running loudnorm here
            # would double-normalize AND switch to DYNAMIC mode (violating
            # AUDIO-001), so the mux pass leaves audio untouched.
            af_str = None

            cmd = (
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    video_path,
                    "-i",
                    audio_path,
                ]
                + trim_arg
                + [
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                ]
            )

            # Video: re-encode with YouTube-optimized settings
            cmd += [
                "-c:v",
                "libx264",
                "-crf",
                str(self.crf),
                "-preset",
                self.preset,
                "-profile:v",
                self.profile,
                "-level:v",
                self.level,
                "-pix_fmt",
                self.pix_fmt,
                "-g",
                str(self.gop),
                "-movflags",
                self.movflags,
                "-bf",
                "2",
                "-coder",
                "1",
            ]
            if vf_str:
                cmd += ["-vf", vf_str]

            # Audio: AAC with optional loudness normalization
            cmd += [
                "-c:a",
                "aac",
                "-b:a",
                bitrate,
                "-ar",
                str(sample_rate),
                "-ac",
                "2",
            ]
            if af_str:
                cmd += ["-af", af_str]

            cmd += [output_path]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
            if result.returncode != 0 or not os.path.exists(output_path):
                logger.error(f"ffmpeg mux failed: {result.stderr[-500:]}")
                return False
            file_size = os.path.getsize(output_path) / (1024 * 1024)
            logger.info(
                f"Muxed+enhanced video (CRF {self.crf}, {self.preset}, "
                f"{self.profile}, {file_size:.1f}MB): {output_path}"
            )
            return True
        except Exception as e:
            logger.error(f"Direct mux error: {e}")
            return False

    def build_video(
        self, frames: list, output_path: str, audio_path: str | None = None, temp_video_path: str | None = None
    ) -> bool:
        """
        Converts frames into an MP4 video. Accepts list or generator.

        Args:
            frames: List of PIL Image objects, numpy arrays, or a generator/iterable.
            output_path: Full path for the final .mp4 file.
            audio_path: Optional path to .mp3 audio file to add.
            temp_video_path: Optional path for temp video (without audio).
                             If None, uses output_path with '_temp' suffix.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            # Determine temp video path
            if temp_video_path is None:
                base, ext = os.path.splitext(output_path)
                temp_video_path = f"{base}_temp{ext}"

            # bare filenames have no directory component -> use cwd
            out_dir = os.path.dirname(output_path) or "."
            tmp_dir = os.path.dirname(temp_video_path) or "."
            os.makedirs(out_dir, exist_ok=True)
            os.makedirs(tmp_dir, exist_ok=True)

            # Convert generator to list if needed for counting
            if hasattr(frames, "__iter__") and not isinstance(frames, (list, tuple)):
                frames = list(frames)

            if not frames:
                logger.error("No frames provided.")
                return False

            logger.info(f"Processing {len(frames)} frames...")

            # Write video WITHOUT audio using imageio
            logger.info(f"Writing temporary video: {temp_video_path}")
            with imageio.get_writer(
                temp_video_path,
                fps=self.fps,
                format="FFMPEG",  # type: ignore[arg-type]
                codec="libx264",
                pixelformat="yuv420p",
                macro_block_size=2,
                ffmpeg_params=[
                    "-crf",
                    "10",  # Near-lossless intermediate (re-encode in mux)
                    "-preset",
                    "ultrafast",  # Fast intermediate, quality in mux pass
                    "-g",
                    "30",  # GOP anchor every 30 frames
                ],
            ) as writer:
                for i, frame in enumerate(frames):
                    if isinstance(frame, Image.Image):
                        if frame.size != (self.width, self.height):
                            frame = frame.resize((self.width, self.height), Image.Resampling.LANCZOS)
                        writer.append_data(np.array(frame))  # type: ignore[attr-defined]
                    elif isinstance(frame, np.ndarray):
                        writer.append_data(frame)  # type: ignore[attr-defined]
                    else:
                        raise TypeError(f"Unsupported frame type: {type(frame)}")
                    if (i + 1) % 100 == 0:
                        logger.info("  Written %d frames...", i + 1)

            logger.info("Temp video created successfully.")

            # Add audio if provided (AUDIO-001 direct mux, no re-encode)
            if audio_path and os.path.exists(audio_path):
                logger.info(f"Adding audio: {audio_path}")
                if not self._mux_direct(temp_video_path, audio_path, output_path):
                    logger.error("Audio mixing failed. Falling back to video without audio.")
                    shutil.copy2(temp_video_path, output_path)

                # Delete temp video
                if os.path.exists(temp_video_path):
                    os.remove(temp_video_path)
            else:
                # No audio: just rename/move temp file
                logger.info(f"No audio provided. Saving final video: {output_path}")
                shutil.copy2(temp_video_path, output_path)
                if os.path.exists(temp_video_path):
                    os.remove(temp_video_path)

            logger.info(f"Video built successfully: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Critical error building video: {e}")
            traceback.print_exc()
            return False
