"""Conservative, read-only scientific evidence processing for ASTRA-FIRE AI.
No external dependencies. No numerical damage probability is inferred.
"""
import re
from database.models import get_connection

RULES = {
    'AF-01': ('High', ('sustained flame propagation', 'sustained flame spread', 'self-sustained flame spread')),
    'AF-03': ('Moderate', ('incomplete combustion', 'carbon monoxide was measured', 'measured co production')),
    'AF-04': ('Moderate', ('conditional flame extinction', 'flame extinguished when', 'extinction occurred at')),
    'AF-05': ('Low', ('no ignition was observed', 'did not ignite', 'no ignition occurred')),
    'AF-06': ('High', ('secondary flame propagation', 'reignition was observed', 're-ignition was observed')),
}
CONDITION_WORDS = ('microgravity', 'normal gravity', 'oxygen', 'pressure', 'airflow', 'flow velocity', 'fuel', 'sample', 'burner')


def source_snippets(source_text, max_snippets=14):
    """Find explicit outcome phrases; each quote comes verbatim from supplied source text."""
    snippets = []
    for rule, (level, phrases) in RULES.items():
        for phrase in phrases:
            for match in list(re.finditer(re.escape(phrase), source_text, flags=re.IGNORECASE))[:3]:
                start = max(0, match.start() - 160)
                end = min(len(source_text), match.end() + 160)
                excerpt = source_text[start:end].strip().replace('\n', ' ')
                preceding = source_text[:match.start()]
                pages = re.findall(r'\[PDF PAGE (\d+)\]', preceding)
                sheets = re.findall(r'\[SHEET ([^;\]]+)', preceding)
                location = f'PDF page {pages[-1]}' if pages else (f'Sheet {sheets[-1]}' if sheets else 'Location not established')
                negated = bool(re.search(r'\b(?:not|no|without|absence of)\s+(?:\w+\s+){0,3}$', source_text[max(0, match.start()-35):match.start()], re.I))
                snippets.append({'rule': rule, 'candidate_level': level, 'location': location,
                                 'excerpt': excerpt, 'negation_warning': negated,
                                 'condition_context': any(word in excerpt.lower() for word in CONDITION_WORDS)})
                if len(snippets) >= max_snippets:
                    return snippets
    return snippets


def conservative_decision(snippets):
    """Candidate evidence is not verified outcome evidence: abstain pending source review."""
    return {'classification': 'Insufficient Evidence',
            'reason': 'Candidate text matches require verification of observed outcome, experimental conditions and source context.',
            'candidate_rules': sorted({s['rule'] for s in snippets}),
            'probability_of_damage': 'Not quantifiable from supplied evidence'}


def linked_library_evidence(document_ids, max_records=25):
    """Read SQLite relationships only; never imply provisional findings are validated."""
    output = []
    with get_connection() as conn:
        for document_id in list(document_ids)[:8]:
            experiments = conn.execute('SELECT * FROM experiments WHERE document_id=? LIMIT 8', (document_id,)).fetchall()
            for exp in experiments:
                ms = conn.execute('SELECT * FROM measurements WHERE experiment_id=? LIMIT 8', (exp['id'],)).fetchall()
                fs = conn.execute('SELECT * FROM findings WHERE experiment_id=? LIMIT 8', (exp['id'],)).fetchall()
                output.append({'document_id': document_id, 'experiment': dict(exp),
                               'measurements': [dict(m) for m in ms], 'findings': [dict(f) for f in fs],
                               'status': 'Unverified until reviewed against original source'})
                if len(output) >= max_records:
                    return output
    return output


def validate_ai_output(raw, candidates):
    """Normalize AI output and prevent unsupported definitive risk/probability claims."""
    if not isinstance(raw, dict):
        raise ValueError('Gemini output must be a JSON object')
    raw['probability_of_damage'] = 'Not quantifiable from supplied evidence'
    raw['preliminary_hazard_classification'] = 'Insufficient Evidence'
    raw['validation_status'] = 'AI-generated evidence review; no operational risk certification'
    raw['evidence_candidates'] = candidates
    raw['verification_required'] = True
    return raw
