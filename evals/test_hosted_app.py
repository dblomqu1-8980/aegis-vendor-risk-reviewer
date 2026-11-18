"""Exercise hosted privacy and spending guards with fictional, offline UI data."""
import base64
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import dotenv
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import audit
import fetch_public
import hosting
import score


def fictional_code(first_byte):
    return base64.urlsafe_b64encode(bytes(range(first_byte, first_byte + 32))).decode().rstrip('=')


CODES = {'reviewer-a': fictional_code(0), 'reviewer-b': fictional_code(32)}
INVITES = {owner: hashlib.sha256(code.encode()).hexdigest() for owner, code in CODES.items()}
NOTE_LABEL = 'Optional review note (do not enter sensitive information)'
CONFIRM_LABEL = 'I reviewed the findings and source quotations.'


def element(app, kind, label):
    return next(item for item in app.get(kind) if item.label == label)


def visible_text(app):
    return '\n'.join(str(item.value) for kind in ('markdown', 'text', 'json', 'caption', 'error', 'warning')
                     for item in app.get(kind))


def run(app):
    app.run()
    assert not app.exception, [item.message for item in app.exception]
    return app


def click(app, label):
    element(app, 'button', label).click()
    return run(app)


def sign_in(app, owner='reviewer-a'):
    element(app, 'text_input', 'Invite code').set_value(CODES[owner])
    click(app, 'Sign in')
    assert CODES[owner] not in str(app.session_state)
    # AppTest can retain the pre-rerun form in its delta tree when the newly
    # authenticated workspace is empty. A fresh server rerun discards that
    # obsolete tree without trying to resubmit its now-cleared widget state.
    app._run(widget_state=None)
    assert not app.exception
    return app


def source_fixture(marker):
    text = f'{marker}_SOURCE: The fictional vendor encrypts customer data in transit and at rest.'
    return {'url': f'https://example.test/{marker.lower()}', 'status': 'ok', 'text': text,
            'sha256': hashlib.sha256(text.encode()).hexdigest(), 'reason': '', 'truncated': False}


def findings_fixture(source):
    return [score.Finding(criterion='security', status='met', summary=source['text'],
                          url=source['url'], quote=source['text'], summary_mode='source_excerpt',
                          evidence=[score.Evidence(url=source['url'], quote=source['text'])])]


