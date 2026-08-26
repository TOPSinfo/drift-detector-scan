"""The one concurrency primitive in this codebase.

`--jobs N` is a pure SCHEDULING knob: it changes when work happens, never what is concluded.
That guarantee rests entirely on this module returning results in INPUT order, so a caller
folding them into a report cannot observe which worker finished first.

Threads, not processes: every unit mapped through here either shells out (ast-grep, git) or
waits on a socket, so the GIL is released for the duration of the work. Processes would add
pickling and start-up cost for no gain.
"""
from __future__ import annotations

import concurrent.futures
from typing import Any


def ordered_map(fn, items, *, jobs=1) -> list[tuple[Any, Exception | None]]:
    """Apply `fn` to each item; return [(result, exc), ...] aligned with `items`.

    Exceptions are CAPTURED, not raised: both call sites already treat a failing item as a
    recorded error rather than an aborted run ("cannot see" is not "clean"), and a pool that
    raised would turn one bad repo into a dead scan.

    jobs<=1 runs inline and constructs no executor - the default path is a plain loop, which
    is what lets CI keep today's behaviour exactly rather than approximately.
    """
    items = list(items)
    if not items:
        return []
    if jobs is None or jobs <= 1:
        return [_call(fn, item) for item in items]

    results: list = [None] * len(items)
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=min(jobs, len(items)))
    try:
        futures = {ex.submit(_call, fn, item): i for i, item in enumerate(items)}
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()
    finally:
        # cancel_futures=True: if a KeyboardInterrupt (or anything else) escapes the loop
        # above, every QUEUED-but-not-started item is dropped instead of run - shutdown does
        # not become a second, unbounded scan while the backlog drains. This does NOT make
        # Ctrl-C instant: futures already RUNNING cannot be killed mid-flight, so the wait is
        # bounded by however many are in flight (at most `jobs` of them), not by the queue.
        ex.shutdown(wait=True, cancel_futures=True)
    return results


def _call(fn, item) -> tuple:
    try:
        return (fn(item), None)
    except Exception as exc:                # NOT BaseException: KeyboardInterrupt must still
        return (None, exc)                  # stop a 25-minute scan, and both call sites already
                                            # catch Exception, so behaviour is unchanged.
