"""Speech-to-text via faster-whisper.

We run Whisper on each completed utterance (after silence detection), not on
every tiny Twilio chunk — that keeps latency and CPU reasonable for a demo.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from faster_whisper import WhisperModel

from src.audio_utils import SAMPLE_RATE, pcm16_to_float32, resample_pcm16

logger = logging.getLogger(__name__)

# Whisper expects ~16 kHz float audio.
WHISPER_RATE = 16000


@lru_cache(maxsize=1)
def get_whisper_model(model_size: str, download_root: str) -> WhisperModel:
    """Load the Whisper model once per process (first call downloads weights)."""
    Path(download_root).mkdir(parents=True, exist_ok=True)
    logger.info("Loading faster-whisper model=%s into %s", model_size, download_root)
    # CPU + int8 is fine for short phone utterances on a laptop.
    return WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
        download_root=download_root,
    )


def transcribe_pcm16(
    pcm_8k: bytes,
    *,
    model_size: str,
    models_dir: Path,
) -> str:
    """Transcribe 8 kHz PCM16 telephony audio; return plain text (may be empty)."""
    if not pcm_8k:
        return ""

    pcm_16k = resample_pcm16(pcm_8k, SAMPLE_RATE, WHISPER_RATE)
    audio = pcm16_to_float32(pcm_16k)

    model = get_whisper_model(model_size, str(models_dir))
    segments, _info = model.transcribe(
        audio,
        language="en",
        beam_size=1,
        vad_filter=False,  # we already did our own pause detection
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text
