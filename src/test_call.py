"""Place an outbound call that connects into our FastAPI Media Stream pipeline.

Prerequisites
-------------
1. Server running:  uvicorn src.server:app --host 0.0.0.0 --port 8000
2. Public HTTPS tunnel (ngrok etc.) pointed at that port
3. PUBLIC_BASE_URL in .env set to the tunnel URL (no trailing slash)
4. OPENAI_API_KEY + Twilio creds set

Usage::

    python -m src.test_call
    python -m src.test_call --scenario prescription_refill
"""

from __future__ import annotations

import argparse

from twilio.rest import Client

from src.config import get_config


def place_call(*, scenario: str | None = None):
    config = get_config(validate=True)
    scenario_id = scenario or config.scenario

    # Twilio will POST here when the callee answers; /voice returns <Connect><Stream>.
    voice_url = f"{config.public_base_url}/voice?scenario={scenario_id}"

    client = Client(config.twilio_account_sid, config.twilio_auth_token)
    call = client.calls.create(
        to=config.target_number,
        from_=config.twilio_from_number,
        url=voice_url,
        method="POST",
    )
    return call, scenario_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Place a QA call to Athena")
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario id from scenarios/scenarios.yaml (default: SCENARIO env)",
    )
    args = parser.parse_args()

    call, scenario_id = place_call(scenario=args.scenario)
    print(f"Scenario: {scenario_id}")
    print(f"Call SID: {call.sid}")
    print(f"Status:   {call.status}")
    print(f"Webhook:  check server logs for Media Stream events")


if __name__ == "__main__":
    main()
