"""Small invite-only demo guard. Hosted state may be lost when its host recycles.

Configuration comes only from trusted process environment, never a browser.
Invite hashes identify separate demo workspaces; sharing an invite also shares
that workspace. These request caps are not a hard monetary spending limit.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import base64
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from types import MappingProxyType
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
SESSION_SECONDS = 3600
MAX_INVITES = 100
_PRINCIPAL = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')


class ConfigError(ValueError):
    """An operator setting is missing or unsafe; messages never include values."""


class AuthenticationError(PermissionError):
    """A session expired or its invitation was revoked."""


class LimitError(RuntimeError):
    def __init__(self, message, reason, retry_after=None):
        super().__init__(message)
        self.reason = reason
        self.retry_after = retry_after


@dataclass(frozen=True)
class HostingConfig:
    mode: str
    data_dir: Path
    invites: Mapping[str, str] = field(repr=False)
    user_daily_limit: int = 3
    global_daily_limit: int = 20
    cooldown_seconds: int = 30
    auth_attempt_limit: int = 30
    auth_window_seconds: int = 60


@dataclass(frozen=True)
class AuthSession:
    principal_id: str
    invite_digest: str = field(repr=False)
    issued_at: float
    expires_at: float


def _integer(env, name, default, minimum, maximum):
    raw = env.get(name, str(default))
    if not isinstance(raw, str) or not re.fullmatch(r'[0-9]{1,6}', raw):
        raise ConfigError(f'{name} must be a bounded integer.')
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ConfigError(f'{name} is outside the allowed range.')
    return value


def load_config(env=None):
    """Load trusted settings. Missing hosting settings never enable local mode."""
    env = os.environ if env is None else env
    mode = env.get('AEGIS_MODE', 'hosted')
    if mode not in ('hosted', 'local'):
        raise ConfigError('AEGIS_MODE must be hosted or local.')
    raw_dir = env.get('AEGIS_DATA_DIR', str(ROOT / '.runtime' / 'hosted'))
    if not isinstance(raw_dir, str) or not raw_dir or len(raw_dir) > 4096 or '\0' in raw_dir:
        raise ConfigError('AEGIS_DATA_DIR must be an absolute directory path.')
    data_dir = Path(raw_dir)
    if not data_dir.is_absolute():
        raise ConfigError('AEGIS_DATA_DIR must be an absolute directory path.')

    invites = {}
    if mode == 'hosted':
        raw_invites = env.get('AEGIS_INVITES_JSON', '')
        if not isinstance(raw_invites, str) or not raw_invites or len(raw_invites) > 15000:
            raise ConfigError('Configure AEGIS_INVITES_JSON with individual invite hashes.')
        try:
            # Reject duplicate JSON names rather than silently replacing an invite.
            pairs = json.loads(raw_invites, object_pairs_hook=lambda values: values)
        except (ValueError, TypeError):
            raise ConfigError('AEGIS_INVITES_JSON must contain a bounded object of invite hashes.') from None
        if (not isinstance(pairs, list) or not 1 <= len(pairs) <= MAX_INVITES
                or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs)):
            raise ConfigError('AEGIS_INVITES_JSON must contain a bounded object of invite hashes.')
        for principal, digest in pairs:
            if (not isinstance(principal, str) or not _PRINCIPAL.fullmatch(principal)
                    or principal in invites or not isinstance(digest, str)
                    or not _DIGEST.fullmatch(digest) or digest in invites.values()):
                raise ConfigError('Invite identifiers and SHA256 hashes must be valid and unique.')
            invites[principal] = digest

    return HostingConfig(
        mode=mode, data_dir=data_dir, invites=MappingProxyType(invites),
        user_daily_limit=_integer(env, 'AEGIS_USER_DAILY_LIMIT', 3, 1, 1000),
        global_daily_limit=_integer(env, 'AEGIS_GLOBAL_DAILY_LIMIT', 20, 1, 10000),
        cooldown_seconds=_integer(env, 'AEGIS_COOLDOWN_SECONDS', 30, 0, 3600),
        auth_attempt_limit=_integer(env, 'AEGIS_AUTH_ATTEMPT_LIMIT', 30, 1, 300),
        auth_window_seconds=_integer(env, 'AEGIS_AUTH_WINDOW_SECONDS', 60, 1, 3600),
    )


def _require_hosted(config):
    if config.mode != 'hosted':
        raise ConfigError('Hosted guards require hosted mode.')


def control_connect(config):
    """Open the shared control database, separate from every review workspace."""
    _require_hosted(config)
    config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(config.data_dir / 'control.sqlite3', timeout=10, isolation_level=None)
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS auth_attempts (
            id INTEGER PRIMARY KEY, at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS auth_attempt_time ON auth_attempts(at);
        CREATE TABLE IF NOT EXISTS review_attempts (
            id INTEGER PRIMARY KEY, principal_id TEXT NOT NULL, at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS review_attempt_time ON review_attempts(at);
        CREATE INDEX IF NOT EXISTS review_attempt_owner ON review_attempts(principal_id, at);
    ''')
    return db


@contextmanager
def _transaction(db):
    # The write lock covers checking the cap and inserting the reservation.
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _now(now):
    value = time.time() if now is None else now
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('A valid current timestamp is required.')
    return float(value)


def _token_shape(code):
    if not isinstance(code, str) or not _TOKEN.fullmatch(code):
        return False
    try:
        decoded = base64.urlsafe_b64decode(code + '=')
    except (ValueError, TypeError):
        return False
    # Canonical 32-byte form plus rejection of obvious repeated placeholders.
    # Randomness is established when the operator generates invitations.
    return (len(decoded) == 32 and len(set(decoded)) >= 16
            and base64.urlsafe_b64encode(decoded).decode().rstrip('=') == code)


def _auth_slot(config, db, now):
    with _transaction(db):
        cutoff = now - config.auth_window_seconds
        db.execute('DELETE FROM auth_attempts WHERE at <= ?', (cutoff,))
        count = db.execute('SELECT count(*) FROM auth_attempts').fetchone()[0]
        if count >= config.auth_attempt_limit:
            raise LimitError('Too many sign-in attempts. Please try again later.', 'auth',
                             config.auth_window_seconds)
        # Invalid and valid attempts both consume a slot; codes are never stored.
        db.execute('INSERT INTO auth_attempts(at) VALUES(?)', (now,))


def authenticate(config, db, code, now=None):
    """Validate an invite without persisting its plaintext. Throttle all attempts."""
    _require_hosted(config)
    now = _now(now)
    _auth_slot(config, db, now)
    if not _token_shape(code):
        return None
    digest = hashlib.sha256(code.encode()).hexdigest()
    principal = None
    for identifier, expected in config.invites.items():
        # Always compare every configured hash, including after a match.
        if hmac.compare_digest(digest, expected):
            principal = identifier
    if principal is None:
        return None
    return AuthSession(principal, digest, now, now + SESSION_SECONDS)


def validate_session(config, session, now=None):
    """Recheck fixed expiry and current invitation hash on every app rerun."""
    if config.mode != 'hosted' or not isinstance(session, AuthSession):
        return False
    now = _now(now)
    if (type(session.issued_at) not in (int, float)
            or type(session.expires_at) not in (int, float)
            or not math.isfinite(session.issued_at) or not math.isfinite(session.expires_at)
            or session.expires_at != session.issued_at + SESSION_SECONDS
            or not session.issued_at <= now < session.expires_at
            or not isinstance(session.principal_id, str)
            or not _PRINCIPAL.fullmatch(session.principal_id)
            or not isinstance(session.invite_digest, str)
            or not _DIGEST.fullmatch(session.invite_digest)):
        return False
    expected = config.invites.get(session.principal_id)
    return expected is not None and hmac.compare_digest(session.invite_digest, expected)


def _authenticated(config, session, now):
    if not validate_session(config, session, now):
        raise AuthenticationError('Please sign in again to continue.')


def review_db_path(config, session, now=None):
    """Derive a workspace from validated server identity, never a client path/ID."""
    now = _now(now)
    _authenticated(config, session, now)
    namespace = hashlib.sha256(('aegis-demo-owner-v1\0' + session.principal_id).encode()).hexdigest()
    directory = config.data_dir / 'users'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / f'{namespace}.sqlite3'


def reserve_review(config, db, session, now=None):
    """Charge a review attempt before network work; failures are not refunded.

    Daily caps use UTC calendar days. Counters are shared across app sessions
    and connections but, on free hosting, can reset with the ephemeral disk.
    """
    now = _now(now)
    _authenticated(config, session, now)
    day_start = math.floor(now / 86400) * 86400
    with _transaction(db):
        # Only recent attempts are needed for these bounded rolling/daily checks.
        db.execute('DELETE FROM review_attempts WHERE at < ?', (day_start - 7 * 86400,))
        user_count = db.execute(
            'SELECT count(*) FROM review_attempts WHERE principal_id=? AND at>=?',
            (session.principal_id, day_start),
        ).fetchone()[0]
        global_count = db.execute(
            'SELECT count(*) FROM review_attempts WHERE at>=?', (day_start,),
        ).fetchone()[0]
        if user_count >= config.user_daily_limit:
            raise LimitError('Your daily demo review limit has been reached. Try again tomorrow.',
                             'user_daily', day_start + 86400 - now)
        if global_count >= config.global_daily_limit:
            raise LimitError('The demo daily review limit has been reached. Try again tomorrow.',
                             'global_daily', day_start + 86400 - now)
        last = db.execute('SELECT max(at) FROM review_attempts WHERE principal_id=?',
                          (session.principal_id,)).fetchone()[0]
        if last is not None and now - last < config.cooldown_seconds:
            raise LimitError('Please wait before creating another review.', 'cooldown',
                             math.ceil(config.cooldown_seconds - (now - last)))
        db.execute('INSERT INTO review_attempts(principal_id,at) VALUES(?,?)',
                   (session.principal_id, now))
