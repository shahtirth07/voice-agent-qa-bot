"""Patient LLM: turn Athena's last line into the next patient utterance.

Persona + goal come from scenarios/scenarios.yaml. We keep a short chat
history per call so the patient stays consistent across turns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from openai import OpenAI

logger = logging.getLogger(__name__)


@dataclass
class Scenario:
    id: str
    persona: str
    goal: str


def load_scenarios(path: Path) -> dict[str, Scenario]:
    data = yaml.safe_load(path.read_text()) or {}
    scenarios: dict[str, Scenario] = {}
    for item in data.get("scenarios") or []:
        scenario = Scenario(
            id=item["id"],
            persona=item["persona"].strip(),
            goal=item["goal"].strip(),
        )
        scenarios[scenario.id] = scenario
    return scenarios


def get_scenario(path: Path, scenario_id: str) -> Scenario:
    scenarios = load_scenarios(path)
    if scenario_id not in scenarios:
        known = ", ".join(sorted(scenarios)) or "(none)"
        raise KeyError(f"Unknown scenario '{scenario_id}'. Known: {known}")
    return scenarios[scenario_id]


SYSTEM_TEMPLATE = """You are role-playing as a patient on a live phone call with a
medical clinic voice agent named Athena.

Persona:
{persona}

Your goal for this call:
{goal}

Rules:
- Reply with ONLY the next thing you say out loud on the phone.
- Keep each turn to 1-2 short sentences (phone-natural).
- Do not narrate actions, use stage directions, or wrap speech in quotes.
- If the agent asks a question, answer it when you can, then nudge toward your goal.
- If your goal is done, politely wrap up (e.g. "Thanks, that's all I needed. Bye.").
- Never break character or mention that you are an AI / test bot.
"""


@dataclass
class PatientAgent:
    """Stateful patient for one call."""

    scenario: Scenario
    api_key: str
    model: str
    history: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.history = [
            {
                "role": "system",
                "content": SYSTEM_TEMPLATE.format(
                    persona=self.scenario.persona,
                    goal=self.scenario.goal,
                ),
            }
        ]

    def next_line(self, agent_utterance: str) -> str:
        """Given what Athena just said, return the patient's next spoken line."""
        agent_utterance = (agent_utterance or "").strip()
        if not agent_utterance:
            return ""

        self.history.append({"role": "user", "content": f"Athena said: {agent_utterance}"})

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=self.history,
            temperature=0.7,
            max_tokens=120,
        )
        line = (response.choices[0].message.content or "").strip()
        # Strip accidental quotes some models add around spoken lines.
        if len(line) >= 2 and line[0] == line[-1] and line[0] in "\"'":
            line = line[1:-1].strip()

        self.history.append({"role": "assistant", "content": line})
        logger.info("Patient (%s): %s", self.scenario.id, line)
        return line
