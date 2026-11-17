"""Temporary, anonymous public demonstration. Does not access local review storage."""
import json
import time
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from demo_quota import reserve
from fetch_public import fetch_sources
from memo import render
from score import score

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
st.set_page_config(page_title='Vendor Risk Reviewer | Aegis', page_icon='🛡️', layout='wide')
st.markdown('''<style>.stApp{background:#F7F6F2;color:#0F1B2D}.block-container{max-width:1120px}.hero{background:#0F1B2D;color:white;border-top:4px solid #D47B3A;border-radius:14px;padding:2.5rem;margin:1rem 0 2rem}.hero h1{color:white}.hero p{color:#d4e3e2}</style>''', unsafe_allow_html=True)
a, b = st.columns([1, 7])
a.image(str(ROOT / 'data' / 'aegis-logo.jpeg'), width=72)
b.markdown('**AEGIS AI ADVISORY**  \nPractical AI. Human oversight.')
st.markdown('<div class="hero"><p>AEGIS INTERACTIVE DEMONSTRATION</p><h1>Know what your AI vendor says.</h1><p>Review public information, identify gaps, and keep a person in control of the decision.</p></div>', unsafe_allow_html=True)
st.info('Demo only. Public vendor information can be incomplete or change. This is not legal advice, certification, or approval to use a vendor. Do not enter confidential information.')
st.caption('Reviews are temporary and stay in your current browser session. Download your draft before leaving or refreshing; it may be lost. No account or permanent review history is provided.')
vendors = json.loads((ROOT / 'data' / 'vendors.json').read_text())
if 'demo_reviews' not in st.session_state:
    st.session_state.demo_reviews = []
    st.session_state.demo_attempts = 0
    st.session_state.demo_last_attempt = 0.0
left, right = st.columns([1.3, 1])
with left:
    st.subheader('Start a vendor review')
    vendor = st.selectbox('Vendor and product scope', list(vendors))
    st.caption('The selected public URLs will be reviewed:')
    for url in vendors[vendor]:
        st.write(url)
    if st.button('Create draft review', type='primary'):
        now = time.time()
        if st.session_state.demo_attempts >= 3:
            st.warning('This session has reached its three-review limit.')
        elif now - st.session_state.demo_last_attempt < 30:
            st.warning('Please wait 30 seconds between attempts.')
        else:
            st.session_state.demo_attempts += 1
            st.session_state.demo_last_attempt = now
            with st.spinner('Retrieving public pages and checking the evidence…'):
                try:
                    # Reserve before network work, including failures, to limit abusive fetches.
                    if not reserve():
                        st.warning('The demo has reached its daily capacity. Please try again later.')
                    else:
                        sources = fetch_sources(vendors[vendor])
                        findings, _ = score(sources, return_metadata=True)
                        st.session_state.demo_reviews.append({'vendor': vendor, 'sources': sources,
                            'findings': [f.model_dump() for f in findings]})
                except Exception:
                    st.error('The review could not be completed. Please try again later.')
with right:
    st.subheader('What the reviewer checks')
    st.write('Training and data use · Retention · Security assurance · Data location · Subprocessors · Access and sharing · Security basics · Sensitive data')
    st.caption('Findings quote source paragraphs. Review their scope, conditions, and evidence coverage. Unknown is a valid result; a person must review the draft.')
if st.session_state.demo_reviews:
    reviews = st.session_state.demo_reviews
    selected = st.selectbox('Your reviews in this session', range(len(reviews)), index=len(reviews)-1,
        format_func=lambda i: f'{i+1} · {reviews[i]["vendor"]}')
    review = reviews[selected]
    document = render(review['vendor'], 'Draft', review['findings'], review['sources'])
    st.divider()
    st.markdown(document)
    st.download_button('Download review as Markdown', document, file_name='aegis-vendor-review.md', mime='text/markdown')
    with st.expander('Captured public source text'):
        for source in review['sources']:
            with st.expander(f'{source["url"]} · {source["status"]}'):
                st.text(source['text'] or 'No source text was available.')
