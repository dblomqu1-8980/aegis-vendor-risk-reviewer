"""Invite/session isolation and atomic demo limits; no keys or network calls."""
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from threading import Barrier

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import hosting


NOW = 1_750_000_000


def token(seed=0):
    # Deliberately fictional, deterministic credentials confined to test storage.
    return base64.urlsafe_b64encode(bytes((seed + i) % 256 for i in range(32))).decode().rstrip('=')


def digest(code):
    return hashlib.sha256(code.encode()).hexdigest()


def config(tmp_path, **settings):
    env = {'AEGIS_DATA_DIR': str(tmp_path / 'hosted'),
           'AEGIS_INVITES_JSON': json.dumps({'invite-a': digest(token()), 'invite-b': digest(token(32))})}
    env.update(settings)
    return hosting.load_config(env)


def login(cfg, db, seed=0, now=NOW):
    session = hosting.authenticate(cfg, db, token(seed), now=now)
    assert session is not None
    return session


def test_missing_config_fails_closed_and_local_mode_is_explicit(tmp_path):
    with pytest.raises(hosting.ConfigError):
        hosting.load_config({})
    with pytest.raises(hosting.ConfigError):
        hosting.load_config({'AEGIS_MODE': 'development'})
    local = hosting.load_config({'AEGIS_MODE': 'local', 'AEGIS_DATA_DIR': str(tmp_path)})
    assert local.mode == 'local'
    with pytest.raises(hosting.ConfigError):
        hosting.control_connect(local)


@pytest.mark.parametrize('raw', [
    '', 'not-json', 'null', '[]', '"string"',
    json.dumps([['invite-a', digest(token())]]),
    json.dumps({'../another-workspace': digest(token())}),
    json.dumps({'person@example.com': digest(token())}),
    json.dumps({'x' * 65: digest(token())}),
    json.dumps({'invite-a': 'not-a-sha256'}),
    json.dumps({'invite-a': digest(token()).upper()}),
    json.dumps({'invite-a': {'digest': digest(token())}}),
    json.dumps({'invite-a': digest(token()), 'invite-b': digest(token())}),
    '{"invite-a":"' + digest(token()) + '","invite-a":"' + digest(token(32)) + '"}',
    json.dumps({f'invite-{i}': hashlib.sha256(str(i).encode()).hexdigest() for i in range(101)}),
])
def test_malformed_duplicate_or_oversized_invitation_config_is_rejected(tmp_path, raw):
    with pytest.raises(hosting.ConfigError) as caught:
        config(tmp_path, AEGIS_INVITES_JSON=raw)
    if len(raw) > 10:
        assert raw not in str(caught.value)


@pytest.mark.parametrize('settings', [
    {'AEGIS_USER_DAILY_LIMIT': '0'}, {'AEGIS_GLOBAL_DAILY_LIMIT': '-1'},
    {'AEGIS_AUTH_ATTEMPT_LIMIT': 'unlimited'}, {'AEGIS_COOLDOWN_SECONDS': '0.5'},
    {'AEGIS_AUTH_WINDOW_SECONDS': '999999'}, {'AEGIS_DATA_DIR': '../shared-db'},
])
def test_limit_and_storage_settings_fail_closed(tmp_path, settings):
    with pytest.raises(hosting.ConfigError):
        config(tmp_path, **settings)


def test_config_and_session_representations_do_not_include_invite_material(tmp_path):
    cfg = config(tmp_path)
    db = hosting.control_connect(cfg)
    session = login(cfg, db)
    assert token() not in repr(cfg) + repr(session)
    assert digest(token()) not in repr(cfg) + repr(session)
    assert token() not in '\n'.join(db.iterdump())
    db.close()


