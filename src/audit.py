"""Local SQLite audit trail; snapshots and status changes are kept together."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parents[1]/'.runtime'/'reviews.sqlite3'

def connect(path=DB):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=15)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, vendor TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL, findings TEXT NOT NULL DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id), at TEXT NOT NULL, step TEXT NOT NULL, detail TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sources (run_id INTEGER NOT NULL REFERENCES runs(id), url TEXT NOT NULL, status TEXT NOT NULL, content TEXT NOT NULL, sha256 TEXT, reason TEXT NOT NULL, truncated INTEGER NOT NULL DEFAULT 0);''')
    return db

def utc(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def event(db,run_id,step,detail): db.execute('INSERT INTO events(run_id,at,step,detail) VALUES(?,?,?,?)',(run_id,utc(),step,json.dumps(detail)))
def create_run(db,vendor):
    with db:
        cur=db.execute('INSERT INTO runs(vendor,created_at,status) VALUES(?,?,?)',(vendor,utc(),'Draft'))
        event(db,cur.lastrowid,'created',{'vendor':vendor})
    return cur.lastrowid

def record_sources(db,run_id,sources):
    with db:
        # Check state while acquiring a write lock, so a concurrent decision
        # cannot freeze the review between this check and the source inserts.
        cur=db.execute('UPDATE runs SET status=status WHERE id=? AND status=?',(run_id,'Draft'))
        if cur.rowcount != 1: raise ValueError('Review is no longer a draft or does not exist')
        for s in sources:
            db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?)',(run_id,s['url'],s['status'],s['text'],s['sha256'],s['reason'],int(s.get('truncated',False))))
            event(db,run_id,'fetch',{'url':s['url'],'status':s['status'],'reason':s['reason'],'sha256':s['sha256'],'truncated':s.get('truncated',False)})

def save_findings(db,run_id,findings,metadata=None):
    with db:
        cur=db.execute('UPDATE runs SET findings=? WHERE id=? AND status=?',(json.dumps([x.model_dump() for x in findings]),run_id,'Draft'))
        if cur.rowcount != 1: raise ValueError('Review is no longer a draft or does not exist')
        event(db,run_id,'score',{'criteria':len(findings),'metadata':metadata or {}})
        event(db,run_id,'draft',{'status':'Draft'})

def decide(db,run_id,decision,comment=''):
    if decision not in ('Approved','Rejected'): raise ValueError('Invalid decision')
    with db:
        cur=db.execute("UPDATE runs SET status=? WHERE id=? AND status=? AND findings != '[]'",(decision,run_id,'Draft'))
        if cur.rowcount!=1: raise ValueError('Review is no longer a draft or does not exist')
        event(db,run_id,'decision',{'decision':decision,'comment':comment[:500]})
