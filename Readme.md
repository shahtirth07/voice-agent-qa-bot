# Voice Agent QA Bot

## Overview

This project is a Python voice bot for testing another voice AI agent over a real phone call. It places an outbound call through Twilio, role-plays realistic patient scenarios, records and transcribes both sides of the conversation, and automatically uses the completed transcript to generate a structured bug report about the target agent's behavior.

## Architecture

Twilio places the outbound call and carries bidirectional, 8 kHz mu-law audio through a Media Streams WebSocket served by FastAPI. Incoming speech is transcribed locally with `faster-whisper`; OpenAI (`gpt-4o-mini`) generates the simulated patient's next response; and ElevenLabs Flash synthesizes that response before it is converted back to Twilio's audio format. The same FastAPI/WebSocket pipeline records the call, writes its timestamped transcript, and starts post-call bug analysis.

## Prerequisites

- Python 3.11 or newer
- A Twilio account and voice-capable Twilio phone number
- An OpenAI API key
- An ElevenLabs API key and voice ID
- [ngrok](https://ngrok.com/) or another HTTPS/WSS tunnel to the local server
- `ffmpeg` available on `PATH` for MP3 export; without it, recording export falls back to WAV

## Setup

1. Clone the repository and enter it:

   ```bash
   git clone <repository-url>
   cd voice-agent-qa-bot
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   On Windows PowerShell:

   ```powershell
   .venv\Scripts\Activate.ps1
   ```

3. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create the local environment file:

   ```bash
   cp .env.example .env
   ```

   Fill in the real values in `.env`:

   ```dotenv
   TWILIO_ACCOUNT_SID=...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM_NUMBER=+1...
   TARGET_NUMBER=+1...
   PUBLIC_BASE_URL=https://YOUR_SUBDOMAIN.ngrok-free.app

   OPENAI_API_KEY=...
   LLM_MODEL=gpt-4o-mini

   ELEVENLABS_API_KEY=...
   ELEVENLABS_VOICE_ID=...
   ELEVENLABS_MODEL=eleven_flash_v2_5

   WHISPER_MODEL_SIZE=base
   SCENARIO=schedule_appointment
   ```

   Phone numbers must use E.164 format, such as `+18054398008`.

5. Expose port 8000:

   ```bash
   ngrok http 8000
   ```

   Copy ngrok's HTTPS forwarding URL into `PUBLIC_BASE_URL` in `.env`. Do not add `/voice` or `/media`; the application adds those paths itself.

## Running a Call

Start the FastAPI server:

```bash
python -m uvicorn src.server:app --host 0.0.0.0 --port 8000
```

Keep the server and ngrok running. In another terminal with the virtual environment activated, place a call:

```bash
python -m src.test_call --scenario schedule_appointment
```

Available scenario IDs are defined in [`scenarios/scenarios.yaml`](scenarios/scenarios.yaml):

- `schedule_appointment`
- `reschedule_appointment`
- `cancel_appointment`
- `prescription_refill`
- `hours_and_insurance`
- `edge_case_confused`
- `weekend_probe`
- `interruption_test`
- `multi_intent`
- `location_question`
- `third_party_caller`
- `safety_triage`
- `self_pay_pricing`
- `escalation_request`
- `indecisive_caller`
- `out_of_scope_request`

Omit `--scenario` to use the `SCENARIO` value from `.env`:

```bash
python -m src.test_call
```

The first call may take longer while `faster-whisper` downloads the selected model into the ignored `models/` directory.

## Output

Each completed call is identified by its Twilio call SID:

- `recordings/{call_sid}.mp3` contains the captured call audio. If MP3 export is unavailable, a WAV file is written instead.
- `transcripts/{call_sid}.txt` contains timestamped `agent` and `patient` turns.
- `bug_reports/{call_sid}.md` contains the automatic analysis for that call, including `No issues found` when applicable.
- `bug_reports/bug_report.md` is the running consolidated report across calls.

Bug analysis runs automatically after the recording and transcript have been saved. There is no separate analysis command or manual post-processing step. If analysis fails, the error is logged without discarding the saved recording or transcript.

## Project Structure

```text
voice-agent-qa-bot/
├── src/
│   ├── __init__.py          # Marks src as a Python package.
│   ├── config.py            # Loads and validates environment configuration.
│   ├── server.py            # FastAPI webhook and Twilio Media Stream WebSocket.
│   ├── test_call.py         # CLI for placing an outbound scenario call.
│   ├── audio_utils.py       # Mu-law/PCM conversion, resampling, and silence detection.
│   ├── stt.py               # Local faster-whisper transcription.
│   ├── patient_agent.py     # Scenario loading and OpenAI patient responses.
│   ├── tts.py               # ElevenLabs Flash TTS and Twilio audio conversion.
│   ├── recording.py         # Per-call audio and timestamped transcript persistence.
│   └── bug_analyzer.py      # Automatic OpenAI transcript analysis and report writing.
├── scenarios/
│   └── scenarios.yaml       # Patient personas, goals, and selectable scenario IDs.
├── recordings/              # Call audio, named by Twilio call SID.
├── transcripts/             # Timestamped call transcripts, named by call SID.
├── bug_reports/
│   ├── {call_sid}.md        # Per-call findings.
│   └── bug_report.md        # Consolidated findings from all analyzed calls.
├── requirements.txt         # Python dependencies.
├── .env.example             # Required environment-variable names and safe defaults.
└── README.md                # Setup, operation, and architecture documentation.
```


