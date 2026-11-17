"""Fixed review criteria. Labels express evidence quality, not certification."""
import re

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


def supports_criterion(criterion, text):
    """Conservative topic/scope gates, not a test of vendor compliance.

    Match the selected paragraph itself. Adjacent context must not turn an
    unrelated core paragraph into apparent evidence for a different topic.
    """
    value = ' '.join(text.split())

    def has(pattern):
        return re.search(pattern, value, re.IGNORECASE) is not None

    if criterion == 'training':
        return has(r'\b(?:train\w*|fine[- ]?tun\w*|model improvement|improv\w*.{0,35}models?)\b') and has(
            r'\b(?:data|content|inputs?|outputs?|customers?|business|API)\b')
    if criterion == 'retention':
        if has(r'\bretain\w*\b.{0,45}\bownership\b') and not has(
                r'\b(?:retention|delet\w*|eras\w*|purg\w*|destroy\w*|days?|hours?|months?|years?)\b'):
            return False
        stored_duration = has(r'\b(?:stor\w*|hold|held|keep|kept)\b') and has(
            r'\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|thirty|sixty|ninety)'
            r'\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b')
        return (stored_duration or has(r'\b(?:retain\w*|retention|delet\w*|eras\w*|purg\w*|destroy\w*)\b')) and has(
            r'\b(?:data|content|records?|information|inputs?|outputs?|conversations?|messages?|retention controls?)\b')
    if criterion == 'assurance':
        return has(r'\bSOC\s*(?:2|II)\b|\bISO(?:[/ ]IEC)?[ /-]*(?:27001|27017|27018|27701)\b|'
                   r'\bindependent\b.{0,80}\b(?:audit|report|certification)\b|'
                   r'\b(?:audit report|security certification)\b')
    if criterion == 'location':
        data_subject = has(r'\b(?:data|content|inputs?|outputs?|records?|information|'
                           r'inference|GPU|endpoints?|conversations?|messages?)\b') or has(
            r'\b(?:services?|applications?|platforms?|infrastructure|servers?)\b.{0,45}\bhost\w*\b|'
            r'\bhost\w*\b.{0,45}\b(?:services?|applications?|platforms?|infrastructure|servers?)\b')
        if not data_subject:
            return False
        relevant_action = has(r'\b(?:stor\w*|process\w*|residen\w*|host\w*|inference)\b')
        geography = has(
            r'\b(?:region\w*|countr\w*|territor\w*|jurisdiction\w*|locations?|'
            r'data cent(?:er|re)s?|globally|worldwide|residen\w*|where)\b|'
            r'\b(?:choose|choice|select)\b.{0,100}\b(?:stor\w*|process\w*|inference)\b')
        if not geography:
            for match in re.finditer(
                    r'\b(?:stor\w*|process\w*|host\w*|inference)\b.{0,90}?\b(?:in|within|outside)\s+(?P<place>[^.;:]{1,90})',
                    value, re.IGNORECASE):
                place = match.group('place')
                if re.match(r'(?:accordance|compliance|connection|conjunction|relation|respect|'
                            r'association|collaboration|response|transit|order|a manner|a way|'
                            r'DPA|agreement|terms|the (?:course|context|event|manner|same|agreement|DPA))\b', place, re.IGNORECASE):
                    continue
                # A named place can precede any later location qualifier.
                if re.match(r'(?:the\s+)?[A-Z](?:[A-Za-z]|$)', place):
                    geography = True
                    break
        return relevant_action and geography
    if criterion == 'subprocessors':
        return has(r'\b(?:sub[- ]?processors?|sub[- ]?contractors?)\b|'
                   r'\b(?:third[- ]part(?:y|ies)|service providers?)\b.{0,80}\b(?:list|register|directory)\b')
    if criterion == 'access_sharing':
        action = has(r'\b(?:access\w*|disclos\w*|shar\w*)\b')
        content = has(r'\b(?:customer|client|user|your)\b.{0,35}\b(?:data|content|information)\b|'
                      r'\b(?:confidential|sensitive) information\b')
        actor = has(r'\b(?:vendors?|providers?|recipient|personnel|employees?|contractors?|'
                    r'agents?|affiliates?|third[- ]part(?:y|ies))\b|'
                    r'\bwe\s+(?:may|can|will|only)\s+(?:access|share|disclose)\b')
        customer_admin = has(r'\b(?:your|customer\w*)\b.{0,30}\b(?:IT team|administrators?|'
                             r'admins?|systems|account roles|workspace permissions)\b')
        explicit_vendor = has(r'\b(?:vendor|recipient|our (?:employees|staff|personnel)|'
                              r'service providers?|third[- ]part(?:y|ies)|contractors?|agents?|affiliates?)\b')
        return action and content and actor and (not customer_admin or explicit_vendor)
    if criterion == 'security':
        return has(r'\b(?:encrypt\w*|AES[- ]?256|TLS|authenticat\w*|MFA|SSO|'
                   r'incident notification|security incident|breach notif\w*)\b')
    if criterion == 'sensitive_data':
        return has(r'\b(?:sensitive|confidential|regulated|health|medical|PHI|HIPAA|'
                   r'personal data|special.category|passwords?|social security)\b') and has(
            r'\b(?:must|may not|prohibit\w*|restrict\w*|not designed|do not|requir\w*|'
            r'unless|shall|not use|not allowed|limit\w*|avoid|warn\w*)\b')
    return False
