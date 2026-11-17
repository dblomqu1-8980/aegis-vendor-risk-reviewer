from rubric import RUBRIC
import re

def quote_text(text):
    # Keep every paragraph inside the quotation and render source Markdown literally.
    return '\n'.join('> ' + re.sub(r'([\\`*_{}\[\]()#+.!|>~\-])', r'\\\1', line)
                     for line in text.splitlines())

def render(vendor,status,findings,sources,decision=None):
    extractive = any(f.get('summary_mode') == 'source_excerpt' for f in findings)
    explanation = (
        '**Evidence draft:** Findings preserve the vendor\'s source wording. Evidence selection and coverage classifications require review. MET means the topic is documented, not that the vendor is compliant, secure, or approved. Verify relevance, scope, and exceptions against the captured source text.'
        if extractive else
        '**Unverified AI draft:** Both summaries and rubric classifications require review. MET means the topic is documented, not that the vendor is compliant, secure, or approved. Verify relevance, scope, and exceptions against the captured source text.'
    )
    lines=[f'# Vendor evidence review: {vendor}',f'**Status: {status}**','',
           'Demonstration only. A source quotation is not proof of the summary or a certification. Verify current terms and seek professional advice where appropriate.','',
           explanation,'',
           '## Findings']
    by_key={f['criterion']:f for f in findings}
    for key, label in RUBRIC.items():
        f=by_key.get(key,{'status':'unknown','summary':'Not assessed.'})
        lines += [f'### {key.replace("_"," ").title()} — {f["status"].upper()}',label,'']
        if f.get('summary_mode') == 'source_excerpt':
            if f.get('evidence'):
                lines += ['**Vendor source text:**','']
                for evidence in f['evidence']:
                    lines += [quote_text(evidence['quote']),'',f'Source: {evidence["url"]}','']
                if key == 'assurance':
                    lines += ['These are published vendor statements. No audit report was inspected and no certification was independently verified by this demo.','']
            else:
                lines += [f'**Finding:** {f["summary"]}']
        else:
            lines += [f'**Model draft summary:** {f["summary"]}']
            if f.get('quote'): lines += ['',quote_text(f['quote']),'',f'Source: {f["url"]}']
        lines.append('')
    lines += ['## Sources and limitations']
    for s in sources:
        limitation = ' (source text truncated)' if s['truncated'] else ''
        lines.append(f'- {s["url"]}: {s["status"]}{limitation}' + (f' — {s["reason"]}' if s['reason'] else ''))
    lines += ['', '## Review decision']
    if status in ('Approved','Rejected'):
        lines.append(f'Human review recorded: **{status}**.')
        if decision and decision.get('at'):
            lines.append(f'Recorded at: {decision["at"]}')
        if decision and decision.get('comment'):
            # Keep each line quoted so a review note cannot create memo headings.
            lines += ['Review note:'] + [f'> {line}' for line in decision['comment'].splitlines()]
        lines.append('This decision records review of this demo memo and does not authorize vendor use. Verify current vendor documents before any purchasing or policy decision.')
    else:
        lines.append('Human review required. Verify findings and unresolved items against current vendor documents before any purchasing or policy decision.')
    return '\n'.join(lines)
