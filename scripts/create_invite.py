"""Create a private demo invite without printing its bearer code.

Run from the repository root: python scripts/create_invite.py reviewer-1
Only the hash map goes into host secrets. Give each person their own code file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('person', help='Opaque ID, e.g. reviewer-1; avoid personal information')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.person):
        parser.error('Use 1–64 letters, numbers, underscores, or hyphens for the person ID.')
    folder = ROOT / '.runtime' / 'invite-setup'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    mapping_path = folder / 'invites.json'
    if mapping_path.is_symlink():
        parser.error('Refusing a symlink configuration file.')
    try:
        mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    except (ValueError, OSError):
        parser.error('Could not read the existing invite map; no credentials were changed.')
    if not isinstance(mapping, dict) or args.person in mapping or len(mapping) >= 100:
        parser.error('Person already exists or invite map is invalid/full; no credentials were changed.')
    code = secrets.token_urlsafe(32)
    code_path = folder / f'{args.person}.txt'
    try:
        fd = os.open(code_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        parser.error('Could not create a new private invite file; existing files were preserved.')
    with os.fdopen(fd, 'w') as output:
        output.write(code + '\n')
    mapping[args.person] = hashlib.sha256(code.encode()).hexdigest()
    # The map contains hashes only; keep it private to avoid accidental rotation.
    temp = mapping_path.with_suffix('.json.tmp')
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(mapping, output, sort_keys=True)
            output.write('\n')
        os.replace(temp, mapping_path)
    except OSError:
        print('Invite file created, but map update failed. No code was displayed. Check the private setup folder.', file=sys.stderr)
        return 1
    print(f'Private invite saved to {code_path.relative_to(ROOT)}')
    print(f'Hash-only host configuration saved to {mapping_path.relative_to(ROOT)}')
    print('Keep the invite file private. Neither file should be committed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
