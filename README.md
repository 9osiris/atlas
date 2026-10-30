atlas - knowledge graph from your notes [experimental project]

disclaimer: this is a scratch tool, not a serious product. the
extraction is regex heuristics, not nlp, so it misses things and
sometimes pulls out nonsense. it works for my own notes and probably
nobody else's.

why i made this
i keep notes about everything i build, fibre, mule, cognix, all of it,
and the notes just sit there as flat text. embeddings search finds
similar chunks but it never tells me how things connect. i wanted the
cheap version of a semantic memory: read a folder of notes, pull out
who did what to what, and let me ask it questions. who built mule.
what connects mule to silk. that kind of thing. i avoided any ml deps
on purpose, the heuristic pass runs anywhere with just python, and
theres a --llm flag for when the regexes miss too much. the graph is a
plain json file because i wanted to read it by hand when the triples
look wrong.

the guide
needs python 3.9+, no dependencies.

```
pip install .
atlas build -s ./notes -o graph.json
atlas query "Noah Tyler"
atlas path Mule Silk
atlas stats
```

build reads .md and .txt files under the sources you give it and
writes the graph to atlas.json by default. --show prints each triple
as it is found. query shows what an entity connects to, substring
match is fine. path prints the shortest chain between two entities,
in true edge direction. stats prints size, relation counts, and the
most mentioned entities. export dumps the graph as graphviz dot or
json:

```
atlas export graph.json --format dot -o graph.dot
atlas merge a.json b.json -o combined.json
```

how it extracts
entities are capitalized phrases, sentence starters like "this" are
skipped. relations come from verb patterns: is a, works at/for,
created/built/wrote/made/designed/founded, uses, runs on, depends on,
is part of, belongs to, lives in, likes. the object is the next
capitalized phrase after the verb, or the raw phrase when there is
none, so "uses an agent loop" still lands. same triple twice just
bumps its weight.

merging aliases
notes are messy: one file says "noah" and another says "noah tyler"
and you get two nodes that are obviously the same person. build with
--merge-aliases and any entity whose name is a word subset of another
gets folded into the longer one, counts and sources combined, edges
rewired. it prints every merge it makes:

```
atlas build -s ./notes -o graph.json --merge-aliases
merged alias: Noah -> Noah Tyler
```

it is opt-in because the rule is dumb and it will merge things you
did not want merged, like new york and new york times. read the
printed list before you trust the graph.

llm mode
if the regexes miss too much, --llm asks a model for triples instead.
it needs an openai-compatible endpoint:

```
atlas build -s ./notes --llm --model gpt-4o-mini
```

uses OPENAI_API_KEY from the environment unless you pass --api-key.
the model is told to reply with json only, no fences, and anything
that does not parse is skipped with a warning. llm triples are added
on top of the heuristic ones, never instead of them.

examples/corpus has a tiny demo set, try:

```
atlas build -s examples/corpus -o /tmp/demo.json --show
atlas query Fibre /tmp/demo.json
```
