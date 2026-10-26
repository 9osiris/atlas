"""optional model extraction: ask an openai-compatible api for triples."""

import json
import urllib.request
import urllib.error

PROMPT = (
    "Extract facts from the text below as a JSON list of objects with "
    "keys subject, relation, object. Use short lowercase relations like "
    "works_at, created, uses, is_a, part_of. Only include facts stated "
    "in the text. Reply with JSON only, no markdown fences."
)


class LLMError(Exception):
    pass


def extract_with_llm(text, base_url, api_key, model, timeout=30):
    url = base_url.rstrip("/") + "/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        raise LLMError("api returned %s" % e.code)
    except urllib.error.URLError as e:
        raise LLMError("could not reach api: %s" % e.reason)
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("unexpected api response shape")
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").strip()
        if content.lower().startswith("json"):
            content = content[4:].strip()
    try:
        items = json.loads(content)
    except json.JSONDecodeError:
        raise LLMError("model did not return valid json")
    triples = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subj, rel, obj = (item.get("subject"), item.get("relation"),
                          item.get("object"))
        if subj and rel and obj:
            triples.append((str(subj), str(rel).lower().replace(" ", "_"),
                            str(obj)))
    return triples
