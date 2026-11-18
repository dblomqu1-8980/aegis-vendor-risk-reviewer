"""Invite provisioning keeps bearer codes private and preserves existing invites."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('create_invite', ROOT / 'scripts' / 'create_invite.py')
create_invite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(create_invite)


def test_generated_invite_matches_hash_without_printing_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(create_invite, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['create_invite.py', 'reviewer-1'])
    assert create_invite.main() == 0
    folder = tmp_path / '.runtime' / 'invite-setup'
    code = (folder / 'reviewer-1.txt').read_text().strip()
    mapping = json.loads((folder / 'invites.json').read_text())
    assert mapping == {'reviewer-1': hashlib.sha256(code.encode()).hexdigest()}
    assert len(code) == 43
    assert code not in capsys.readouterr().out
    if os.name == 'posix':
        assert (folder / 'reviewer-1.txt').stat().st_mode & 0o777 == 0o600
        assert (folder / 'invites.json').stat().st_mode & 0o777 == 0o600
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    with pytest.raises(SystemExit):
        create_invite.main()
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before


def test_invite_id_cannot_escape_private_setup_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(create_invite, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['create_invite.py', '../outside'])
    with pytest.raises(SystemExit):
        create_invite.main()
    assert not list(tmp_path.iterdir())
