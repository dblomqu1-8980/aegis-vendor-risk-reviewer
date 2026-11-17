from pathlib import Path
from types import SimpleNamespace
import sys
import httpx
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import audit
from fetch_public import fetch_sources
from score import validate_findings, score
from memo import render

URL='https://example.com/policy'
TEXT='Business customer data is not used for training by default. Data is retained for 30 days.'
SOURCES=[{'url':URL,'status':'ok','text':TEXT,'sha256':'abc','reason':'','truncated':False}]

def test_exact_evidence_and_unknown_for_silent_assurance():
    result=validate_findings({'findings':[{'criterion':'training','status':'met','summary':'No training by default','url':URL,'quote':'Business customer data is not used for training by default.'}]},SOURCES)
    by={f.criterion:f for f in result}
    assert by['training'].status=='met'
    assert by['assurance'].status=='unknown'
    assert 'SOC 2' not in by['assurance'].summary

def test_fake_quote_or_wrong_url_becomes_unknown():
    for url,quote in [(URL,'We have a SOC 2 report and certification.'),('https://evil.example','Business customer data is not used for training by default.')]:
        result=validate_findings({'findings':[{'criterion':'assurance','status':'met','summary':'Certified','url':url,'quote':quote}]},SOURCES)
        assert next(f for f in result if f.criterion=='assurance').status=='unknown'

def test_missing_and_redirected_pages_are_audited_without_following():
    seen=[]
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302,headers={'Location':'http://127.0.0.1/private'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sources=fetch_sources([URL],client)
    assert len(seen)==1 and sources[0]['status']=='unavailable'
    findings=score(sources,client=object())
    assert all(x.status=='unknown' for x in findings)
    assert 'HTTP 302' in render('Example','Draft',[x.model_dump() for x in findings],sources)

def test_review_gate_and_persisted_audit(tmp_path):
    db=audit.connect(tmp_path/'test.sqlite3')
    run=audit.create_run(db,'Example')
    with pytest.raises(ValueError): audit.decide(db,run,'Approved')
    audit.record_sources(db,run,SOURCES)
    findings=validate_findings({},SOURCES)
    audit.save_findings(db,run,findings)
    assert db.execute('SELECT status FROM runs WHERE id=?',(run,)).fetchone()[0]=='Draft'
    audit.decide(db,run,'Approved','Reviewed')
    with pytest.raises(ValueError): audit.decide(db,run,'Rejected')
    assert [r[0] for r in db.execute('SELECT step FROM events WHERE run_id=? ORDER BY id',(run,))]==['created','fetch','score','draft','decision']
    assert db.execute('SELECT content FROM sources WHERE run_id=?',(run,)).fetchone()[0]==TEXT
    db.close()