def test_authentication_checks_all_configured_digests_in_constant_time(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    db = hosting.control_connect(cfg)
    compared = []
    original = hosting.hmac.compare_digest

    def compare(left, right):
        compared.append(right)
        return original(left, right)

    monkeypatch.setattr(hosting.hmac, 'compare_digest', compare)
    session = login(cfg, db)
    assert session.principal_id == 'invite-a'
    assert compared == list(cfg.invites.values())
    assert session.expires_at - session.issued_at == hosting.SESSION_SECONDS == 3600
    db.close()


@pytest.mark.parametrize('code', ['', 'replace-me', 'A' * 43, token() + '=', token() + ' ', '../path', token(96)])
def test_weak_malformed_and_unlisted_invites_do_not_authenticate(tmp_path, code):
    cfg = config(tmp_path)
    db = hosting.control_connect(cfg)
    assert hosting.authenticate(cfg, db, code, now=NOW) is None
    assert db.execute('SELECT count(*) FROM auth_attempts').fetchone()[0] == 1
    db.close()


def test_global_auth_throttle_counts_failures_persists_and_expires(tmp_path):
    cfg = config(tmp_path, AEGIS_AUTH_ATTEMPT_LIMIT='2')
    db = hosting.control_connect(cfg)
    assert hosting.authenticate(cfg, db, 'invalid', now=NOW) is None
    login(cfg, db, now=NOW)
    db.close()
    db = hosting.control_connect(cfg)
    with pytest.raises(hosting.LimitError) as caught:
        login(cfg, db, now=NOW + 1)
    assert caught.value.reason == 'auth'
    assert hosting.authenticate(cfg, db, token(), now=NOW + 60) is not None
    db.close()


def test_expiry_is_fixed_and_removing_or_rotating_an_invite_revokes_sessions(tmp_path):
    cfg = config(tmp_path)
    db = hosting.control_connect(cfg)
    session = login(cfg, db)
    assert hosting.validate_session(cfg, session, now=NOW + 3599)
    assert not hosting.validate_session(cfg, session, now=NOW + 3600)
    assert not hosting.validate_session(cfg, session, now=NOW - 1)
    assert not hosting.validate_session(cfg, replace(session, expires_at=session.expires_at + 1), now=NOW)
    assert not hosting.validate_session(cfg, {'principal_id': 'invite-a'}, now=NOW)
    for invites in ({'invite-b': digest(token(32))},
                    {'invite-a': digest(token(64)), 'invite-b': digest(token(32))}):
        changed = config(tmp_path, AEGIS_INVITES_JSON=json.dumps(invites))
        assert not hosting.validate_session(changed, session, now=NOW)
        with pytest.raises(hosting.AuthenticationError):
            hosting.review_db_path(changed, session, now=NOW)
        with pytest.raises(hosting.AuthenticationError):
            hosting.reserve_review(changed, db, session, now=NOW)
    assert db.execute('SELECT count(*) FROM review_attempts').fetchone()[0] == 0
    db.close()


def test_per_principal_paths_are_derived_isolated_and_stable_across_invite_rotation(tmp_path):
    cfg = config(tmp_path)
    db = hosting.control_connect(cfg)
    first, second = login(cfg, db), login(cfg, db, 32)
    first_path = hosting.review_db_path(cfg, first, now=NOW)
    second_path = hosting.review_db_path(cfg, second, now=NOW)
    assert first_path != second_path
    assert first_path.parent == second_path.parent == cfg.data_dir / 'users'
    assert len(first_path.stem) == 64
    assert first.principal_id not in str(first_path)
    assert first_path != Path(hosting.ROOT) / '.runtime' / 'reviews.sqlite3'
    with pytest.raises(hosting.AuthenticationError):
        hosting.review_db_path(cfg, replace(first, principal_id='../../outside'), now=NOW)
    with pytest.raises(hosting.AuthenticationError):
        hosting.review_db_path(cfg, replace(first, principal_id='invite-b'), now=NOW)
    with pytest.raises(hosting.AuthenticationError):
        hosting.review_db_path(cfg, str(second_path), now=NOW)
    rotated = config(tmp_path, AEGIS_INVITES_JSON=json.dumps({'invite-a': digest(token(64))}))
    replacement = login(rotated, db, 64)
    assert hosting.review_db_path(rotated, replacement, now=NOW) == first_path
    db.close()


def test_cooldown_boundary_and_per_user_daily_cap_survive_reopen(tmp_path):
    cfg = config(tmp_path)
    db = hosting.control_connect(cfg)
    session = login(cfg, db)
    hosting.reserve_review(cfg, db, session, now=NOW)
    with pytest.raises(hosting.LimitError) as caught:
        hosting.reserve_review(cfg, db, session, now=NOW + 29)
    assert caught.value.reason == 'cooldown'
    assert caught.value.retry_after == 1
    hosting.reserve_review(cfg, db, session, now=NOW + 30)
    hosting.reserve_review(cfg, db, session, now=NOW + 60)
    db.close()
    db = hosting.control_connect(cfg)
    with pytest.raises(hosting.LimitError) as caught:
        hosting.reserve_review(cfg, db, session, now=NOW + 90)
    assert caught.value.reason == 'user_daily'
    assert db.execute('SELECT count(*) FROM review_attempts').fetchone()[0] == 3
    db.close()


def test_global_daily_cap_is_shared_and_resets_at_utc_day_boundary(tmp_path):
    cfg = config(tmp_path, AEGIS_GLOBAL_DAILY_LIMIT='2', AEGIS_COOLDOWN_SECONDS='0')
    db = hosting.control_connect(cfg)
    first, second = login(cfg, db), login(cfg, db, 32)
    hosting.reserve_review(cfg, db, first, now=NOW)
    hosting.reserve_review(cfg, db, second, now=NOW)
    with pytest.raises(hosting.LimitError) as caught:
        hosting.reserve_review(cfg, db, first, now=NOW + 1)
    assert caught.value.reason == 'global_daily'
    next_day = (NOW // 86400 + 1) * 86400
    fresh = login(cfg, db, now=next_day)
    hosting.reserve_review(cfg, db, fresh, now=next_day)
    db.close()


def test_failed_work_after_reservation_does_not_refund_attempt(tmp_path):
    cfg = config(tmp_path, AEGIS_USER_DAILY_LIMIT='1', AEGIS_COOLDOWN_SECONDS='0')
    db = hosting.control_connect(cfg)
    session = login(cfg, db)
    hosting.reserve_review(cfg, db, session, now=NOW)
    # A network timeout after this point could still have incurred API charges.
    with pytest.raises(RuntimeError):
        raise RuntimeError('Fictional downstream failure')
    with pytest.raises(hosting.LimitError) as caught:
        hosting.reserve_review(cfg, db, session, now=NOW + 1)
    assert caught.value.reason == 'user_daily'
    db.close()


@pytest.mark.parametrize('limit_kind', ['global', 'user', 'auth'])
def test_attempt_reservation_is_atomic_across_concurrent_connections(tmp_path, limit_kind):
    settings = {'AEGIS_COOLDOWN_SECONDS': '0'}
    if limit_kind == 'global':
        settings['AEGIS_GLOBAL_DAILY_LIMIT'] = '1'
    elif limit_kind == 'user':
        settings['AEGIS_USER_DAILY_LIMIT'] = '1'
    else:
        settings['AEGIS_AUTH_ATTEMPT_LIMIT'] = '1'
    cfg = config(tmp_path, **settings)
    db = hosting.control_connect(cfg)
    if limit_kind == 'auth':
        sessions = [None, None]
    else:
        sessions = [login(cfg, db), login(cfg, db, 32 if limit_kind == 'global' else 0)]
    db.close()
    barrier = Barrier(2)

    def attempt(index):
        connection = hosting.control_connect(cfg)
        try:
            barrier.wait(timeout=10)
            if limit_kind == 'auth':
                hosting.authenticate(cfg, connection, 'invalid', now=NOW)
            else:
                hosting.reserve_review(cfg, connection, sessions[index], now=NOW)
            return 'reserved'
        except hosting.LimitError as error:
            return error.reason
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [0, 1]))
    expected_reason = {'global': 'global_daily', 'user': 'user_daily', 'auth': 'auth'}[limit_kind]
    assert sorted(results) == sorted(['reserved', expected_reason])
    db = hosting.control_connect(cfg)
    table = 'auth_attempts' if limit_kind == 'auth' else 'review_attempts'
    assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 1
    db.close()
