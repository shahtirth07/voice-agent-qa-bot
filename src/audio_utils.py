"""Low-level audio helpers for Twilio Media Streams (8 kHz mu-law).

Twilio sends/expects raw G.711 mu-law at 8000 Hz, mono, base64-encoded.
We decode to 16-bit PCM for energy detection, Whisper, and recording.
"""

from __future__ import annotations

import audioop
from dataclasses import dataclass, field

import numpy as np

# Twilio Media Streams clock
SAMPLE_RATE = 8000
# 20 ms frames are typical; we accept whatever chunk size Twilio sends
BYTES_PER_SAMPLE_PCM = 2


def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    """Decode mu-law bytes to signed 16-bit little-endian PCM."""
    return audioop.ulaw2lin(mulaw_bytes, BYTES_PER_SAMPLE_PCM)


def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Encode signed 16-bit PCM to mu-law."""
    return audioop.lin2ulaw(pcm_bytes, BYTES_PER_SAMPLE_PCM)


def resample_pcm16(pcm_bytes: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample mono 16-bit PCM between sample rates (for Whisper / TTS)."""
    if from_rate == to_rate:
        return pcm_bytes
    converted, _ = audioop.ratecv(
        pcm_bytes, BYTES_PER_SAMPLE_PCM, 1, from_rate, to_rate, None
    )
    return converted


def pcm16_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert PCM16 bytes to float32 numpy array in [-1, 1] (Whisper input)."""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    return samples / 32768.0


def rms_energy(pcm_bytes: bytes) -> float:
    """Root-mean-square energy of a PCM16 chunk (0 if empty)."""
    if not pcm_bytes:
        return 0.0
    return float(audioop.rms(pcm_bytes, BYTES_PER_SAMPLE_PCM))


@dataclass
class SilenceDetector:
    """Very simple energy-based end-of-utterance detector.

    - While RMS > speech_threshold, we treat audio as speech and keep buffering.
    - After speech has started, if RMS stays below silence_threshold for
      silence_ms milliseconds, we consider the utterance complete.
    """

    speech_threshold: float = 400.0
    silence_threshold: float = 350.0
    silence_ms: int = 700
    min_speech_ms: int = 300
    sample_rate: int = SAMPLE_RATE

    _buffer: bytearray = field(default_factory=bytearray)
    _in_speech: bool = False
    _silence_ms: float = 0.0
    _speech_ms: float = 0.0

    def reset(self) -> None:
        self._buffer.clear()
        self._in_speech = False
        self._silence_ms = 0.0
        self._speech_ms = 0.0

    def feed(self, pcm_chunk: bytes) -> bytes | None:
        """Feed PCM16 audio. Returns a completed utterance, or None."""
        if not pcm_chunk:
            return None

        duration_ms = 1000.0 * (len(pcm_chunk) / BYTES_PER_SAMPLE_PCM) / self.sample_rate
        energy = rms_energy(pcm_chunk)

        if energy >= self.speech_threshold:
            self._in_speech = True
            self._silence_ms = 0.0
            self._speech_ms += duration_ms
            self._buffer.extend(pcm_chunk)
            return None

        if not self._in_speech:
            # Ignore leading silence / noise before the agent starts talking.
            return None

        # We were in speech; this chunk is quieter.
        self._buffer.extend(pcm_chunk)
        if energy <= self.silence_threshold:
            self._silence_ms += duration_ms
        else:
            # Ambiguous mid-level energy — still count a little toward speech.
            self._speech_ms += duration_ms
            self._silence_ms = 0.0

        if (
            self._silence_ms >= self.silence_ms
            and self._speech_ms >= self.min_speech_ms
        ):
            utterance = bytes(self._buffer)
            self.reset()
            return utterance

        return None
