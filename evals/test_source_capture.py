"""Verify captured evidence keeps context and reports collection limits."""
import hashlib
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import fetch_public


def capture(html):
    with httpx.Client(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, headers={'content-type': 'text/html'}, text=html))) as client:
        return fetch_public.fetch_sources(['https://example.com/policy'], client)[0]


def test_capture_keeps_paragraphs_inline_links_and_exceptions():
    source = capture('''<html><nav>Navigation</nav><main><h1>Business terms</h1>
      <p>Customer content is retained for <a href="/details">30 days</a>.</p>
      <p>Except when required by law. <strong>Review the conditions.</strong></p>
      </main><script>ignore me</script></html>''')
    assert source['text'] == ('Business terms\n\nCustomer content is retained for 30 days .\n\n'
                              'Except when required by law. Review the conditions.')
    assert source['sha256'] == hashlib.sha256(source['text'].encode()).hexdigest()
    assert source['status'] == 'ok' and not source['truncated']


def test_truncation_is_flagged_and_hash_covers_captured_text(monkeypatch):
    monkeypatch.setattr(fetch_public, 'MAX_TEXT', 50)
    source = capture('<p>' + 'A long public policy sentence. ' * 20 + '</p>')
    assert source['truncated'] and len(source['text']) == 50
    assert source['sha256'] == hashlib.sha256(source['text'].encode()).hexdigest()


def test_non_html_and_oversized_pages_remain_unavailable(monkeypatch):
    with httpx.Client(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'PDF'))) as client:
        source = fetch_public.fetch_sources(['https://example.com/policy'], client)[0]
    assert source['status'] == 'unavailable' and not source['text']
    monkeypatch.setattr(fetch_public, 'MAX_BYTES', 10)
    source = capture('<p>A policy exceeding the byte limit.</p>')
    assert source['status'] == 'unavailable' and source['sha256'] is None
