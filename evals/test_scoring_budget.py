"""Bound hosted API input before client construction or any request."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import score


def test_oversized_prompt_never_constructs_api_client(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError('The API client must not be constructed for oversized input')
    monkeypatch.setattr(score, 'OpenAI', forbidden)
    sources = [{'url': 'https://example.com/policy', 'status': 'ok', 'text': '保管' * 25_000}]
    with pytest.raises(score.InputBudgetError):
        score.score(sources)


def test_small_prompt_uses_explicit_hosted_model_and_fixed_output_limit(monkeypatch):
    calls = []
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
    def complete(**kwargs):
        calls.append(kwargs)
        return response
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    monkeypatch.setenv('OPENAI_MODEL', 'ignored-administrator-default')
    findings, metadata = score.score([
        {'url': 'https://example.com/policy', 'status': 'ok', 'text': 'Customer data is deleted after 30 days.'},
    ], client=client, return_metadata=True, model='gpt-4o-mini')
    assert calls[0]['model'] == 'gpt-4o-mini'
    assert calls[0]['max_tokens'] == 1800
    assert 0 < metadata['prompt_bytes'] <= score.MAX_PROMPT_BYTES
    assert len(findings) == 8