@pytest.fixture
def hosted_ui(tmp_path, monkeypatch):
    # Never load the developer's dotenv or Streamlit secrets during these tests.
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *args, **kwargs: False)
    monkeypatch.setenv('AEGIS_MODE', 'hosted')
    monkeypatch.setenv('AEGIS_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('AEGIS_INVITES_JSON', json.dumps(INVITES))
    monkeypatch.setenv('AEGIS_COOLDOWN_SECONDS', '0')
    monkeypatch.setenv('AEGIS_USER_DAILY_LIMIT', '3')
    monkeypatch.setenv('AEGIS_GLOBAL_DAILY_LIMIT', '20')
    monkeypatch.setenv('AEGIS_AUTH_ATTEMPT_LIMIT', '30')
    monkeypatch.setenv('AEGIS_AUTH_WINDOW_SECONDS', '60')
    monkeypatch.setenv('OPENAI_API_KEY', 'fictional-test-key-not-valid')
    fetched = source_fixture('NEW_REVIEW')
    fetch = Mock(return_value=[fetched])
    model = Mock(return_value=(findings_fixture(fetched), {'evidence_method': 'test_fixture'}))
    monkeypatch.setattr(fetch_public, 'fetch_sources', fetch)
    monkeypatch.setattr(score, 'score', model)
    # Catch any fallback to the existing local DB, including a default argument
    # captured before monkeypatching. Only hashed per-user paths are permitted.
    original_connect = audit.connect
    connections = []
    sentinel = object()

    def connect(path=sentinel):
        assert path is not sentinel, 'Hosted UI attempted to open the shared local history'
        path = Path(path).resolve()
        assert path.parent == tmp_path / 'users', 'Hosted UI opened a non-user review DB'
        connections.append(path)
        return original_connect(path)

    monkeypatch.setattr(audit, 'connect', connect)

    def app():
        tested = AppTest.from_file(str(ROOT / 'src' / 'app.py'), default_timeout=15)
        # A nonempty fixture replaces st.secrets rather than consulting a real file.
        tested.secrets = {'fictional_test_fixture': True}
        return run(tested)

    def session(owner):
        config = hosting.load_config()
        with closing(hosting.control_connect(config)) as db:
            authenticated = hosting.authenticate(config, db, CODES[owner])
        assert authenticated is not None
        return authenticated

    def seed(owner, marker, count=1):
        config = hosting.load_config()
        path = hosting.review_db_path(config, session(owner))
        ids = []
        with closing(connect(path)) as db:
            for index in range(count):
                run_id = audit.create_run(db, f'{marker}_VENDOR_{index + 1}')
                source = source_fixture(marker)
                audit.record_sources(db, run_id, [source])
                audit.save_findings(db, run_id, findings_fixture(source))
                with db:
                    audit.event(db, run_id, 'fixture', {'note': f'{marker}_AUDIT'})
                ids.append(run_id)
        return path, ids

    return SimpleNamespace(app=app, session=session, seed=seed, connections=connections,
                           fetch=fetch, model=model, data_dir=tmp_path)


def assert_no_review_access(app, fixture):
    assert not app.selectbox
    assert not app.get('download_button')
    assert not any(button.label == 'Create draft review' for button in app.button)
    assert not fixture.connections
    fixture.fetch.assert_not_called()
    fixture.model.assert_not_called()


def test_unauthenticated_visitor_cannot_read_sources_reviews_or_call_services(hosted_ui):
    app = hosted_ui.app()
    invite = element(app, 'text_input', 'Invite code')
    assert invite.proto.type == invite.proto.PASSWORD
    assert app.get('form')[0].proto.form.clear_on_submit
    assert 'https://' not in visible_text(app)
    assert_no_review_access(app, hosted_ui)


@pytest.mark.parametrize('invites', [None, '', '{}', 'not json', '{"reviewer-a":"bad-digest"}'])
def test_missing_or_invalid_hosted_configuration_fails_closed(hosted_ui, monkeypatch, invites):
    # Omitting the mode must retain the secure hosted default.
    monkeypatch.delenv('AEGIS_MODE')
    if invites is None:
        monkeypatch.delenv('AEGIS_INVITES_JSON')
    else:
        monkeypatch.setenv('AEGIS_INVITES_JSON', invites)
    app = hosted_ui.app()
    assert any('not accepting sign-ins' in item.value for item in app.error)
    assert not app.text_input
    assert_no_review_access(app, hosted_ui)


def test_invalid_invite_keeps_review_data_and_services_inaccessible(hosted_ui):
    app = hosted_ui.app()
    element(app, 'text_input', 'Invite code').set_value(fictional_code(64))
    click(app, 'Sign in')
    assert any('not recognized' in item.value for item in app.error)
    assert 'aegis_auth' not in app.session_state
    assert_no_review_access(app, hosted_ui)


def test_successful_login_removes_invite_widget_and_raw_code_from_state(hosted_ui):
    app = sign_in(hosted_ui.app())
    assert app.session_state['aegis_auth'].principal_id == 'reviewer-a'
    assert not any(item.label == 'Invite code' for item in app.text_input)
    assert all(CODES['reviewer-a'] not in str(value)
               for value in app.session_state.filtered_state.values())
    assert 'saved reviews can reset' in visible_text(app)
    assert 'Download your memo' in visible_text(app)
    hosted_ui.fetch.assert_not_called()
    hosted_ui.model.assert_not_called()


def test_two_invites_only_render_their_own_memos_sources_and_audit(hosted_ui):
    a_path, _ = hosted_ui.seed('reviewer-a', 'A_ONLY')
    b_path, _ = hosted_ui.seed('reviewer-b', 'B_ONLY')
    assert a_path != b_path
    hosted_ui.connections.clear()
    for owner, own_marker, other_marker, expected_path in (
        ('reviewer-a', 'A_ONLY', 'B_ONLY', a_path),
        ('reviewer-b', 'B_ONLY', 'A_ONLY', b_path),
    ):
        app = sign_in(hosted_ui.app(), owner)
        text = visible_text(app)
        assert f'{own_marker}_VENDOR' in text
        assert f'{own_marker}_SOURCE' in text
        assert f'{own_marker}_AUDIT' in text
        assert other_marker not in text
        assert len(app.get('download_button')) == 1
        assert set(hosted_ui.connections) == {expected_path}
        hosted_ui.connections.clear()
    hosted_ui.fetch.assert_not_called()
    hosted_ui.model.assert_not_called()


def test_logout_clears_review_note_confirmation_and_selected_state(hosted_ui):
    hosted_ui.seed('reviewer-a', 'A_ONLY', count=2)
    app = sign_in(hosted_ui.app())
    element(app, 'selectbox', 'Open a review').select(1)
    run(app)
    element(app, 'text_input', NOTE_LABEL).set_value('A_ONLY_PRIVATE_NOTE')
    element(app, 'checkbox', CONFIRM_LABEL).check()
    run(app)
    app.session_state['run_id'] = 1
    app.session_state['review_selection'] = 'A_ONLY_SELECTION'
    click(app, 'Sign out')
    assert 'aegis_auth' not in app.session_state
    assert 'run_id' not in app.session_state
    assert 'review_selection' not in app.session_state
    assert CODES['reviewer-a'] not in str(app.session_state.filtered_state)
    assert 'A_ONLY_PRIVATE_NOTE' not in str(app.session_state.filtered_state)
    assert not app.selectbox
    assert not app.get('download_button')


def test_switching_users_cannot_reuse_foreign_selection_or_decide_foreign_review(hosted_ui):
    a_path, a_ids = hosted_ui.seed('reviewer-a', 'A_ONLY', count=2)
    b_path, b_ids = hosted_ui.seed('reviewer-b', 'B_ONLY')
    app = sign_in(hosted_ui.app())
    element(app, 'text_input', NOTE_LABEL).set_value('A_ONLY_PRIVATE_NOTE')
    element(app, 'checkbox', CONFIRM_LABEL).check()
    run(app)
    click(app, 'Sign out')
    sign_in(app, 'reviewer-b')
    # Even a stale run identifier from A is interpreted only in B's database.
    app.session_state['run_id'] = a_ids[-1]
    run(app)
    assert element(app, 'selectbox', 'Open a review').value == b_ids[0]
    assert element(app, 'text_input', NOTE_LABEL).value == ''
    assert element(app, 'checkbox', CONFIRM_LABEL).value is False
    assert 'A_ONLY' not in visible_text(app)
    element(app, 'text_input', NOTE_LABEL).set_value('B_ONLY_APPROVAL_NOTE')
    element(app, 'checkbox', CONFIRM_LABEL).check()
    click(app, 'Record decision')
    with sqlite3.connect(a_path) as db:
        assert db.execute('SELECT DISTINCT status FROM runs').fetchall() == [('Draft',)]
        assert db.execute("SELECT count(*) FROM events WHERE step='decision'").fetchone()[0] == 0
    with sqlite3.connect(b_path) as db:
        assert db.execute('SELECT status FROM runs WHERE id=?', (b_ids[0],)).fetchone()[0] == 'Approved'
        detail = json.loads(db.execute("SELECT detail FROM events WHERE step='decision'").fetchone()[0])
        assert detail['comment'] == 'B_ONLY_APPROVAL_NOTE'
    assert 'A_ONLY' not in visible_text(app)


def test_quota_rejection_precedes_run_creation_fetching_and_model_calls(hosted_ui, monkeypatch):
    monkeypatch.setenv('AEGIS_USER_DAILY_LIMIT', '1')
    app = sign_in(hosted_ui.app())
    config = hosting.load_config()
    session = app.session_state['aegis_auth']
    with closing(hosting.control_connect(config)) as control:
        hosting.reserve_review(config, control, session)
    click(app, 'Create draft review')
    assert app.warning
    hosted_ui.fetch.assert_not_called()
    hosted_ui.model.assert_not_called()
    with sqlite3.connect(hosting.review_db_path(config, session)) as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_valid_invite_can_generate_download_and_audit_a_mock_review(hosted_ui):
    app = sign_in(hosted_ui.app())
    click(app, 'Create draft review')
    hosted_ui.fetch.assert_called_once()
    hosted_ui.model.assert_called_once_with(hosted_ui.fetch.return_value,
                                            return_metadata=True, model='gpt-4o-mini')
    text = visible_text(app)
    assert 'NEW_REVIEW_SOURCE' in text
    assert 'test_fixture' in text
    assert len(app.get('download_button')) == 1
    assert element(app, 'selectbox', 'Open a review').value == 1


@pytest.mark.parametrize('change', ['expired', 'revoked'])
def test_expired_or_revoked_identity_clears_private_review_state(hosted_ui, monkeypatch, change):
    hosted_ui.seed('reviewer-a', 'A_ONLY')
    app = sign_in(hosted_ui.app())
    element(app, 'text_input', NOTE_LABEL).set_value('A_ONLY_PRIVATE_NOTE')
    run(app)
    app.session_state['run_id'] = 1
    if change == 'expired':
        now = time.time()
        app.session_state['aegis_auth'] = replace(app.session_state['aegis_auth'],
                                                 issued_at=now - 7200, expires_at=now - 3600)
    else:
        monkeypatch.setenv('AEGIS_INVITES_JSON', json.dumps({'reviewer-b': INVITES['reviewer-b']}))
    run(app)
    assert 'aegis_auth' not in app.session_state
    assert 'run_id' not in app.session_state
    assert 'A_ONLY' not in visible_text(app)
    assert 'A_ONLY_PRIVATE_NOTE' not in str(app.session_state.filtered_state)
    assert not app.selectbox
    assert not app.get('download_button')
    assert element(app, 'text_input', 'Invite code').value == ''
    hosted_ui.fetch.assert_not_called()
    hosted_ui.model.assert_not_called()


def test_missing_api_configuration_disables_generation_but_keeps_own_download(hosted_ui, monkeypatch):
    hosted_ui.seed('reviewer-a', 'A_ONLY')
    monkeypatch.delenv('OPENAI_API_KEY')
    app = sign_in(hosted_ui.app())
    assert element(app, 'button', 'Create draft review').disabled
    assert 'A_ONLY_SOURCE' in visible_text(app)
    assert len(app.get('download_button')) == 1
    hosted_ui.fetch.assert_not_called()
    hosted_ui.model.assert_not_called()
