"""
Regression tests for the classifier's two correctness-critical properties:

1. _extract_json_object() must survive the exact failure mode that broke
   the old tool: Claude adding text after the closing '}' (with or without
   a markdown fence), which used to raise "Extra data" from json.loads().

2. Classifier.classify() must fail CLOSED: any API/parse error returns
   score=None (discard), never a guessed score. This is what "English jobs
   only" actually means in practice — the old bug's opposite (fail open)
   is exactly what let unverified/French jobs into the tracker before.
"""

from unittest.mock import MagicMock, patch

import pytest

from packages.core.models import NormalizedJob
from packages.scoring.classifier import Classifier, _extract_json_object, score_job


# ── score_job(): the two-tier rule ──────────────────────────────────────────

@pytest.mark.parametrize(
    "description_is_english,requires_fluent_english,expected",
    [
        (True, True, 1.0),
        (True, False, 0.5),
        (False, True, None),
        (False, False, None),
    ],
)
def test_score_job_tiers(description_is_english, requires_fluent_english, expected):
    assert score_job(description_is_english, requires_fluent_english) == expected


# ── _extract_json_object(): the exact regression cases from the old bug ────

def test_extract_json_clean():
    text = '{"description_is_english": true, "requires_fluent_english": false, "reason": "ok"}'
    assert _extract_json_object(text) == {
        "description_is_english": True, "requires_fluent_english": False, "reason": "ok",
    }


def test_extract_json_with_fence():
    text = '```json\n{"description_is_english": true, "requires_fluent_english": true, "reason": "ok"}\n```'
    result = _extract_json_object(text)
    assert result["description_is_english"] is True
    assert result["requires_fluent_english"] is True


def test_extract_json_trailing_text_after_close_brace():
    """This is the exact bug: Claude appends a sentence after '}', which
    used to raise json.JSONDecodeError('Extra data', ...) from json.loads().
    raw_decode() must parse the object and ignore the trailing text."""
    text = (
        '{"description_is_english": false, "requires_fluent_english": false, '
        '"reason": "French only"}\n\nNote: based on the job description provided.'
    )
    result = _extract_json_object(text)
    assert result["description_is_english"] is False
    assert result["requires_fluent_english"] is False


def test_extract_json_leading_prose_before_object():
    text = 'Here is my answer:\n{"description_is_english": true, "requires_fluent_english": true, "reason": "x"}'
    result = _extract_json_object(text)
    assert result["description_is_english"] is True


def test_extract_json_no_object_raises():
    with pytest.raises(ValueError):
        _extract_json_object("no json here at all")


# ── Classifier.classify(): fail-closed on API/parse error ──────────────────

def _make_job() -> NormalizedJob:
    return NormalizedJob(
        job_id="abc123", title="Data Analyst", company="Acme", location="Paris, France",
        url="https://example.com/job/1", description="We need a Data Analyst.",
        source="Adzuna", search_query="Data Analyst",
    )


def _fake_profile() -> dict:
    return {
        "profile_id": "test", "candidate_name": "Test User", "location": "France",
        "target_roles": ["Data Analyst"], "skills": [], "languages": {"English": "Native"},
    }


class _FakeContentBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeResponse:
    def __init__(self, text: str):
        self.content = [_FakeContentBlock(text)]
        self.usage = MagicMock(cache_read_input_tokens=0)


def test_classify_success_scores_correctly():
    clf = Classifier(api_key="sk-ant-fake", profile=_fake_profile())
    good_text = '{"description_is_english": true, "requires_fluent_english": true, "reason": "clear"}'
    with patch.object(clf.client.messages, "create", return_value=_FakeResponse(good_text)):
        result = clf.classify(_make_job())
    assert result.score == 1.0
    assert result.description_is_english is True
    assert result.requires_fluent_english is True


def test_classify_fails_closed_on_repeated_api_error():
    """Every attempt raises -> must return score=None, never a guessed value.
    This is the direct regression test for the old fail-open bug."""
    clf = Classifier(api_key="sk-ant-fake", profile=_fake_profile())
    with patch.object(clf.client.messages, "create", side_effect=RuntimeError("API is down")):
        result = clf.classify(_make_job())
    assert result.score is None
    assert "excluded" in result.reason.lower()


def test_classify_fails_closed_on_malformed_response():
    """Response parses as JSON-ish garbage / unparseable text after fence
    stripping -> still must discard, not default to True/0.5."""
    clf = Classifier(api_key="sk-ant-fake", profile=_fake_profile())
    with patch.object(clf.client.messages, "create", return_value=_FakeResponse("not json at all")):
        result = clf.classify(_make_job())
    assert result.score is None


def test_classify_recovers_on_second_attempt():
    """First attempt errors, second succeeds -> job should still be kept
    (the retry exists so a transient hiccup doesn't cost a real English job)."""
    clf = Classifier(api_key="sk-ant-fake", profile=_fake_profile())
    good_text = '{"description_is_english": true, "requires_fluent_english": false, "reason": "ok"}'
    with patch.object(
        clf.client.messages, "create",
        side_effect=[RuntimeError("transient"), _FakeResponse(good_text)],
    ):
        result = clf.classify(_make_job())
    assert result.score == 0.5
