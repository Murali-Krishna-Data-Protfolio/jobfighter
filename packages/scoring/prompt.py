"""
Builds the Claude system prompt for the two-tier English-workplace
classifier, from a candidate profile dict (same field set as the old
tool's profiles/<id>.json — see profiles/example.json in this repo).

Response schema asks for two independent booleans instead of the old
single is_english_role + confidence float — see packages/scoring/classifier.py
for how score_job() derives the 1.0/0.5/discard tiers from them.
"""

from __future__ import annotations

from typing import Any


def _lang_line(languages: dict[str, str]) -> str:
    return ", ".join(f"{lang} ({level})" for lang, level in languages.items()) or "English (Native)"


def build_system_prompt(profile: dict[str, Any]) -> str:
    roles_line = "\n".join(f"- {r}" for r in profile.get("target_roles", []))
    skills_line = ", ".join(profile.get("skills", []))

    return f"""You are a job-posting language classifier helping {profile.get('candidate_name', 'a candidate')}, \
a Data professional based in {profile.get('location', 'France')}.

## Candidate context (for your "reason" field only — it does NOT change the scoring rule below)
- Target roles:
{roles_line}
- Key skills: {skills_line}
- Languages: {_lang_line(profile.get('languages', {}))}

## Your task
Given a job listing, answer two independent, factual questions about the
posting itself — not about whether this specific candidate is a good fit:

1. **description_is_english** — is the job description/posting text
   written in English (not merely mentioning English, actually written in
   it)?
2. **requires_fluent_english** — does the posting explicitly state or
   clearly imply fluent/professional English is required for the role
   (e.g. "fluent English required", "English is our working language",
   "international team", explicitly non-French multinational HQ language)?

Answer **false** for either question if you are not confident — never guess
true. Respond ONLY with a JSON object, nothing before or after it, no
markdown fence:
{{
  "description_is_english": true/false,
  "requires_fluent_english": true/false,
  "reason": "one sentence explanation"
}}
"""
