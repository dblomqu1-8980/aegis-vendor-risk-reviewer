from rubric import RUBRIC

def render(vendor,status,findings,sources):
    lines=[f'# Vendor evidence review: {vendor}',f'**Status: {status}**','',
           'Demonstration only. A source quotation is not proof of the summary or a certification. Verify current terms and seek professional advice where appropriate.','',
           '## Findings']
    by_key={f['criterion']:f for f in findings}
    for key, label in RUBRIC.items():
        f=by_key.get(key,{'status':'unknown','summary':'Not assessed.'})
        lines += [f'### {key.replace("_"," ").title()} — {f["status"].upper()}',f['summary']]
        if f.get('quote'): lines += [f'> {f["quote"]}',f'Source: {f["url"]}']
        lines.append('')
    lines += ['## Sources and limitations']
    for s in sources:
        limitation = ' (source text truncated)' if s['truncated'] else ''
        lines.append(f'- {s["url"]}: {s["status"]}{limitation}' + (f' — {s["reason"]}' if s['reason'] else ''))
    lines += ['', '## Review decision', 'Human review required. Verify findings and unresolved items against current vendor documents before any purchasing or policy decision.']
    return '\n'.join(lines)
