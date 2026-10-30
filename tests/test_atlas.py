"""tests for atlas: extraction, graph, llm mode, cli."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from atlas.extract import (clean_object, extract_document,
                           extract_entities, extract_triples, find_entities,
                           split_sentences)
from atlas.graph import Graph
from atlas.llm import LLMError, extract_with_llm
from atlas.cli import main

HERE = os.path.dirname(__file__)
CORPUS = os.path.join(HERE, "..", "examples", "corpus")


class TestSentencesAndEntities(unittest.TestCase):
    def test_split_on_periods_and_newlines(self):
        text = "First sentence. Second one!\nThird line."
        self.assertEqual(split_sentences(text),
                         ["First sentence.", "Second one!", "Third line."])

    def test_multiword_entity(self):
        names = [n for n, _, _ in find_entities("Noah Tyler built Mule.")]
        self.assertIn("Noah Tyler", names)
        self.assertIn("Mule", names)

    def test_sentence_starter_not_an_entity(self):
        names = [n for n, _, _ in find_entities("This is a plain note.")]
        self.assertEqual(names, [])

    def test_single_name_at_start_is_kept(self):
        names = [n for n, _, _ in find_entities("Fibre is a coding agent.")]
        self.assertIn("Fibre", names)

    def test_entity_counts_and_display(self):
        counts, seen = extract_entities("Noah Tyler met Noah Tyler once.")
        self.assertEqual(counts["noah tyler"], 2)
        self.assertEqual(seen["noah tyler"], "Noah Tyler")


class TestTriples(unittest.TestCase):
    def check(self, text, want):
        got = [(s, r, o) for s, r, o, _, _ in extract_triples(text)]
        self.assertEqual(got, want)

    def test_is_a(self):
        self.check("Fibre is a coding agent.",
                   [("Fibre", "is_a", "coding agent")])

    def test_is_a_no_trailing_period(self):
        self.assertEqual(clean_object("coding agent."), "coding agent")

    def test_works_at(self):
        self.check("Noah Tyler works at Layered Innovation.",
                   [("Noah Tyler", "works_at", "Layered Innovation")])

    def test_created_verbs(self):
        self.check("Noah Tyler built Mule.",
                   [("Noah Tyler", "created", "Mule")])
        self.check("Noah Tyler founded Layered Innovation.",
                   [("Noah Tyler", "created", "Layered Innovation")])

    def test_uses_and_runs_on(self):
        self.check("Mule uses an agent loop.",
                   [("Mule", "uses", "agent loop")])
        self.check("Silk runs on Windows.",
                   [("Silk", "runs on", "Windows")])

    def test_part_of_and_lives_in(self):
        self.check("Mule is part of the Fibre project.",
                   [("Mule", "part_of", "Fibre")])
        self.check("Noah Tyler lives in Columbia.",
                   [("Noah Tyler", "lives_in", "Columbia")])

    def test_no_verb_no_triple(self):
        self.check("Fibre and Mule are both tools.",
                   [])

    def test_self_loop_skipped(self):
        self.check("Fibre uses Fibre.",
                   [])

    def test_extract_document(self):
        counts, seen, triples = extract_document(
            "Noah Tyler built Mule. Mule is a coding agent.", source="n.md")
        self.assertEqual(counts["mule"], 2)
        self.assertEqual(len(triples), 2)
        self.assertEqual(triples[0][4], "n.md")


class TestGraph(unittest.TestCase):
    def setUp(self):
        self.g = Graph()
        self.g.add_entity("Noah Tyler", count=True)
        self.g.add_triple("Noah Tyler", "created", "Mule")
        self.g.add_triple("Noah Tyler", "created", "Mule")
        self.g.add_triple("Mule", "uses", "Python")
        self.g.add_triple("Python", "runs_on", "Windows")

    def test_duplicate_triple_bumps_weight(self):
        edge = [e for e in self.g.edges if e["rel"] == "created"][0]
        self.assertEqual(edge["weight"], 2)
        self.assertEqual(len(self.g.edges), 3)

    def test_mention_count_not_bumped_by_triples(self):
        self.assertEqual(self.g.nodes["noah tyler"]["count"], 1)

    def test_neighbors_sorted_by_weight(self):
        rows = self.g.neighbors("Noah Tyler")
        self.assertEqual(rows[0], ("created", "Mule", 2, False))

    def test_neighbors_rel_filter(self):
        rows = self.g.neighbors("Mule", rel="uses")
        self.assertEqual(rows, [("uses", "Python", 1, False)])

    def test_neighbors_incoming_flagged(self):
        rows = self.g.neighbors("Mule")
        incoming = [r for r in rows if r[3]]
        self.assertEqual(incoming, [("created", "Noah Tyler", 2, True)])

    def test_find_substring(self):
        self.assertEqual(self.g.find("noah"), "noah tyler")
        self.assertIsNone(self.g.find("nobody"))

    def test_path_forward(self):
        steps = self.g.path("Noah Tyler", "Windows")
        self.assertEqual(steps, [("Noah Tyler", "created", "Mule"),
                                 ("Mule", "uses", "Python"),
                                 ("Python", "runs_on", "Windows")])

    def test_path_backwards_keeps_edge_direction(self):
        steps = self.g.path("Windows", "Noah Tyler")
        self.assertEqual(steps, [("Python", "runs_on", "Windows"),
                                 ("Mule", "uses", "Python"),
                                 ("Noah Tyler", "created", "Mule")])

    def test_path_none_and_self(self):
        self.assertIsNone(self.g.path("Noah Tyler", "Nobody"))
        self.assertEqual(self.g.path("Mule", "Mule"), [])

    def test_top_nodes(self):
        top = self.g.top_nodes(2)
        self.assertEqual(top[0], ("Noah Tyler", 1))

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "g.json")
            self.g.save(path)
            loaded = Graph.load(path)
        self.assertEqual(loaded.to_dict(), self.g.to_dict())

    def test_merge(self):
        other = Graph()
        other.add_entity("Noah Tyler", count=True)
        other.add_entity("Noah Tyler", count=True)
        other.add_triple("Noah Tyler", "created", "Fibre")
        other.add_triple("Noah Tyler", "created", "Mule")
        self.g.merge(other)
        self.assertEqual(self.g.nodes["noah tyler"]["count"], 3)
        edge = [e for e in self.g.edges
                if e["rel"] == "created" and e["dst"] == "mule"][0]
        self.assertEqual(edge["weight"], 3)
        self.assertIn("fibre", self.g.nodes)

    def test_stats(self):
        stats = self.g.stats()
        self.assertEqual(stats["nodes"], 4)
        self.assertEqual(stats["edges"], 3)
        self.assertEqual(stats["relations"]["created"], 1)


class FakeModelHandler(BaseHTTPRequestHandler):
    mode = "ok"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.mode == "error":
            self.send_response(500)
            self.end_headers()
            return
        if self.mode == "badjson":
            body = {"choices": [{"message": {"content": "not json"}}]}
        elif self.mode == "fenced":
            body = {"choices": [{"message": {"content":
                "```json\n[{\"subject\": \"Noah\", \"relation\": \"created\", "
                "\"object\": \"Mule\"}]\n```"}}]}
        else:
            body = {"choices": [{"message": {"content":
                '[{"subject": "Noah", "relation": "created", '
                '"object": "Mule"}]'}}]}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_fake_server(mode):
    FakeModelHandler.mode = mode
    server = HTTPServer(("127.0.0.1", 0), FakeModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class TestLLM(unittest.TestCase):
    def run_llm(self, mode):
        server = start_fake_server(mode)
        try:
            url = "http://127.0.0.1:%d" % server.server_address[1]
            return extract_with_llm("some text", url, "key", "fake-model")
        finally:
            server.shutdown()
            server.server_close()

    def test_ok(self):
        triples = self.run_llm("ok")
        self.assertEqual(triples, [("Noah", "created", "Mule")])

    def test_fenced_json_stripped(self):
        triples = self.run_llm("fenced")
        self.assertEqual(triples, [("Noah", "created", "Mule")])

    def test_bad_json_raises(self):
        with self.assertRaises(LLMError):
            self.run_llm("badjson")

    def test_http_error_raises(self):
        with self.assertRaises(LLMError):
            self.run_llm("error")

    def test_unreachable_raises(self):
        with self.assertRaises(LLMError):
            extract_with_llm("text", "http://127.0.0.1:1", "k", "m")


class TestCLI(unittest.TestCase):
    def run_cli(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def test_build_query_path_stats_export(self):
        with tempfile.TemporaryDirectory() as d:
            graph = os.path.join(d, "g.json")
            code, out = self.run_cli(["build", "-s", CORPUS, "-o", graph])
            self.assertEqual(code, 0)
            self.assertIn("15 nodes, 16 edges", out)
            code, out = self.run_cli(["query", "Noah Tyler", graph])
            self.assertEqual(code, 0)
            self.assertIn("works_at", out)
            code, out = self.run_cli(["path", "Mule", "Silk", graph])
            self.assertEqual(code, 0)
            self.assertIn("Layered Innovation", out)
            code, out = self.run_cli(["stats", graph])
            self.assertEqual(code, 0)
            self.assertIn("nodes: 15", out)
            code, out = self.run_cli(["export", graph, "--format", "dot"])
            self.assertEqual(code, 0)
            self.assertIn("digraph atlas", out)
            self.assertIn('"Noah Tyler" -> "Mule"', out)

    def test_build_show(self):
        with tempfile.TemporaryDirectory() as d:
            graph = os.path.join(d, "g.json")
            code, out = self.run_cli(["build", "-s", CORPUS, "-o", graph,
                                      "--show"])
            self.assertEqual(code, 0)
            self.assertIn("Noah Tyler --created--> Mule", out)

    def test_merge_cli(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.json")
            b = os.path.join(d, "b.json")
            out = os.path.join(d, "out.json")
            self.run_cli(["build", "-s", CORPUS, "-o", a])
            self.run_cli(["build", "-s", CORPUS, "-o", b])
            code, text = self.run_cli(["merge", a, b, "-o", out])
            self.assertEqual(code, 0)
            self.assertIn("15 nodes, 16 edges", text)

    def test_query_unknown_entity(self):
        with tempfile.TemporaryDirectory() as d:
            graph = os.path.join(d, "g.json")
            self.run_cli(["build", "-s", CORPUS, "-o", graph])
            code, _ = self.run_cli(["query", "Nobody Here", graph])
            self.assertEqual(code, 1)

    def test_build_no_files(self):
        with tempfile.TemporaryDirectory() as d:
            code, _ = self.run_cli(["build", "-s", d, "-o",
                                    os.path.join(d, "g.json")])
            self.assertEqual(code, 1)

    def test_missing_graph(self):
        code, _ = self.run_cli(["stats", "/tmp/does-not-exist-atlas.json"])
        self.assertEqual(code, 1)


class TestMergeAliases(unittest.TestCase):
    def test_subset_merges_into_longer(self):
        g = Graph()
        g.add_entity("Noah", count=True)
        g.add_entity("Noah Tyler", count=True)
        g.add_triple("Noah", "created", "Mule")
        merges = g.merge_aliases()
        self.assertEqual(merges, [("Noah", "Noah Tyler")])
        self.assertNotIn("noah", g.nodes)
        self.assertEqual(g.nodes["noah tyler"]["count"], 2)
        self.assertEqual(len(g.edges), 1)
        self.assertEqual(g.edges[0]["src"], "noah tyler")

    def test_chain_folds_to_longest(self):
        g = Graph()
        g.add_entity("Noah", count=True)
        g.add_entity("Noah Tyler", count=True)
        g.add_entity("Noah Tyler Jr", count=True)
        merges = g.merge_aliases()
        self.assertEqual(merges, [("Noah", "Noah Tyler Jr"),
                                  ("Noah Tyler", "Noah Tyler Jr")])
        self.assertEqual(list(g.nodes), ["noah tyler jr"])
        self.assertEqual(g.nodes["noah tyler jr"]["count"], 3)

    def test_duplicate_edges_collapse(self):
        g = Graph()
        g.add_triple("Noah", "created", "Mule")
        g.add_triple("Noah Tyler", "created", "Mule")
        g.merge_aliases()
        self.assertEqual(len(g.edges), 1)
        self.assertEqual(g.edges[0]["weight"], 2)

    def test_self_loop_dropped(self):
        g = Graph()
        g.add_triple("Noah", "knows", "Noah Tyler")
        g.merge_aliases()
        self.assertEqual(g.edges, [])

    def test_no_subset_no_merge(self):
        g = Graph()
        g.add_triple("Noah Tyler", "created", "Mule")
        self.assertEqual(g.merge_aliases(), [])
        self.assertEqual(len(g.nodes), 2)

    def test_same_words_different_order_not_merged(self):
        g = Graph()
        g.add_entity("Noah Tyler", count=True)
        g.add_entity("Tyler Noah", count=True)
        self.assertEqual(g.merge_aliases(), [])

    def test_merges_reported_sorted(self):
        g = Graph()
        g.add_entity("Noah", count=True)
        g.add_entity("Noah Tyler", count=True)
        g.add_entity("Fibre", count=True)
        g.add_entity("Fibre Project", count=True)
        merges = g.merge_aliases()
        self.assertEqual(merges, [("Fibre", "Fibre Project"),
                                  ("Noah", "Noah Tyler")])

    def test_sources_combined(self):
        g = Graph()
        g.add_entity("Noah", source="a.md")
        g.add_entity("Noah Tyler", source="b.md")
        g.merge_aliases()
        node = g.nodes["noah tyler"]
        self.assertEqual(node["sources"], {"a.md", "b.md"})

    def test_cli_merge_aliases_flag(self):
        with tempfile.TemporaryDirectory() as d:
            notes = os.path.join(d, "notes.md")
            with open(notes, "w") as f:
                f.write("Noah Tyler built Mule.\nNoah demoed Mule yesterday.\n")
            graph = os.path.join(d, "g.json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["build", "-s", d, "-o", graph,
                             "--merge-aliases"])
            out = buf.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("merged alias: Noah -> Noah Tyler", out)
            loaded = Graph.load(graph)
            self.assertNotIn("noah", loaded.nodes)
            self.assertEqual(loaded.nodes["noah tyler"]["count"], 2)


if __name__ == "__main__":
    unittest.main()
