"""Post-call bug analysis: score Athena (agent) lines only via OpenAI.

Runs automatically after each call's transcript is saved. Writes a per-call
markdown report and appends to a running consolidated bug_reports/bug_report.md.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from openai import OpenAI

from src.config import ROOT, get_config

logger = logging.getLogger(__name__)

BUG_REPORTS_DIR = ROOT / "bug_reports"
CONSOLIDATED_REPORT = BUG_REPORTS_DIR / "bug_report.md"

SYSTEM_PROMPT = """You are a QA reviewer for Pretty Good AI's Athena voice agent.

You will receive a timestamped phone-call transcript with lines labeled
"agent" (Athena / Pretty Good AI) and "patient" (a simulated caller used for
testing — NOT under review).

Your job:
- Evaluate ONLY the agent side. Never flag patient lines as bugs.
- Ignore garbled names, mid-word cutoffs, misspellings, or nonsensical short
  fragments that are likely speech-to-text artifacts from local Whisper STT,
  not real agent mistakes.
- Only flag clear logical, factual, or conversational failures by the agent
  (e.g. wrong info, ignoring the request, looping, hanging up prematurely,
  asking for something already provided, contradicting itself, failing the task).

Output format — if you find genuine issues, list each one exactly like this
(one block per issue, blank line between blocks):

Bug: [one line summary]
Severity: High/Medium/Low
Call: {call_sid}.txt at [timestamp from the transcript line, e.g. 53.62s]
Details: [what happened, why it's a problem, what should have happened]

If there are no genuine agent issues, return exactly this single line and nothing else:
No issues found
"""


def _count_issues(result: str) -> int:
    """How many Bug: blocks appear (0 if 'No issues found')."""
    text = (result or "").strip()
    if not text or text == "No issues found":
        return 0
    return len(re.findall(r"(?mi)^Bug:\s*", text))


def _append_consolidated(call_sid: str, result: str) -> None:
    """Append this call's section to bug_reports/bug_report.md (create if needed)."""
    BUG_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    body = (result or "").strip() or "No issues found"
    section = f"## Call: {call_sid}\n{body}\n\n"

    existing = ""
    if CONSOLIDATED_REPORT.exists():
        existing = CONSOLIDATED_REPORT.read_text()
        if existing and not existing.endswith("\n"):
            existing += "\n"

    CONSOLIDATED_REPORT.write_text(existing + section)


def analyze_transcript(transcript_path: Path | str, call_sid: str) -> str:
    """Analyze one call transcript; write per-call + consolidated reports.

    Returns the raw model output. Callers should wrap this in try/except so a
    failed analysis never blocks recording/transcript persistence.
    """
    transcript_path = Path(transcript_path)
    config = get_config(validate=False)
    if not config.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for bug analysis")

    transcript = transcript_path.read_text()
    if not transcript.strip():
        result = "No issues found"
    else:
        client = OpenAI(api_key=config.openai_api_key)
        system = SYSTEM_PROMPT.replace("{call_sid}", call_sid)
        response = client.chat.completions.create(
            model=config.llm_model or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"Call SID: {call_sid}\n"
                        f"Transcript file: {call_sid}.txt\n\n"
                        f"{transcript}"
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        result = (response.choices[0].message.content or "").strip()
        if not result:
            result = "No issues found"

    BUG_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    per_call_path = BUG_REPORTS_DIR / f"{call_sid}.md"
    per_call_path.write_text(result + ("\n" if not result.endswith("\n") else ""))
    logger.info("Wrote bug report %s", per_call_path)

    _append_consolidated(call_sid, result)

    n_issues = _count_issues(result)
    logger.info("Bug analysis complete for %s: %d issues found", call_sid, n_issues)
    return result
