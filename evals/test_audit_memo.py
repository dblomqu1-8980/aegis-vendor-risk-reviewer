"""Regression checks for frozen review evidence and exported decisions."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import audit
from memo import render
from score import validate_findings


SOURCE = {
    'url': 'https://example.com/policy',
    'status': 'ok',
    'text': 'Fictional vendor source text.',
    'sha256': 'test-hash',
    'reason': '',
    'truncated': False,
}


@pytest.mark.parametrize('outcome', ['Approved', 'Rejected'])
def test_completed_review_evidence_and_decision_are_immutable(tmp_path, outcome):
    db = audit.connect(tmp_path / 'reviews.sqlite3')
    run = audit.create_run(db, 'Example vendor')
    audit.record_sources(db, run, [SOURCE])
    findings = validate_findings({}, [SOURCE])
    audit.save_findings(db, run, findings)
    audit.decide(db, run, outcome, 'Original review note')
    snapshot = '\n'.join(db.iterdump())

    for mutation in (
        lambda: audit.record_sources(db, run, [SOURCE]),
        lambda: audit.record_sources(db, run, []),
        lambda: audit.save_findings(db, run, findings),
        lambda: audit.decide(db, run, 'Rejected' if outcome == 'Approved' else 'Approved'),
    ):
        with pytest.raises(ValueError):
            mutation()
        assert '\n'.join(db.iterdump()) == snapshot

    events = db.execute('SELECT step,detail FROM events WHERE run_id=? ORDER BY id', (run,)).fetchall()
    assert [step for step, _ in events] == ['created', 'fetch', 'score', 'draft', 'decision']
    assert json.loads(events[-1][1]) == {'decision': outcome, 'comment': 'Original review note'}
    db.close()


def test_sources_require_existing_draft(tmp_path):
    db = audit.connect(tmp_path / 'reviews.sqlite3')
    with pytest.raises(ValueError):
        audit.record_sources(db, 99, [SOURCE])
    assert db.execute('SELECT count(*) FROM sources').fetchone()[0] == 0
    db.close()


def test_score_metadata_and_source_snapshot_survive_reopen(tmp_path):
    path = tmp_path / 'reviews.sqlite3'
    source = dict(SOURCE, sha256=hashlib.sha256(SOURCE['text'].encode()).hexdigest())
    metadata = {
        'model': 'gpt-4o-mini',
        'evidence_method': 'numbered-source-passages-v1',
        'statuses': {'met': 0, 'partial': 0, 'not met': 0, 'unknown': 8},
    }
    db = audit.connect(path)
    run = audit.create_run(db, 'Example vendor')
    audit.record_sources(db, run, [source])
    findings = validate_findings({}, [source])
    audit.save_findings(db, run, findings, metadata=metadata)
    db.close()

    reopened = audit.connect(path)
    score_detail = json.loads(reopened.execute(
        "SELECT detail FROM events WHERE run_id=? AND step='score'", (run,),
    ).fetchone()[0])
    assert score_detail == {'criteria': len(findings), 'metadata': metadata}
    assert sum(score_detail['metadata']['statuses'].values()) == len(findings)
    text, digest = reopened.execute(
        'SELECT content,sha256 FROM sources WHERE run_id=?', (run,),
    ).fetchone()
    assert text == source['text']
    assert digest == source['sha256'] == hashlib.sha256(text.encode()).hexdigest()
    fetch_detail = json.loads(reopened.execute(
        "SELECT detail FROM events WHERE run_id=? AND step='fetch'", (run,),
    ).fetchone()[0])
    assert fetch_detail['sha256'] == digest
    reopened.close()


def test_draft_memo_requires_human_review():
    memo = render('Example', 'Draft', [], [])
    assert '**Status: Draft**' in memo
    assert 'Human review required.' in memo
    assert 'Human review recorded:' not in memo


def test_source_paragraphs_cannot_create_memo_sections_or_active_markdown():
    memo = render('Example', 'Draft', [{
        'criterion': 'security', 'status': 'partial', 'summary': 'Needs review.',
        'quote': 'First public paragraph.\n\n# Source heading\n![image](https://example.com/image)',
        'url': 'https://example.com/policy',
    }], [])
    assert '> First public paragraph\\.\n> \n> \\# Source heading' in memo
    assert '\n# Source heading' not in memo
    assert '![image](' not in memo


@pytest.mark.parametrize('outcome', ['Approved', 'Rejected'])
def test_completed_memo_records_outcome_and_optional_audit_details(outcome):
    # Four-argument callers retain a useful outcome even without event metadata.
    memo = render('Example', outcome, [], [])
    assert f'Human review recorded: **{outcome}**.' in memo
    assert 'Human review required.' not in memo
    assert 'does not authorize vendor use' in memo

    memo = render('Example', outcome, [], [], decision={
        'at': '2026-11-17T12:00:00+00:00',
        'comment': 'Reviewed the gaps.\n# This is a review note',
    })
    assert 'Recorded at: 2026-11-17T12:00:00+00:00' in memo
    assert '> Reviewed the gaps.\n> # This is a review note' in memo
