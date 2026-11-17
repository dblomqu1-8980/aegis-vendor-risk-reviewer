"""Adversarial model prose must not replace scoped, source-derived findings."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from memo import render
from score import build_passages, score


URL = 'https://example.com/business-policy'


def source(text, url=URL):
    return {'url': url, 'status': 'ok', 'text': text,
            'sha256': hashlib.sha256(text.encode()).hexdigest(),
            'reason': '', 'truncated': False}


def client_for(rows):
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        id='fictional-grounding-test', _request_id='fictional-request',
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'findings': rows})))],
    )
    return client


def selected_id(sources, phrase):
    return next(p['passage_id'] for p in build_passages(sources) if phrase in p['text'])


def finding_for(findings, criterion):
    return next(f for f in findings if f.criterion == criterion)


def assert_extractive(finding, sources):
    assert finding.status != 'unknown'
    assert finding.summary_mode == 'source_excerpt'
    evidence = [e.model_dump() if hasattr(e, 'model_dump') else e for e in finding.evidence]
    assert evidence
    captured = {s['url']: s['text'] for s in sources}
    assert all(e['url'] in captured and e['quote'] in captured[e['url']] for e in evidence)
    assert finding.summary == '\n\n'.join(e['quote'] for e in evidence)
    assert finding.url == evidence[0]['url']
    assert finding.quote == evidence[0]['quote']


SCOPED_CASES = [
    pytest.param(
        'training',
        'Business inputs and outputs are not used for training by default.\n\n'
        'Only API customers may explicitly opt in to share their API data for model improvement.',
        'Only API customers',
        'Every business product allows customers to opt in to training.',
        ['Only API customers', 'explicitly opt in', 'API data'],
        id='api-specific-training-opt-in',
    ),
    pytest.param(
        'retention',
        'Enterprise Chat organization owners may configure content retention.\n\n'
        'Zero data retention is available only to approved API customers using qualifying endpoints.',
        'Zero data retention',
        'All business products offer unrestricted zero data retention.',
        ['only to approved API customers', 'qualifying endpoints'],
        id='api-zero-retention-eligibility',
    ),
    pytest.param(
        'assurance',
        'FictionalCo describes a SOC 2 Type II attestation report.\n\n'
        'That report has not been supplied for independent inspection.',
        'SOC 2 Type II',
        'FictionalCo is SOC 2 certified and we independently verified its certification.',
        ['SOC 2 Type II attestation report', 'not been supplied for independent inspection'],
        id='soc2-report-is-not-certification',
    ),
    pytest.param(
        'location',
        'Eligible Pro API customers may choose Europe for customer content stored at rest.',
        'Eligible Pro API customers',
        'Every product stores and processes all customer data exclusively in Europe.',
        ['Eligible Pro API customers', 'stored at rest'],
        id='storage-evidence-does-not-become-processing-claim',
    ),
    pytest.param(
        'sensitive_data',
        'A signed health-data addendum is required before processing protected health information.\n\n'
        'Services not designed for protected health information must not process it, even with that addendum.',
        'A signed health-data addendum',
        'All services may process protected health information after signing an addendum.',
        ['addendum is required', 'must not process it', 'even with that addendum'],
        id='phi-addendum-does-not-remove-service-prohibition',
    ),
    pytest.param(
        'sensitive_data',
        'A signed health-data addendum is required before processing protected health information.\n\n'
        'Customers must not process protected health information with services that are not designed for it, even with an addendum.',
        'A signed health-data addendum',
        'All services may process protected health information after signing an addendum.',
        ['addendum is required', 'Customers must not process', 'even with an addendum'],
        id='customer-worded-phi-prohibition-is-still-context',
    ),
]


@pytest.mark.parametrize('selection_field', ['passage_ids', 'passage_id'])
@pytest.mark.parametrize('criterion,text,selected_phrase,bad_summary,required', SCOPED_CASES)
def test_erroneous_model_summary_cannot_reach_memo_and_source_qualifications_survive(
        selection_field, criterion, text, selected_phrase, bad_summary, required):
    sources = [source(text)]
    identifier = selected_id(sources, selected_phrase)
    row = {'criterion': criterion, 'status': 'met', 'summary': bad_summary,
           selection_field: [identifier] if selection_field == 'passage_ids' else identifier,
           'url': 'https://invented.example/fake', 'quote': 'A fabricated quote from the model.'}

    findings = score(sources, client=client_for([row]))
    finding = finding_for(findings, criterion)
    assert_extractive(finding, sources)
    assert all(fragment in finding.summary for fragment in required)
    document = render('FictionalCo', 'Draft', [f.model_dump() for f in findings], sources)
    assert all(fragment in document for fragment in required)
    assert bad_summary not in document
    assert 'https://invented.example/fake' not in document
    assert 'A fabricated quote from the model.' not in document


def test_location_can_cite_storage_and_processing_without_inventing_equivalence():
    storage = source('Eligible Pro API customers may choose Europe for customer content stored at rest.',
                     'https://example.com/storage')
    processing = source('Regional processing is available only for approved text endpoints; other processing may occur globally.',
                        'https://example.com/processing')
    sources = [storage, processing]
    bad_summary = 'Every product stores and processes all customer data exclusively in Europe.'
    row = {'criterion': 'location', 'status': 'partial', 'summary': bad_summary,
           'passage_ids': [selected_id(sources, 'stored at rest'), selected_id(sources, 'Regional processing')]}

    findings = score(sources, client=client_for([row]))
    finding = finding_for(findings, 'location')
    assert_extractive(finding, sources)
    assert all(fragment in finding.summary for fragment in (
        'Eligible Pro API customers', 'stored at rest', 'only for approved text endpoints',
        'other processing may occur globally',
    ))
    evidence = [e.model_dump() if hasattr(e, 'model_dump') else e for e in finding.evidence]
    assert {e['url'] for e in evidence} == {storage['url'], processing['url']}
    document = render('FictionalCo', 'Draft', [f.model_dump() for f in findings], sources)
    assert bad_summary not in document
    assert storage['url'] in document and processing['url'] in document


def test_customer_admin_controls_do_not_establish_vendor_personnel_access():
    sources = [source('Customer organization administrators assign account roles and remove their own users.')]
    row = {'criterion': 'access_sharing', 'status': 'met', 'passage_ids': [1],
           'summary': 'Vendor employees and contractors access content only on a need-to-know basis.'}

    findings = score(sources, client=client_for([row]))
    finding = finding_for(findings, 'access_sharing')
    assert finding.status == 'unknown'
    assert not finding.quote and not finding.url
    assert row['summary'] not in render('FictionalCo', 'Draft', [f.model_dump() for f in findings], sources)


def test_actual_vendor_need_to_know_terms_remain_available_as_evidence():
    text = ('The vendor may disclose customer content only to its employees and contractors '
            'who need to know it to provide the service and are bound by confidentiality obligations.')
    sources = [source(text)]
    row = {'criterion': 'access_sharing', 'status': 'partial', 'passage_ids': [1],
           'summary': 'No vendor employee can ever access customer content.'}

    findings = score(sources, client=client_for([row]))
    finding = finding_for(findings, 'access_sharing')
    assert_extractive(finding, sources)
    assert text in finding.summary
    assert row['summary'] not in finding.summary


def test_vendor_described_iso_certification_is_not_suppressed_as_soc2_overclaim():
    text = ('FictionalCo states that it holds ISO 27001 certification for its business service. '
            'The published statement is not an independent inspection of its certificate.')
    sources = [source(text)]
    row = {'criterion': 'assurance', 'status': 'met', 'passage_ids': [1],
           'summary': 'Our reviewer has inspected and independently verified every certificate.'}

    findings = score(sources, client=client_for([row]))
    finding = finding_for(findings, 'assurance')
    assert_extractive(finding, sources)
    assert text in finding.summary
    assert row['summary'] not in finding.summary


def test_source_excerpt_memo_ignores_forged_summary_and_keeps_each_evidence_citation():
    agreement = source('A health-data addendum is required before processing protected health information.',
                       'https://example.com/health-addendum')
    restriction = source('Services not designed for protected health information must not process it, even with that addendum.',
                         'https://example.com/service-restrictions')
    sources = [agreement, restriction]
    malicious_summary = 'All services may process protected health information once any addendum is signed.'
    finding = {
        'criterion': 'sensitive_data', 'status': 'partial', 'summary_mode': 'source_excerpt',
        'summary': malicious_summary, 'url': agreement['url'], 'quote': agreement['text'],
        'evidence': [{'url': s['url'], 'quote': s['text'], 'passage_ids': [i + 1]}
                     for i, s in enumerate(sources)],
    }

    document = render('FictionalCo', 'Draft', [finding], sources)
    assert malicious_summary not in document
    assert 'addendum is required before processing' in document
    assert 'must not process it' in document
    assert 'even with that addendum' in document
    assert f'Source: {agreement["url"]}' in document
    assert f'Source: {restriction["url"]}' in document
