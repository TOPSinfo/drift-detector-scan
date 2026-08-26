import threading
import time

import pytest

from agent.lib import pool


def test_ordered_map_returns_results_in_input_order_not_completion_order():
    """Item 0 sleeps longest, so completion order is the REVERSE of input order.

    If results were collected as futures completed, this returns [4,3,2,1,0].
    """
    def slow(i):
        time.sleep((5 - i) * 0.02)
        return i

    out = pool.ordered_map(slow, [0, 1, 2, 3, 4], jobs=5)

    assert [value for value, _exc in out] == [0, 1, 2, 3, 4]
    assert all(exc is None for _value, exc in out)


def test_ordered_map_captures_per_item_errors_against_the_right_index():
    """One item raising must not abort the rest, and the error must stay aligned."""
    def sometimes(i):
        if i == 1:
            raise ValueError("boom")
        return i * 10

    out = pool.ordered_map(sometimes, [0, 1, 2], jobs=3)

    assert out[0] == (0, None)
    assert out[2] == (20, None)
    value, exc = out[1]
    assert value is None
    assert isinstance(exc, ValueError) and str(exc) == "boom"


def test_ordered_map_with_jobs_1_never_constructs_an_executor(monkeypatch):
    """The default must be today's serial code, not a pool of size one.

    That distinction is what keeps the CI risk at zero, so it is asserted rather than
    assumed: constructing an executor at jobs=1 fails this test loudly.
    """
    def explode(*a, **kw):
        raise AssertionError("ThreadPoolExecutor must not be constructed when jobs=1")

    monkeypatch.setattr(pool.concurrent.futures, "ThreadPoolExecutor", explode)

    assert pool.ordered_map(lambda i: i + 1, [1, 2, 3], jobs=1) == [(2, None), (3, None), (4, None)]


def test_ordered_map_on_an_empty_list_is_an_empty_list():
    assert pool.ordered_map(lambda i: i, [], jobs=4) == []


def test_ordered_map_stops_early_on_keyboard_interrupt():
    """A worker raising KeyboardInterrupt must not let the pool drain the whole queue.

    With jobs=2 over 6 items, at most 2 items can be RUNNING at the moment item 0 raises;
    the other 4 are still QUEUED, not yet started. If `ordered_map` lets the executor shut
    down with the default `cancel_futures=False`, every queued item still runs to completion
    before the KeyboardInterrupt reaches the caller - Ctrl-C during a 53-repo scan would not
    cut it short, it would stall until all workers drained the backlog. Each non-raising item
    sleeps 0.2s AFTER recording that it started, which is generous enough (three orders of
    magnitude above the microsecond-scale exception propagation this test races against)
    that a freed-up worker cannot cascade through more than one extra queued item before the
    main thread notices future 0 is done and the assertion below is checked.
    """
    started = []
    lock = threading.Lock()

    def worker(i):
        with lock:
            started.append(i)
        if i == 0:
            raise KeyboardInterrupt("simulated Ctrl-C")
        time.sleep(0.2)
        return i

    with pytest.raises(KeyboardInterrupt):
        pool.ordered_map(worker, list(range(6)), jobs=2)

    # Well under the full 6: only the items already RUNNING (bounded by jobs=2) plus at most
    # one more a freed-up worker grabbed before the interrupt propagated should have started.
    assert len(started) <= 4, f"expected only a few items to start, got {started}"
