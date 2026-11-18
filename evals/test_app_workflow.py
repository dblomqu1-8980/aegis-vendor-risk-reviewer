"""Exercise human decisions in the local UI without API calls or credentials."""
import json
from pathlib import Path
import sqlite3
import sys

import dotenv
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import audit
from score import validate_findings


@pytest.fixture
def review_app(tmp_path, monkeypatch):
    monkeypatch.setenv('AEGIS_MODE', 'local')
    path = tmp_path / 'reviews.sqlite3'
    original_connect = audit.connect
    monkeypatch.setattr(audit, 'connect', lambda: original_connect(path))
    # These UI regressions deliberately never load the developer's local key.
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *args, **kwargs: False)
    db = audit.connect()
    for vendor in ('First fictional vendor', 'Second fictional vendor'):
        run = audit.create_run(db, vendor)
        audit.save_findings(db, run, validate_findings({}, []))
    db.close()
    app = AppTest.from_file(str(ROOT / 'src' / 'app.py'), default_timeout=15).run()
    assert not app.exception
    return app, path


def submit_decision(app):
    next(button for button in app.button if button.label == 'Record decision').click().run()
    assert not app.exception


def test_confirmation_and_note_are_specific_to_selected_review(review_app):
    app, _ = review_app
    assert app.selectbox[1].value == 2
    app.checkbox[0].check().run()
    app.text_input[0].set_value('Reviewed only the second vendor.').run()
    app.selectbox[1].select(1).run()
    assert app.checkbox[0].value is False
    assert app.text_input[0].value == ''


def test_unconfirmed_submission_keeps_draft_then_confirmed_approval_is_audited(review_app):
    app, path = review_app
    run = app.selectbox[1].value
    submit_decision(app)
    assert any('Confirm that you reviewed' in warning.value for warning in app.warning)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT status FROM runs WHERE id=?', (run,)).fetchone()[0] == 'Draft'
        assert db.execute("SELECT count(*) FROM events WHERE run_id=? AND step='decision'", (run,)).fetchone()[0] == 0

    app.text_input[0].set_value('Reviewed the disclosed gaps.').run()
    app.checkbox[0].check().run()
    submit_decision(app)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT status FROM runs WHERE id=?', (run,)).fetchone()[0] == 'Approved'
        decisions = db.execute("SELECT at,detail FROM events WHERE run_id=? AND step='decision'", (run,)).fetchall()
    assert len(decisions) == 1
    at, detail = decisions[0]
    assert json.loads(detail) == {'decision': 'Approved', 'comment': 'Reviewed the disclosed gaps.'}
    memo = '\n'.join(markdown.value for markdown in app.markdown)
    assert '**Status: Approved**' in memo
    assert at in memo and 'Reviewed the disclosed gaps.' in memo
    assert not any(button.label == 'Record decision' for button in app.button)


def test_confirmed_rejection_is_recorded_and_hides_decision_form(review_app):
    app, path = review_app
    run = app.selectbox[1].value
    app.radio[0].set_value('Reject').run()
    app.text_input[0].set_value('Insufficient evidence for this demo review.').run()
    app.checkbox[0].check().run()
    submit_decision(app)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT status FROM runs WHERE id=?', (run,)).fetchone()[0] == 'Rejected'
        decisions = db.execute("SELECT detail FROM events WHERE run_id=? AND step='decision'", (run,)).fetchall()
    assert len(decisions) == 1
    assert json.loads(decisions[0][0])['decision'] == 'Rejected'
    memo = '\n'.join(markdown.value for markdown in app.markdown)
    assert '**Status: Rejected**' in memo
    assert 'Insufficient evidence for this demo review.' in memo
    assert not any(button.label == 'Record decision' for button in app.button)
