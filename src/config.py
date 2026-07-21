"""Load and validate environment configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root (parent of src/)
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

REQUIRED_VARS = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    "PUBLIC_BASE_URL",
    "OPENAI_API_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
)


@dataclass(frozen=True)
class Config:
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from_number: str
    target_number: str
    public_base_url: str
    openai_api_key: str
    llm_model: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model: str
    whisper_model_size: str
    scenario: str
    recordings_dir: Path
    transcripts_dir: Path
    models_dir: Path
    scenarios_path: Path

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            twilio_from_number=os.getenv("TWILIO_FROM_NUMBER", ""),
            target_number=os.getenv("TARGET_NUMBER", "+18054398008"),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
            elevenlabs_model=os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
            whisper_model_size=os.getenv("WHISPER_MODEL_SIZE", "base"),
            scenario=os.getenv("SCENARIO", "schedule_appointment"),
            recordings_dir=ROOT / "recordings",
            transcripts_dir=ROOT / "transcripts",
            models_dir=ROOT / "models",
            scenarios_path=ROOT / "scenarios" / "scenarios.yaml",
        )

    def validate(self) -> None:
        missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
        if missing:
            raise ValueError(
                "Missing required environment variables: " + ", ".join(missing)
            )


def get_config(*, validate: bool = True) -> Config:
    config = Config.from_env()
    if validate:
        config.validate()
    return config
