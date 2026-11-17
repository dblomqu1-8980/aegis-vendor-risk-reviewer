"""Local demonstration. Do not expose publicly without access and storage controls."""
import json
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
import audit
from fetch_public import fetch_sources
from memo import render
from rubric import RUBRIC

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
st.set_page_config(page_title='Vendor Risk Reviewer | Aegis', page_icon='🛡️', layout='wide')
st.markdown('''<style>.stApp{background:#F7F6F2;color:#0F1B2D}.block-container{max-width:1120px} .hero{background:#0F1B2D;color:#fff;border-top:4px solid #D47B3A;border-radius:14px;padding:2.5rem;margin:1rem 0 2rem}.hero h1{color:#fff;margin:0 0 1rem}.hero p{color:#d4e3e2}.eyebrow{letter-spacing:.13em;color:#01696F;font-size:.75rem;font-weight:700}</style>''',unsafe_allow_html=True)
a,b=st.columns([1,7]); a.image(str(ROOT/'data'/'aegis-logo.jpeg'),width=72); b.markdown('**AEGIS AI ADVISORY**  \nPractical AI. Human oversight.')
st.markdown('<div class="hero"><p>AEGIS INTERACTIVE DEMONSTRATION</p><h1>Know what your AI vendor says.</h1><p>Review public information, identify gaps, and keep a person in control of the decision.</p></div>',unsafe_allow_html=True)
st.info('Demo only. Public vendor pages may be incomplete or change. Findings are not a legal opinion, certification, or a substitute for reviewing current terms. Do not enter client or confidential information.')
vendors=json.loads((ROOT/'data'/'vendors.json').read_text())
db=audit.connect()
left,right=st.columns([1.3,1])
with left:
    st.subheader('Start a vendor review')
    vendor=st.selectbox('Vendor and product scope',list(vendors))
    st.caption('The selected public URLs will be reviewed:')
    for url in vendors[vendor]: st.write(url)
    if st.button('Create draft review',type='primary'):
        run=audit.create_run(db,vendor)
        st.session_state.run_id=run
        with st.spinner('Retrieving public pages and checking the evidence…'):
            sources=fetch_sources(vendors[vendor]); audit.record_sources(db,run,sources)
            try:
                from score import score
                findings,metadata=score(sources,return_metadata=True)
                audit.save_findings(db,run,findings,metadata=metadata)
            except Exception:
                with db: audit.event(db,run,'error',{'stage':'scoring','message':'Scoring unavailable; check API setup and retry with a new review.'})
                st.error('The review could not be scored. Check the OpenAI API setup and try a new review.')
with right:
    st.subheader('What the reviewer checks')
    st.write('Training and data use · Retention · Security assurance · Data location · Subprocessors · Access and sharing · Security basics · Sensitive data')
    st.caption('Findings quote source paragraphs. Review their scope, conditions, and evidence coverage. Unknown is a valid result; a person must review the draft.')

runs=db.execute('SELECT id,vendor,created_at,status,findings FROM runs ORDER BY id DESC').fetchall()
if runs:
    ids=[r[0] for r in runs]
    default=ids.index(st.session_state.get('run_id')) if st.session_state.get('run_id') in ids else 0
    selected=st.selectbox('Open a review',ids,index=default,format_func=lambda i:next(f'#{r[0]} · {r[1]} · {r[3]}' for r in runs if r[0]==i))
    row=next(r for r in runs if r[0]==selected)
    findings=json.loads(row[4])
    sources=[dict(zip(('url','status','reason','truncated'),s)) for s in db.execute('SELECT url,status,reason,truncated FROM sources WHERE run_id=?',(selected,))]
    st.divider(); st.subheader(f'{row[1]} · {row[3]}')
    st.caption('Created '+row[2]+' · A reviewer must verify the source and summary.')
    if not findings:
        st.warning('No scored draft is available for this review. Create a new review after checking the setup.')
    else:
        if any(f.get('summary_mode','legacy')=='legacy' and f.get('quote') for f in findings):
            st.info('This historical review uses earlier generated summaries. Create a new review to use the updated source-based memo.')
        decision_event=db.execute("SELECT at,detail FROM events WHERE run_id=? AND step='decision' ORDER BY id DESC LIMIT 1",(selected,)).fetchone()
        decision_detail=None
        if decision_event:
            decision_detail={'at':decision_event[0], **json.loads(decision_event[1])}
        document=render(row[1],row[3],findings,sources,decision=decision_detail)
        st.markdown(document)
        st.download_button('Download review as Markdown',document,file_name=f'vendor-review-{selected}.md',mime='text/markdown')
        if row[3]=='Draft':
            with st.form(f'decision-{selected}'):
                decision=st.radio('Human review decision',('Approve','Reject'),horizontal=True)
                comment=st.text_input('Optional review note (do not enter sensitive information)',max_chars=500)
                confirm=st.checkbox('I reviewed the findings and source quotations.')
                submit=st.form_submit_button('Record decision')
            if submit:
                if not confirm: st.warning('Confirm that you reviewed the draft before recording a decision.')
                else:
                    audit.decide(db,selected,'Approved' if decision=='Approve' else 'Rejected',comment)
                    st.rerun()
    with st.expander('Audit trail and captured source text'):
        for at,step,detail in db.execute('SELECT at,step,detail FROM events WHERE run_id=? ORDER BY id',(selected,)):
            st.write(at, '·', step, json.loads(detail))
        for url,status,text in db.execute('SELECT url,status,content FROM sources WHERE run_id=?',(selected,)):
            with st.expander(f'{url} · {status}'):
                st.text(text or 'No source text was available.')
db.close()
