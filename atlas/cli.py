"""command line: build a graph from text, then ask it questions."""

import argparse
import json
import os
import sys

from . import VERSION
from .extract import extract_document, norm
from .graph import Graph
from .llm import LLMError, extract_with_llm

TEXT_EXTS = {".md", ".txt", ".markdown"}


def die(msg):
    print("atlas: " + msg, file=sys.stderr)
    return 1


def iter_files(sources):
    for src in sources:
        if os.path.isfile(src):
            yield src
        elif os.path.isdir(src):
            for root, _dirs, files in os.walk(src):
                for name in sorted(files):
                    path = os.path.join(root, name)
                    if os.path.splitext(name)[1].lower() in TEXT_EXTS:
                        yield path
        else:
            print("atlas: skipping missing path %s" % src, file=sys.stderr)


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def cmd_build(args):
    graph = Graph()
    files = list(iter_files(args.sources))
    if not files:
        return die("no text files found under %s" % " ".join(args.sources))
    for path in files:
        text = read_text(path)
        counts, seen, triples = extract_document(text, source=path)
        for key, count in counts.items():
            for _ in range(count):
                graph.add_entity(seen[key], source=path)
        for subj, rel, obj, _sent, _src in triples:
            graph.add_triple(subj, rel, obj, source=path)
        if args.llm:
            try:
                llm_triples = extract_with_llm(text, args.base_url,
                                               args.api_key, args.model)
            except LLMError as e:
                print("atlas: llm extraction failed for %s: %s" % (path, e),
                      file=sys.stderr)
                continue
            for subj, rel, obj in llm_triples:
                graph.add_triple(subj, rel, obj, source=path)
        if args.show:
            for subj, rel, obj, sent, _src in triples:
                print("  %s --%s--> %s" % (subj, rel, obj))
    graph.save(args.out)
    stats = graph.stats()
    print("built %s: %d nodes, %d edges from %d files"
          % (args.out, stats["nodes"], stats["edges"], len(files)))
    return 0


def load_graph(path):
    if not os.path.isfile(path):
        return None
    return Graph.load(path)


def cmd_query(args):
    graph = load_graph(args.graph)
    if graph is None:
        return die("no graph at %s, run atlas build first" % args.graph)
    key = graph.find(args.name)
    if key is None:
        return die("no entity matching %r" % args.name)
    node = graph.nodes[key]
    print("%s (mentioned %d times)" % (node["name"], node["count"]))
    rows = graph.neighbors(args.name, rel=args.rel)
    if not rows:
        print("  no relations recorded")
        return 0
    for rel, name, weight, incoming in rows:
        if incoming:
            print("  %s --%s--> %s (x%d)" % (name, rel, node["name"], weight))
        else:
            print("  --%s--> %s (x%d)" % (rel, name, weight))
    return 0


def cmd_path(args):
    graph = load_graph(args.graph)
    if graph is None:
        return die("no graph at %s, run atlas build first" % args.graph)
    steps = graph.path(args.start, args.end)
    if steps is None:
        print("no path between %s and %s" % (args.start, args.end))
        return 0
    if not steps:
        print("%s is %s" % (args.start, args.end))
        return 0
    for i, (frm, rel, to) in enumerate(steps):
        print("%s --%s--> %s" % (frm, rel, to))
    return 0


def cmd_stats(args):
    graph = load_graph(args.graph)
    if graph is None:
        return die("no graph at %s, run atlas build first" % args.graph)
    stats = graph.stats()
    print("nodes: %d" % stats["nodes"])
    print("edges: %d" % stats["edges"])
    for rel, count in sorted(stats["relations"].items()):
        print("  %-12s %d" % (rel, count))
    print("most mentioned:")
    for name, count in stats["top"]:
        print("  %-30s %d" % (name, count))
    return 0


def to_dot(graph):
    lines = ["digraph atlas {"]
    for key, node in sorted(graph.nodes.items()):
        label = node["name"].replace('"', "'")
        lines.append('  "%s" [label="%s"];' % (key, label))
    for edge in graph.edges:
        src = graph.nodes[edge["src"]]["name"].replace('"', "'")
        dst = graph.nodes[edge["dst"]]["name"].replace('"', "'")
        lines.append('  "%s" -> "%s" [label="%s"];'
                     % (src, dst, edge["rel"]))
    lines.append("}")
    return "\n".join(lines) + "\n"


def cmd_export(args):
    graph = load_graph(args.graph)
    if graph is None:
        return die("no graph at %s, run atlas build first" % args.graph)
    if args.format == "dot":
        text = to_dot(graph)
    else:
        text = json.dumps(graph.to_dict(), indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote %s" % args.out)
    else:
        sys.stdout.write(text)
    return 0


def cmd_merge(args):
    first = load_graph(args.a)
    second = load_graph(args.b)
    if first is None:
        return die("no graph at %s" % args.a)
    if second is None:
        return die("no graph at %s" % args.b)
    first.merge(second)
    first.save(args.out)
    stats = first.stats()
    print("merged into %s: %d nodes, %d edges"
          % (args.out, stats["nodes"], stats["edges"]))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="atlas",
                                     description="knowledge graph from notes")
    parser.add_argument("--version", action="version",
                        version="atlas " + VERSION)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="build a graph from text files")
    p.add_argument("-s", "--sources", nargs="+", required=True,
                   help="files or directories to read")
    p.add_argument("-o", "--out", default="atlas.json",
                   help="graph file to write (default atlas.json)")
    p.add_argument("--show", action="store_true",
                   help="print each extracted triple")
    p.add_argument("--llm", action="store_true",
                   help="also extract triples with a model")
    p.add_argument("--base-url", default="https://api.openai.com",
                   help="openai-compatible base url")
    p.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""),
                   help="api key (or OPENAI_API_KEY)")
    p.add_argument("--model", default="gpt-4o-mini",
                   help="model for llm extraction")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("query", help="show what an entity connects to")
    p.add_argument("name", help="entity name, substring match ok")
    p.add_argument("graph", nargs="?", default="atlas.json")
    p.add_argument("--rel", default=None, help="only this relation")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("path", help="shortest path between two entities")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("graph", nargs="?", default="atlas.json")
    p.set_defaults(func=cmd_path)

    p = sub.add_parser("stats", help="graph size and top entities")
    p.add_argument("graph", nargs="?", default="atlas.json")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("export", help="dump the graph as dot or json")
    p.add_argument("graph", nargs="?", default="atlas.json")
    p.add_argument("--format", choices=["dot", "json"], default="dot")
    p.add_argument("-o", "--out", default=None)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("merge", help="merge two graphs into one")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("-o", "--out", default="atlas.json")
    p.set_defaults(func=cmd_merge)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
