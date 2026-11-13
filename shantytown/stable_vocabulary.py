"""Exact published vocabulary for dual readers; never an instance allocator."""
LEGACY = "http://aegis.gastown.local/ontology/"
# ownership.json SHA256 a389be53b74259d0c515ff6db16d602474dc5fe38dc6cc47f0f54a2d1347d34e.
TERMS = {'Decision': 'https://w3id.org/intigraph/quipu/ns#Decision',
 'WorkflowRun': 'https://w3id.org/intigraph/quipu/ns#WorkflowRun',
 'by': 'https://w3id.org/intigraph/camayoc/core/ns#by',
 'commitSha': 'https://w3id.org/intigraph/camayoc/delivery/ns#commitSha',
 'currentState': 'https://w3id.org/intigraph/camayoc/core/ns#currentState',
 'outcome': 'https://w3id.org/intigraph/camayoc/core/ns#outcome',
 'predicateId': 'https://w3id.org/intigraph/camayoc/core/ns#predicateId',
 'runOf': 'https://w3id.org/intigraph/camayoc/core/ns#runOf',
 'signature': 'https://w3id.org/intigraph/camayoc/core/ns#signature',
 'targetRef': 'https://w3id.org/intigraph/camayoc/core/ns#targetRef',
 'verifier': 'https://w3id.org/intigraph/camayoc/core/ns#verifier'}


def aliases(name):
    return (LEGACY + name, TERMS[name])


def pattern(subject, name, value):
    """Grouped explicit UNION: older native readers retain literal objects."""
    return "{ " + " UNION ".join(
        "{ " + subject + " <" + iri + "> " + value + " }" for iri in aliases(name)) + " } "
