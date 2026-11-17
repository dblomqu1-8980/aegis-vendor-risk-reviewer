"""Fixed review criteria. Labels express evidence quality, not certification."""
RUBRIC = {
 'training': 'Whether vendor uses customer inputs or outputs to train models, including product and opt-in distinctions.',
 'retention': 'Retention duration or deletion process for customer content.',
 'assurance': 'Whether SOC 2, ISO 27001, or similar independent security report or certification is described.',
 'location': 'Where customer data is stored or processed, or regional choices.',
 'subprocessors': 'Third-party subprocessors and whether a list is available.',
 'access_sharing': 'Vendor personnel or third-party access to customer content.',
 'security': 'Encryption, authentication, or incident-notification commitments.',
 'sensitive_data': 'Restrictions or warnings on regulated, sensitive, or confidential information.',
}
