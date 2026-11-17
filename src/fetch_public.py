"""Fetch only preselected HTTPS pages; never follow redirects to unknown hosts."""
import hashlib
import httpx
from bs4 import BeautifulSoup

MAX_BYTES = 1000000
MAX_TEXT = 50000

def fetch_sources(urls, client=None):
    if client is None:
        with httpx.Client(timeout=15, follow_redirects=False, headers={'User-Agent':'AegisVendorRiskReviewer/0.1'}) as owned_client:
            return fetch_sources(urls, owned_client)
    sources = []
    for url in urls:
        source = {'url':url, 'status':'unavailable', 'text':'', 'sha256':None, 'reason':'', 'truncated':False}
        try:
            with client.stream('GET', url) as response:
                source['http_status'] = response.status_code
                if response.status_code != 200:
                    source['reason'] = f'HTTP {response.status_code}; redirects are not followed.'
                elif 'html' not in response.headers.get('content-type','').lower():
                    source['reason'] = 'Source was not an HTML page.'
                else:
                    parts=[]; total=0
                    for chunk in response.iter_bytes():
                        total+=len(chunk)
                        if total>MAX_BYTES: raise ValueError('Source exceeds byte limit')
                        parts.append(chunk)
                    soup=BeautifulSoup(b''.join(parts), 'html.parser')
                    for element in soup(['script','style','nav','footer','header']): element.decompose()
                    text=' '.join(soup.stripped_strings)
                    if not text:
                        source['reason']='Page contained no extractable text.'
                    else:
                        source.update(status='ok', text=text[:MAX_TEXT], sha256=hashlib.sha256(text[:MAX_TEXT].encode()).hexdigest(), truncated=len(text)>MAX_TEXT)
        except (httpx.HTTPError, ValueError) as exc:
            source['reason']=type(exc).__name__
        sources.append(source)
    return sources
