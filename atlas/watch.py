"""watch mode: rebuild the graph whenever the notes change."""

import os
import time

from .cli import do_build, iter_files


def snapshot(sources):
    snap = {}
    for path in iter_files(sources):
        try:
            st = os.stat(path)
        except OSError:
            continue
        snap[path] = (st.st_mtime_ns, st.st_size)
    return snap


def diff(old, new):
    changed = []
    for path, stamp in new.items():
        if path not in old or old[path] != stamp:
            changed.append(path)
    for path in old:
        if path not in new:
            changed.append(path)
    return sorted(changed)


def run_watch(args, interval=2.0, stop_after=None):
    # initial build so the graph exists before the first edit
    do_build(args)
    last = snapshot(args.sources)
    rebuilds = 0
    print("watching %s (every %.1fs, ctrl-c to stop)"
          % (", ".join(args.sources), interval))
    try:
        while True:
            time.sleep(interval)
            now = snapshot(args.sources)
            changed = diff(last, now)
            if not changed:
                continue
            last = now
            print("changed: %s" % ", ".join(os.path.basename(p)
                                            for p in changed))
            do_build(args)
            rebuilds += 1
            if stop_after is not None and rebuilds >= stop_after:
                return rebuilds
    except KeyboardInterrupt:
        print("stopped watching")
        return rebuilds
