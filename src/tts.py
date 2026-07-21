"""Text-to-speech via ElevenLabs Flash, converted to Twilio mu-law @ 8 kHz.

We request raw PCM from ElevenLabs (pcm_24000), then reuse the same
resample → mu-law path as before so Twilio Media Streams get 8 kHz G.711.
"""

from __future__ import annotations

import logging

from elevenlabs.client import ElevenLabs

from src.audio_utils import pcm16_to_mulaw, resample_pcm16

logger = logging.getLogger(__name__)

ELEVENLABS_PCM_RATE = 24000
TWILIO_RATE = 8000
DEFAULT_MODEL = "eleven_flash_v2_5"


def synthesize_mulaw(
    text: str,
    *,
    api_key: str,
    voice_id: str,
    model: str = DEFAULT_MODEL,
) -> bytes:
    """Return mu-law 8 kHz audio bytes for `text` (empty if text is blank)."""
    text = (text or "").strip()
    if not text:
        return b""
    if not voice_id:
        raise ValueError("ELEVENLABS_VOICE_ID is required for TTS")

    client = ElevenLabs(api_key=api_key)
    logger.info("TTS ElevenLabs (%s / %s): %s", model, voice_id, text[:80])

    # convert() yields audio chunks; pcm_24000 is raw signed 16-bit LE @ 24 kHz.
    audio_iter = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=model,
        output_format="pcm_24000",
    )
    pcm_24k = b"".join(audio_iter)
    pcm_8k = resample_pcm16(pcm_24k, ELEVENLABS_PCM_RATE, TWILIO_RATE)
    return pcm16_to_mulaw(pcm_8k)
