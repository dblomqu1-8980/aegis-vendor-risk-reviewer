"""Best-effort single-instance demo budget; not an OpenAI billing limit."""
import sqlite3
import time
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / '.runtime' / 'demo-usage.sqlite3'
DAILY_LIMIT = 25

def reserve(path=DB, now=None, limit=DAILY_LIMIT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    day = int(time.time() if now is None else now) // 86400
    with sqlite3.connect(path, timeout=15) as db:
        db.execute('CREATE TABLE IF NOT EXISTS usage (day INTEGER PRIMARY KEY, requests INTEGER NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT requests FROM usage WHERE day=?', (day,)).fetchone()
        if row and row[0] >= limit:
            return False
        db.execute('INSERT INTO usage VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET requests=requests+1', (day,))
        db.execute('DELETE FROM usage WHERE day < ?', (day - 1,))
        return True
