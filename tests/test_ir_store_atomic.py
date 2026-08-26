"""REGRESSION: _write must be atomic, or a concurrent --jobs>1 scan reads a torn cache file.

`_repo_path` keys the per-repo cache on sha256(ident)@head_sha@rules_sig, not on the repo's
absolute directory — so two distinct discovered repos that share a git identity and HEAD sha
(e.g. two configured roots each containing an identical `web/` checkout) write the SAME cache
path. Serially that is harmless (one write lands after the other). Under --jobs > 1, one
worker's write can race another worker's read of the same path. `Path.write_text` (the old
`_write`) truncates the file before writing the new bytes, so a reader landing in that window
gets a truncated, unparseable JSON file. `load_repo_cache` has no guard around that — the
`json.JSONDecodeError` propagates out of the worker, the concurrency pool captures it, and the
repo lands in `coverage["reposErrored"]`: a perfectly scannable repo reported as an error, which
is exactly the "cannot see" masquerading as a result this project exists to refuse.

This test proves the fix: a reader concurrent with writers must NEVER observe a partial file —
every read is either None (file not yet created) or a fully-parsed dict, never a raise.
"""
from __future__ import annotations

import threading

from agent.lib import ir_store


def test_concurrent_reads_never_see_a_torn_write(tmp_path):
    state_dir = str(tmp_path)
    path, sha = "acme/web", "deadbeef"

    # A large-ish payload gives a non-atomic write() a real truncation window to be caught in —
    # a tiny record can complete in one syscall often enough to make the test flaky-green.
    def make_record(n: int) -> dict:
        return {
            "path": path,
            "head_sha": sha,
            "n": n,
            "endpoints": [
                {"vendor": f"vendor-{i}", "file": f"src/mod_{i}.py", "line": i,
                 "method": "GET", "url": f"https://api.example.com/v{i}/resource/{i}"}
                for i in range(400)
            ],
        }

    ITERATIONS = 300
    stop = threading.Event()
    failures: list[str] = []

    def writer():
        for n in range(ITERATIONS):
            ir_store.save_repo_cache(state_dir, path, sha, make_record(n))
        stop.set()

    def reader():
        while not stop.is_set():
            try:
                doc = ir_store.load_repo_cache(state_dir, path, sha)
            except Exception as exc:  # the bug: json.JSONDecodeError on a torn read
                failures.append(f"{type(exc).__name__}: {exc}")
                continue
            if doc is not None:
                # A torn read can also parse successfully into a truncated-but-valid-JSON
                # partial value (e.g. a cut-off list) rather than raising, so check shape too.
                if doc.get("path") != path or "endpoints" not in doc or \
                        len(doc.get("endpoints") or []) != 400:
                    failures.append(f"partial/malformed doc observed: {doc}")

    writer_thread = threading.Thread(target=writer)
    reader_threads = [threading.Thread(target=reader) for _ in range(4)]

    writer_thread.start()
    for t in reader_threads:
        t.start()
    writer_thread.join()
    for t in reader_threads:
        t.join()

    assert not failures, f"{len(failures)} torn/failed read(s), e.g. {failures[:3]}"
