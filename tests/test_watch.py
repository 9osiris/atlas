"""tests for atlas watch mode: snapshots, diffs, rebuild loop."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from atlas.cli import build_parser
from atlas.watch import diff, run_watch, snapshot

NOTES = "Noah Tyler built Mule. Mule uses an agent loop.\n"


def make_args(tmp, sources):
    args = build_parser().parse_args(
        ["watch", "-s"] + sources + ["-o", os.path.join(tmp, "graph.json")])
    args.llm = False
    return args


class TestSnapshot(unittest.TestCase):
    def test_unchanged_files_have_empty_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.md")
            with open(path, "w") as f:
                f.write(NOTES)
            self.assertEqual(diff(snapshot([tmp]), snapshot([tmp])), [])

    def test_added_file_shows_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.md")
            with open(path, "w") as f:
                f.write(NOTES)
            before = snapshot([tmp])
            with open(os.path.join(tmp, "more.md"), "w") as f:
                f.write("Silk runs on Fibre.\n")
            changed = diff(before, snapshot([tmp]))
            self.assertEqual(len(changed), 1)
            self.assertTrue(changed[0].endswith("more.md"))

    def test_removed_file_shows_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.md")
            with open(path, "w") as f:
                f.write(NOTES)
            before = snapshot([tmp])
            os.remove(path)
            self.assertEqual(diff(before, snapshot([tmp])), [path])

    def test_edited_file_shows_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.md")
            with open(path, "w") as f:
                f.write(NOTES)
            before = snapshot([tmp])
            time.sleep(0.02)
            with open(path, "w") as f:
                f.write(NOTES + "Silk runs on Fibre.\n")
            self.assertEqual(diff(before, snapshot([tmp])), [path])

    def test_non_text_files_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.md")
            with open(path, "w") as f:
                f.write(NOTES)
            before = snapshot([tmp])
            with open(os.path.join(tmp, "photo.png"), "wb") as f:
                f.write(b"\x89PNG")
            self.assertEqual(diff(before, snapshot([tmp])), [])


class TestRunWatch(unittest.TestCase):
    def test_rebuilds_after_an_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.md")
            with open(path, "w") as f:
                f.write(NOTES)
            args = make_args(tmp, [tmp])
            out = os.path.join(tmp, "graph.json")

            def edit_later():
                time.sleep(0.4)
                with open(path, "a") as f:
                    f.write("Silk runs on Fibre.\n")

            thread = threading.Thread(target=edit_later)
            thread.start()
            with redirect_stdout(StringIO()):
                rebuilds = run_watch(args, interval=0.1, stop_after=1)
            thread.join()
            self.assertEqual(rebuilds, 1)
            with open(out) as f:
                graph = json.load(f)
            names = [n["name"] for n in graph["nodes"].values()]
            self.assertIn("Silk", names)

    def test_initial_build_runs_before_any_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.md")
            with open(path, "w") as f:
                f.write(NOTES)
            args = make_args(tmp, [tmp])
            out = os.path.join(tmp, "graph.json")

            def edit_later():
                time.sleep(0.4)
                with open(path, "a") as f:
                    f.write("Silk runs on Fibre.\n")

            thread = threading.Thread(target=edit_later)
            thread.start()
            with redirect_stdout(StringIO()):
                run_watch(args, interval=0.1, stop_after=1)
            thread.join()
            self.assertTrue(os.path.isfile(out))

    def test_watch_parser_defaults(self):
        args = build_parser().parse_args(["watch", "-s", "./notes"])
        self.assertEqual(args.interval, 2.0)
        self.assertEqual(args.out, "atlas.json")
        self.assertFalse(args.merge_aliases)
        self.assertFalse(args.cooccur)


if __name__ == "__main__":
    unittest.main()
