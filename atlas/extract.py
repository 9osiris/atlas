"""pull entities and relations out of plain text, no model needed."""

import re
from collections import Counter

# words that look like entities only because they start a sentence
STOP = {
    "the", "a", "an", "it", "this", "that", "these", "those", "he", "she",
    "we", "they", "you", "i", "in", "on", "at", "for", "with", "and",
    "but", "or", "so", "if", "when", "while", "after", "before", "also",
    "here", "there", "what", "why", "how", "not", "no", "yes", "one",
    "two", "first", "next", "then", "now", "my", "his", "her", "our",
    "their", "your", "its", "from", "into", "over", "under", "by", "of",
    "to", "is", "was", "are", "were", "be", "been", "has", "have", "had",
    "do", "does", "did", "can", "could", "will", "would", "should",
}

# verb phrase -> relation name, checked in order
PATTERNS = [
    (r"\bis\s+(?:a|an|the)\s+", "is_a"),
    (r"\bworks\s+(?:at|for)\s+", "works_at"),
    (r"\b(?:created|built|wrote|made|designed|founded)\s+", "created"),
    (r"\buses\s+", "uses"),
    (r"\bruns\s+on\s+", "runs_on"),
    (r"\bdepends\s+on\s+", "depends_on"),
    (r"\bis\s+part\s+of\s+", "part_of"),
    (r"\bbelongs\s+to\s+", "part_of"),
    (r"\blives\s+in\s+", "lives_in"),
    (r"\blikes\s+", "likes"),
]

CAP_WORD = r"[A-Z][a-zA-Z0-9_-]*"
ENTITY_RE = re.compile(r"\b(" + CAP_WORD + r"(?:\s+" + CAP_WORD + r")*)\b")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text):
    parts = SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def norm(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def find_entities(sentence):
    """capitalized phrases, minus sentence-initial stopwords."""
    out = []
    for m in ENTITY_RE.finditer(sentence):
        phrase = m.group(1)
        words = phrase.split()
        # drop leading stopwords, a sentence starter is not an entity
        while words and words[0].lower() in STOP:
            words.pop(0)
        if not words:
            continue
        if len(words) == 1 and words[0].lower() in STOP:
            continue
        # single capitalized word at the very start of the sentence
        # is usually just grammar, unless it is also seen mid-sentence
        name = " ".join(words)
        out.append((name, m.start(), m.end()))
    return out


def clean_object(raw):
    raw = raw.strip().strip(",;:.")
    raw = re.sub(r"\s+", " ", raw)
    # cut at the next clause boundary
    for stop in (",", " and ", " but ", " which ", " that ", " to "):
        if stop in raw.lower():
            idx = raw.lower().find(stop)
            raw = raw[:idx]
    return raw.strip().strip(",;:.")


def extract_triples(text, source=None):
    """list of (subject, relation, object) from heuristic patterns."""
    triples = []
    for sentence in split_sentences(text):
        entities = find_entities(sentence)
        if not entities:
            continue
        low = sentence.lower()
        for pattern, rel in PATTERNS:
            for m in re.finditer(pattern, low):
                verb_start, verb_end = m.start(), m.end()
                # subject is the last entity ending before the verb
                subj = None
                for name, s, e in entities:
                    if e <= verb_start:
                        subj = name
                if subj is None:
                    continue
                if rel == "is_a":
                    rest = clean_object(sentence[verb_end:])
                    if rest:
                        triples.append((subj, rel, rest, sentence, source))
                    continue
                # object is the first entity starting after the verb
                obj = None
                for name, s, e in entities:
                    if s >= verb_end:
                        obj = name
                        break
                if obj is None:
                    # no capitalized object, take the raw phrase instead,
                    # so "uses an agent loop" still lands as a fact
                    phrase = clean_object(sentence[verb_end:])
                    phrase = re.sub(r"^(a|an|the)\s+", "", phrase,
                                    flags=re.I)
                    if phrase:
                        obj = phrase
                if obj is not None and norm(obj) != norm(subj):
                    triples.append((subj, rel, obj, sentence, source))
    return triples


def extract_entities(text):
    """name -> mention count, first-seen display form kept by caller."""
    counts = Counter()
    seen = {}
    for sentence in split_sentences(text):
        for name, _, _ in find_entities(sentence):
            key = norm(name)
            counts[key] += 1
            seen.setdefault(key, name)
    return counts, seen


def extract_document(text, source=None):
    """everything one file gives us: entities, triples."""
    counts, seen, triples = extract_entities(text)
    triples = extract_triples(text, source=source)
    return counts, seen, triples
