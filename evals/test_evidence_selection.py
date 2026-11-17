"""Server-derived source quotations and safe passage-selection failures."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rubric import RUBRIC
from score import MAX_PASSAGE_CHARS, build_passages, score, validate_findings


URL = 'https://example.com/business'


def source(text, url=URL, status='ok'):
    return {'url': url, 'status': status, 'text': text,
            'sha256': None, 'reason': '', 'truncated': False}


def client_for(payload):
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        id='test-response', _request_id='test-request',
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
    )
    return client


def by_criterion(findings):
    return {finding.criterion: finding for finding in findings}


def test_selected_paragraph_keeps_adjacent_exception_and_restriction():
    text = ('Health data requires a signed supplemental agreement.\n\n'
            'Services not designed for health data must not process it, even with that agreement.')
    passages = build_passages([source(text)])
    client = client_for({'findings': [{
        'criterion': 'sensitive_data', 'status': 'met',
        'summary': 'An agreement is required, and unsupported services remain prohibited.',
        'passage_id': 1,
        # Generated citation fields must never replace original source text.
        'url': 'https://invented.example/', 'quote': 'A fabricated quotation.',
    }]})

    findings, metadata = score([source(text)], client=client, return_metadata=True)
    finding = by_criterion(findings)['sensitive_data']

    assert finding.status == 'met'
    assert finding.url == URL
    assert finding.quote == text
    assert passages[0]['text'] == text.split('\n\n')[0]
    assert finding.summary_mode == 'source_excerpt'
    assert finding.summary == '\n\n'.join(item.quote for item in finding.evidence)
    assert metadata['validation']['sensitive_data'] == 'accepted_source_selection'
    assert metadata['evidence_method'] == 'extractive_paragraph_selection_v2'
    assert metadata['response_id'] == 'test-response'
    assert metadata['request_id'] == 'test-request'


def test_model_receives_numbered_passages_and_can_select_second_source():
    sources = [source('The service requires an approved business account.'),
               source('Records are deleted within thirty days after termination, except where required by law.',
                      url='https://example.com/terms')]
    client = client_for({'findings': [{
        'criterion': 'retention', 'status': 'met',
        'summary': 'Posttermination deletion within thirty days, with a legal-retention exception.',
        'passage_id': 2,
    }]})

    findings = score(sources, client=client)

    finding = by_criterion(findings)['retention']
    assert finding.url == sources[1]['url']
    assert finding.quote == sources[1]['text']
    sent = client.chat.completions.create.call_args.kwargs['messages'][1]['content']
    submitted = json.loads(sent)['passages']
    assert [row['passage_id'] for row in submitted] == [1, 2]
    assert submitted[1]['text'] == sources[1]['text']
    assert set(submitted[1]) == {'passage_id', 'url', 'text'}


@pytest.mark.parametrize('identifier', [True, False, 0, -1, 2, '1', 1.0, None])
def test_invalid_passage_id_becomes_unknown(identifier):
    sources = [source('The service encrypts customer content at rest and in transit.')]
    client = client_for({'findings': [{
        'criterion': 'security', 'status': 'met', 'summary': 'Encryption is described.',
        'passage_id': identifier,
    }]})

    findings, metadata = score(sources, client=client, return_metadata=True)

    assert by_criterion(findings)['security'].status == 'unknown'
    assert by_criterion(findings)['security'].quote == ''
    assert metadata['validation']['security'] == 'invalid_passage_id'


def test_duplicate_criterion_is_unknown_instead_of_arbitrarily_selected():
    row = {'criterion': 'training', 'status': 'met',
           'summary': 'Business inputs are not used for training by default.', 'passage_id': 1}
    sources = [source('Business inputs are not used for training by default. Explicit opt-in is available.')]

    findings, metadata = score(sources, client=client_for({'findings': [row, row]}),
                               return_metadata=True)

    assert by_criterion(findings)['training'].status == 'unknown'
    assert metadata['validation']['training'] == 'duplicate_finding'


def test_silent_criterion_remains_unknown_without_an_invented_assurance():
    client = client_for({'findings': [{
        'criterion': 'assurance', 'status': 'unknown',
        'summary': 'No security certification was documented.', 'passage_id': None,
    }]})

    findings, metadata = score([source('Business inputs are not used for training by default.')],
                               client=client, return_metadata=True)

    assert len(findings) == len(RUBRIC)
    assert all(finding.status == 'unknown' for finding in findings)
    assert by_criterion(findings)['assurance'].quote == ''
    assert metadata['validation']['assurance'] == 'model_unknown'
    assert metadata['validation']['location'] == 'missing_finding'


def test_no_available_text_does_not_call_model():
    client = MagicMock()
    findings, metadata = score([source('', status='unavailable')], client=client,
                               return_metadata=True)

    client.chat.completions.create.assert_not_called()
    assert all(finding.status == 'unknown' for finding in findings)
    assert all(finding.summary_mode == 'source_excerpt' for finding in findings)
    assert metadata['passage_count'] == 0
    assert metadata['status_counts'] == {'unknown': len(RUBRIC)}


def test_short_selected_evidence_records_validation_failure_not_acceptance():
    client = client_for({'findings': [{
        'criterion': 'security', 'status': 'met',
        'summary': 'Security is documented.', 'passage_id': 1,
    }]})

    findings, metadata = score([source('TLS data.')], client=client, return_metadata=True)

    assert by_criterion(findings)['security'].status == 'unknown'
    assert by_criterion(findings)['security'].quote == ''
    assert metadata['validation']['security'] == 'source_validation_failed'


def test_flattened_legacy_text_is_bounded_overlapping_and_exact():
    text = ' '.join(f'Policy sentence {number} preserves the customer data restriction.'
                    for number in range(180))
    passages = build_passages([source(text)])

    assert len(passages) > 1
    assert passages[0]['start'] == 0
    assert passages[-1]['end'] == len(text)
    assert all(len(p['text']) <= MAX_PASSAGE_CHARS for p in passages)
    assert all(p['text'] == text[p['start']:p['end']] for p in passages)
    assert all(right['start'] < left['end'] for left, right in zip(passages, passages[1:]))


def test_focused_paragraphs_preserve_adjacent_service_restriction():
    paragraphs = [('The approval requirement applies to the business plan. ' * 10).strip(),
                  ('A supplemental agreement is required for health information. ' * 10).strip(),
                  ('An unsupported service must not process health information. ' * 10).strip(),
                  ('A reviewer must verify current product eligibility. ' * 10).strip(),
                  ('Deletion follows the documented contractual process. ' * 10).strip()]
    text = '\n\n'.join(paragraphs)
    passages = build_passages([source(text)])

    assert len(passages) > 1
    assert all(p['text'] == text[p['start']:p['end']] for p in passages)
    assert [p['text'] for p in passages] == paragraphs
    client = client_for({'findings': [{
        'criterion': 'sensitive_data', 'status': 'partial', 'passage_ids': [2],
        'summary': 'A signed agreement removes all restrictions.',
    }]})
    finding = by_criterion(score([source(text)], client=client))['sensitive_data']
    assert finding.status != 'unknown'
    assert paragraphs[1] in finding.quote and paragraphs[2] in finding.quote
    assert 'A signed agreement removes all restrictions.' not in finding.summary


def test_malformed_model_json_yields_unknown_with_safe_validation_metadata():
    client = client_for({})
    client.chat.completions.create.return_value.choices[0].message.content = 'not json'

    findings, metadata = score([source('The service encrypts customer content in transit.')],
                               client=client, return_metadata=True)

    assert all(finding.status == 'unknown' for finding in findings)
    assert set(metadata['validation'].values()) == {'invalid_model_response'}
    json.dumps(metadata)  # Metadata is suitable for the existing JSON audit event.


def test_incomplete_retention_can_remain_partial_with_exact_source_context():
    text = 'Retention controls are available for qualifying organizations. Eligibility must be checked.'
    client = client_for({'findings': [{
        'criterion': 'retention', 'status': 'partial',
        'summary': 'Controls are mentioned, but duration and deletion details are not provided.',
        'passage_id': 1,
    }]})

    findings = score([source(text)], client=client)

    finding = by_criterion(findings)['retention']
    assert finding.status == 'partial'
    assert finding.quote == text


def test_oversized_actual_paragraph_keeps_terminal_health_data_prohibition():
    paragraph = ('A signed health-data agreement is required. '
                 + 'The reviewer must check the applicable product scope. ' * 65
                 + 'Services not designed for protected health information must not process it, even with that agreement.')
    text = 'Sensitive information policy\n\n' + paragraph
    passages = build_passages([source(text)])
    selected = next(p for p in passages if 'signed health-data agreement' in p['text'])
    client = client_for({'findings': [{
        'criterion': 'sensitive_data', 'status': 'partial', 'passage_ids': [selected['passage_id']],
    }]})

    finding = by_criterion(score([source(text)], client=client))['sensitive_data']

    assert len(paragraph) > MAX_PASSAGE_CHARS
    assert selected['text'] == paragraph
    assert finding.status == 'partial'
    assert finding.quote == paragraph
    assert finding.summary.endswith('must not process it, even with that agreement.')


def test_candidate_pool_distinguishes_customer_it_from_vendor_disclosure():
    sources = [source('Customer administrators assign account roles and remove their own users.\n\n'
                      'The vendor may disclose customer content to employees and contractors who need to know and are bound by confidentiality.')]
    client = client_for({'findings': [{
        'criterion': 'access_sharing', 'status': 'partial', 'passage_ids': [2],
    }]})

    finding = by_criterion(score(sources, client=client))['access_sharing']

    submitted = json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
    assert submitted['candidate_ids']['access_sharing'] == [2]
    assert finding.status == 'partial'
    assert 'need to know' in finding.summary
    assert 'assign account roles' not in finding.summary


def test_mixed_customer_it_and_vendor_access_keeps_only_supported_vendor_scope():
    customer = 'Customer administrators assign account roles and remove their own users.'
    vendor = ('The vendor may disclose customer content to employees and contractors '
              'who need to know and are bound by confidentiality.')
    sources = [source(customer + '\n\n' + vendor)]
    client = client_for({'findings': [{
        'criterion': 'access_sharing', 'status': 'met', 'passage_ids': [1, 2],
    }]})

    findings, metadata = score(sources, client=client, return_metadata=True)
    finding = by_criterion(findings)['access_sharing']

    assert finding.status == 'partial'
    assert finding.summary == vendor
    assert finding.quote == vendor
    assert customer not in finding.summary
    assert metadata['validation']['access_sharing'] == 'accepted_with_scope_filter'
    assert metadata['requested_ids']['access_sharing'] == [1, 2]
    assert metadata['selected_ids']['access_sharing'] == [2]
    assert metadata['rejected_ids']['access_sharing'] == [1]


def test_all_wrong_scope_selections_remain_unknown_and_auditable():
    text = 'Customer administrators assign account roles and remove their own users.'
    client = client_for({'findings': [{
        'criterion': 'access_sharing', 'status': 'met', 'passage_ids': [1],
    }]})

    findings, metadata = score([source(text)], client=client, return_metadata=True)
    finding = by_criterion(findings)['access_sharing']

    assert finding.status == 'unknown'
    assert finding.evidence == []
    assert metadata['validation']['access_sharing'] == 'criterion_scope_mismatch'
    assert metadata['requested_ids']['access_sharing'] == [1]
    assert metadata['rejected_ids']['access_sharing'] == [1]
    assert 'access_sharing' not in metadata['selected_ids']


def test_out_of_range_mixed_with_valid_id_still_fails_closed():
    text = 'Customer content is encrypted at rest and in transit.'
    client = client_for({'findings': [{
        'criterion': 'security', 'status': 'met', 'passage_ids': [1, 999],
    }]})

    findings, metadata = score([source(text)], client=client, return_metadata=True)

    assert by_criterion(findings)['security'].status == 'unknown'
    assert metadata['validation']['security'] == 'invalid_passage_id'
    assert metadata['requested_ids']['security'] == [1, 999]
    assert 'security' not in metadata['selected_ids']


@pytest.mark.parametrize('phrase', ['in accordance with the DPA', 'in compliance with these terms',
                                  'in connection with the customer agreement'])
def test_processing_legal_basis_does_not_establish_data_geography(phrase):
    text = f'Customer data submitted through the service is processed {phrase}.'
    client = client_for({'findings': [{
        'criterion': 'location', 'status': 'met', 'passage_ids': [1],
    }]})

    findings, metadata = score([source(text)], client=client, return_metadata=True)

    assert by_criterion(findings)['location'].status == 'unknown'
    assert metadata['validation']['location'] == 'criterion_scope_mismatch'


@pytest.mark.parametrize('text', ['Customer data is stored in Europe for eligible accounts.',
                                'Customer data is processed within Canada.',
                                'Regional processing is available only on selected endpoints.'])
def test_actual_data_geography_remains_available(text):
    client = client_for({'findings': [{
        'criterion': 'location', 'status': 'partial', 'passage_ids': [1],
    }]})

    finding = by_criterion(score([source(text)], client=client))['location']

    assert finding.status == 'partial'
    assert finding.summary == text


def test_regional_arbitration_process_is_not_customer_data_geography():
    text = ('J.2. Arbitration. Any Dispute will be determined in English by final, binding arbitration '
            'according to the region-specific processes below. Judgment on any award issued through '
            'the arbitration process in this Section J.2 (Arbitration) may be entered in any court '
            'having jurisdiction. EACH PARTY AGREES THEY ARE WAIVING THE RIGHT TO A TRIAL BY JURY, '
            'AND THE RIGHT TO JOIN AND PARTICIPATE IN A CLASS ACTION, TO THE FULLEST EXTENT PERMITTED '
            'UNDER THE LAW IN CONNECTION WITH THESE TERMS.')
    client = client_for({'findings': [{
        'criterion': 'location', 'status': 'met', 'passage_ids': [1],
    }]})

    findings, metadata = score([source(text)], client=client, return_metadata=True)

    assert by_criterion(findings)['location'].status == 'unknown'
    assert metadata['validation']['location'] == 'criterion_scope_mismatch'
    assert metadata['rejected_ids']['location'] == [1]


@pytest.mark.parametrize('text', [
    'Eligible API customers can store sensitive customer content at rest in the U.S., Europe, or Canada.',
    'Eligible customers may opt into in-region GPU inference in the U.S. or Europe on supported endpoints.',
    'The business service is hosted in Europe for qualifying organizations.',
])
def test_data_storage_inference_and_service_hosting_are_geographic_evidence(text):
    client = client_for({'findings': [{
        'criterion': 'location', 'status': 'partial', 'passage_ids': [1],
    }]})

    finding = by_criterion(score([source(text)], client=client))['location']

    assert finding.status == 'partial'
    assert finding.summary == text


def test_stored_conversation_duration_keeps_feedback_only_scope():
    text = ('When you provide feedback, we store the entire related conversation for up to 5 years. '
            'This does not describe retention for every ordinary customer conversation.')
    client = client_for({'findings': [{
        'criterion': 'retention', 'status': 'partial', 'passage_ids': [1],
    }]})

    finding = by_criterion(score([source(text)], client=client))['retention']

    assert finding.status == 'partial'
    assert finding.summary == text
    assert 'When you provide feedback' in finding.summary


def test_lettered_exclusion_clause_remains_with_disclosure_conditions():
    text = ('E.2. Recipient may share customer content only with employees who need to know and are bound by confidentiality.\n\n'
            'E.3. Exclusions. Recipient may disclose Confidential Information when required by law, with notice when permitted.')
    client = client_for({'findings': [{
        'criterion': 'access_sharing', 'status': 'partial', 'passage_ids': [1],
    }]})

    finding = by_criterion(score([source(text)], client=client))['access_sharing']

    assert finding.status == 'partial'
    assert finding.summary == text
    assert 'required by law' in finding.summary


def test_retaining_ownership_is_not_a_retention_period_or_deletion_process():
    text = 'Customer retains all ownership rights in Input and owns all Output.'
    client = client_for({'findings': [{
        'criterion': 'retention', 'status': 'met', 'passage_ids': [1],
    }]})

    findings, metadata = score([source(text)], client=client, return_metadata=True)

    assert by_criterion(findings)['retention'].status == 'unknown'
    assert metadata['validation']['retention'] == 'criterion_scope_mismatch'


@pytest.mark.parametrize('tamper', ['summary', 'secondary_quote', 'offset'])
def test_extractive_validation_checks_summary_every_quote_and_source_offsets(tamper):
    first = source('Customer content is encrypted at rest and in transit.')
    second = source('Multi-factor authentication is required for account administrators.',
                    url='https://example.com/authentication')
    evidence = [{'url': s['url'], 'quote': s['text'], 'start': 0, 'end': len(s['text'])}
                for s in (first, second)]
    row = {'criterion': 'security', 'status': 'met', 'summary_mode': 'source_excerpt',
           'url': first['url'], 'quote': first['text'], 'evidence': evidence,
           'summary': '\n\n'.join(e['quote'] for e in evidence)}
    if tamper == 'summary':
        row['summary'] = 'The reviewer independently verified every security control.'
    elif tamper == 'secondary_quote':
        evidence[1]['quote'] = 'The vendor has a perfect security record.'
        evidence[1].pop('start')
        evidence[1].pop('end')
        row['summary'] = '\n\n'.join(e['quote'] for e in evidence)
    else:
        evidence[1]['start'] = 1

    finding = by_criterion(validate_findings({'findings': [row]}, [first, second]))['security']

    assert finding.status == 'unknown'
    assert finding.summary_mode == 'source_excerpt'
    assert finding.evidence == []
