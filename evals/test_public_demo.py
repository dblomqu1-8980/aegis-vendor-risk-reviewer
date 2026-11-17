import concurrent.futures
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from demo_quota import reserve


def test_quota_is_atomic_across_visitors(tmp_path):
    db = tmp_path / 'usage.sqlite3'
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: reserve(db, now=100000, limit=5), range(30)))
    assert sum(results) == 5
    assert reserve(db, now=200000, limit=5)


def test_public_app_sessions_are_isolated(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import fetch_public
    import score
    source = {'url': 'https://example.com', 'status': 'ok', 'text': 'First visitor public source', 'reason': '', 'sha256': '', 'truncated': False}
    monkeypatch.setattr(fetch_public, 'fetch_sources', lambda urls: [source])
    monkeypatch.setattr(score, 'score', lambda sources, return_metadata: ([], {}))
    import demo_quota
    monkeypatch.setattr(demo_quota, 'reserve', lambda: True)
    script = str(Path(__file__).resolve().parents[1] / 'src' / 'public_app.py')
    first = AppTest.from_file(script).run()
    second = AppTest.from_file(script).run()
    assert not first.exception and not second.exception
    first.button[0].click().run()
    assert len(first.session_state['demo_reviews']) == 1
    second.run()
    assert not second.session_state['demo_reviews']
    assert not first.exception and not second.exception


def test_public_app_limits_repeat_attempts(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import demo_quota, fetch_public, score
    calls = []
    monkeypatch.setattr(demo_quota, 'reserve', lambda: calls.append('reserved') or True)
    monkeypatch.setattr(fetch_public, 'fetch_sources', lambda urls: [])
    monkeypatch.setattr(score, 'score', lambda sources, return_metadata: ([], {}))
    script = str(Path(__file__).resolve().parents[1] / 'src' / 'public_app.py')
    app = AppTest.from_file(script).run()
    app.button[0].click().run()
    app.button[0].click().run()
    assert len(calls) == 1
    assert any('30 seconds' in w.value for w in app.warning)
    app.session_state['demo_attempts'] = 3
    app.session_state['demo_last_attempt'] = 0
    app.button[0].click().run()
    assert len(calls) == 1
    assert any('three-review' in w.value for w in app.warning)
