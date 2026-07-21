"""Per-call recording (MP3) and timestamped transcript helpers."""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from pydub import AudioSegment

from src.audio_utils import SAMPLE_RATE

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CallRecorder:
    """Collects both sides of the call and writes artifacts at hangup."""

    call_sid: str
    recordings_dir: Path
    transcripts_dir: Path
    started_at: datetime = field(default_factory=_utc_now)
    # Mono 8 kHz PCM16 timeline: inbound (agent) + outbound (patient) in order.
    _pcm: bytearray = field(default_factory=bytearray)
    _lines: list[str] = field(default_factory=list)

    def append_pcm16(self, pcm: bytes) -> None:
        if pcm:
            self._pcm.extend(pcm)

    def log(self, speaker: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        elapsed = (_utc_now() - self.started_at).total_seconds()
        stamp = f"{elapsed:7.2f}s"
        line = f"[{stamp}] {speaker}: {text}"
        self._lines.append(line)
        logger.info("%s | %s", self.call_sid, line)

    def save(self) -> tuple[Path | None, Path]:
        """Write recordings/{call_sid}.mp3 and transcripts/{call_sid}.txt."""
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)

        transcript_path = self.transcripts_dir / f"{self.call_sid}.txt"
        transcript_path.write_text("\n".join(self._lines) + ("\n" if self._lines else ""))
        logger.info("Saved transcript %s", transcript_path)

        recording_path: Path | None = None
        if self._pcm:
            recording_path = self.recordings_dir / f"{self.call_sid}.mp3"
            try:
                # Build a WAV in memory, then export MP3 via pydub (needs ffmpeg).
                wav_buf = BytesIO()
                with wave.open(wav_buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(bytes(self._pcm))
                wav_buf.seek(0)
                audio = AudioSegment.from_wav(wav_buf)
                audio.export(recording_path, format="mp3")
                logger.info("Saved recording %s", recording_path)
            except Exception:
                # Fall back to WAV so we never lose the audio on a challenge laptop
                # that doesn't have ffmpeg installed.
                logger.exception("MP3 export failed; writing WAV instead")
                recording_path = self.recordings_dir / f"{self.call_sid}.wav"
                with wave.open(str(recording_path), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(bytes(self._pcm))

        return recording_path, transcript_path
