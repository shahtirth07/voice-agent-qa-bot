"""FastAPI server: Twilio voice webhook + bidirectional Media Stream WebSocket.

Flow for one call
-----------------
1. test_call.py places an outbound call with url=PUBLIC_BASE_URL/voice
2. Twilio hits POST /voice → we return TwiML that <Connect><Stream>s to /media
3. Twilio opens a WebSocket to /media and streams the remote party (Athena)
   as base64 mu-law chunks
4. We buffer until a pause, Whisper-transcribe, ask the patient LLM what to say,
   TTS that line, and stream mu-law audio back on the same WebSocket
5. On stream stop we write recordings/{call_sid}.mp3 + transcripts/{call_sid}.txt
   and automatically run bug analysis into bug_reports/

Run (after ngrok / PUBLIC_BASE_URL is set)::

    uvicorn src.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

from src.audio_utils import SilenceDetector, mulaw_to_pcm16
from src.bug_analyzer import analyze_transcript
from src.config import get_config
from src.patient_agent import PatientAgent, get_scenario
from src.recording import CallRecorder
from src.stt import transcribe_pcm16
from src.tts import synthesize_mulaw

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Athena Voice Tester")

# Chunk size when sending TTS back to Twilio (~20 ms of 8 kHz mu-law).
OUTBOUND_CHUNK_MULAW = 160


def _ws_media_url(public_base_url: str) -> str:
    """https://x.ngrok.io → wss://x.ngrok.io/media (Twilio requires wss)."""
    if public_base_url.startswith("https://"):
        return "wss://" + public_base_url.removeprefix("https://") + "/media"
    if public_base_url.startswith("http://"):
        return "ws://" + public_base_url.removeprefix("http://") + "/media"
    return public_base_url.rstrip("/") + "/media"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/voice")
async def voice_webhook(request: Request) -> Response:
    """Twilio calls this when the outbound leg connects.

    Returns TwiML that starts a *bidirectional* Media Stream via <Connect>.
    Optional form field / query `scenario` overrides the default SCENARIO env.
    """
    config = get_config()
    form: dict[str, Any] = {}
    try:
        form = dict(await request.form())
    except Exception:
        form = {}

    scenario_id = (
        request.query_params.get("scenario")
        or form.get("scenario")
        or config.scenario
    )

    ws_url = _ws_media_url(config.public_base_url)
    logger.info("Returning Media Stream TwiML → %s (scenario=%s)", ws_url, scenario_id)

    # <Connect><Stream> = bidirectional; we both receive Athena and speak as patient.
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=ws_url)
    stream.parameter(name="scenario", value=str(scenario_id))
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")


@app.websocket("/media")
async def media_stream(websocket: WebSocket) -> None:
    """Handle one Twilio Media Stream WebSocket for the lifetime of a call."""
    await websocket.accept()
    config = get_config()

    stream_sid: str | None = None
    call_sid: str = "unknown"
    scenario_id: str = config.scenario
    patient: PatientAgent | None = None
    recorder: CallRecorder | None = None
    detector = SilenceDetector()

    # While we are synthesizing / streaming a reply, ignore inbound audio so we
    # do not double-trigger on leftover echo or talk-over.
    busy = False

    async def handle_utterance(pcm_utterance: bytes) -> None:
        nonlocal busy
        if patient is None or recorder is None or stream_sid is None:
            busy = False
            return

        try:
            # 1) STT — what did Athena just say?
            text = await asyncio.to_thread(
                transcribe_pcm16,
                pcm_utterance,
                model_size=config.whisper_model_size,
                models_dir=config.models_dir,
            )
            if not text:
                logger.info("Empty transcript; skipping turn")
                return

            recorder.append_pcm16(pcm_utterance)
            recorder.log("agent", text)

            # 2) Patient LLM — what should we say next?
            reply = await asyncio.to_thread(patient.next_line, text)
            if not reply:
                return
            recorder.log("patient", reply)

            # 3) TTS → mu-law, then stream back to Twilio in small chunks.
            mulaw = await asyncio.to_thread(
                synthesize_mulaw,
                reply,
                api_key=config.elevenlabs_api_key,
                voice_id=config.elevenlabs_voice_id,
                model=config.elevenlabs_model,
            )
            if not mulaw:
                return

            # Keep a PCM copy for the call recording.
            recorder.append_pcm16(mulaw_to_pcm16(mulaw))

            for offset in range(0, len(mulaw), OUTBOUND_CHUNK_MULAW):
                chunk = mulaw[offset : offset + OUTBOUND_CHUNK_MULAW]
                # Pad final short frame so Twilio gets consistent timing.
                if len(chunk) < OUTBOUND_CHUNK_MULAW:
                    chunk = chunk + b"\xff" * (OUTBOUND_CHUNK_MULAW - len(chunk))
                payload = base64.b64encode(chunk).decode("ascii")
                await websocket.send_json(
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": payload},
                    }
                )
                # ~20 ms pacing so we do not dump the whole clip at once.
                await asyncio.sleep(0.02)

            # Mark lets us know (optionally) when Twilio finished playing.
            await websocket.send_json(
                {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "patient_done"},
                }
            )
        except Exception:
            logger.exception("Failed to handle utterance")
        finally:
            detector.reset()
            busy = False

    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            event = message.get("event")

            if event == "connected":
                logger.info("Media stream connected: %s", message.get("protocol"))

            elif event == "start":
                # start carries call/stream IDs and any <Parameter>s from TwiML.
                start = message["start"]
                stream_sid = message.get("streamSid") or start.get("streamSid")
                call_sid = start.get("callSid") or "unknown"
                custom = start.get("customParameters") or {}
                scenario_id = custom.get("scenario") or config.scenario

                scenario = get_scenario(config.scenarios_path, scenario_id)
                patient = PatientAgent(
                    scenario=scenario,
                    api_key=config.openai_api_key,
                    model=config.llm_model,
                )
                recorder = CallRecorder(
                    call_sid=call_sid,
                    recordings_dir=config.recordings_dir,
                    transcripts_dir=config.transcripts_dir,
                )
                detector.reset()
                logger.info(
                    "Stream started call=%s stream=%s scenario=%s",
                    call_sid,
                    stream_sid,
                    scenario_id,
                )

            elif event == "media":
                if busy or recorder is None:
                    continue
                payload_b64 = message["media"]["payload"]
                mulaw = base64.b64decode(payload_b64)
                pcm = mulaw_to_pcm16(mulaw)

                # Opportunistically keep quiet inbound in the recording only once
                # an utterance completes (we append full utterance there). Here we
                # only run silence detection.
                utterance = detector.feed(pcm)
                if utterance and not busy:
                    # Mark busy immediately to avoid overlapping turns.
                    busy = True
                    # Fire-and-forget so we keep reading the websocket.
                    asyncio.create_task(handle_utterance(utterance))

            elif event == "mark":
                logger.debug("Twilio mark: %s", message.get("mark"))

            elif event == "stop":
                logger.info("Stream stop for call %s", call_sid)
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for call %s", call_sid)
    finally:
        if recorder is not None:
            # Always persist audio + transcript first — analysis must not block this.
            _recording_path, transcript_path = recorder.save()
            try:
                analyze_transcript(transcript_path, recorder.call_sid)
            except Exception:
                logger.exception(
                    "Bug analysis failed for %s (recording/transcript already saved)",
                    recorder.call_sid,
                )
