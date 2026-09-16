"""The warm process pool, and the properties that make it safe to use.

No real `claude` process is started here. A pool that only works against the
real CLI could only be tested by spending six seconds and a model call per
assertion, so the process is faked: a small script that speaks the same
stream-json protocol. What is being tested is the pool's own contract --
one question per process, always retire, never lose an answer to a pool
problem -- not Claude's behaviour.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from llm_api.cli_pool import ClaudePool

# A stand-in for `claude`. Reads stream-json user messages on stdin and
# answers each with a result event, counting how many it has seen so that a
# test can prove a process is never asked twice.
FAKE = r'''
import json, sys
seen = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    seen += 1
    msg = json.loads(line)
    text = msg["message"]["content"][0]["text"]
    print(json.dumps({
        "type": "result",
        "result": f"answer to {text} (message #{seen} to this process)",
        "duration_ms": 5,
        "session_id": "fake",
        "usage": {"input_tokens": 1, "output_tokens": 2,
                  "cache_read_input_tokens": 3},
    }), flush=True)
'''


@pytest.fixture
def fake_cli(tmp_path):
    """A command that behaves like `claude --input-format stream-json`."""
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE, encoding="utf-8")

    return sys.executable, str(script)


def _pool(fake, size=2, warmup=0.05, reply_timeout=10.0):
    """A pool whose processes are the fake, not the real CLI.

    Built at size 0 so the constructor spawns nothing: the pool's own flags
    (`-p`, `--system-prompt`, ...) mean nothing to a python script, and a
    process spawned before the swap would die and skew the test.
    """
    exe, script = fake
    pool = ClaudePool(command=exe, system_prompt="SP", model=None,
                      size=0, warmup=warmup, reply_timeout=reply_timeout)
    pool._argv = lambda: [exe, script]
    pool._size = size
    pool._refill()
    return pool


def test_a_question_gets_an_answer(fake_cli):
    pool = _pool(fake_cli)
    try:
        run = pool.ask("show me the items")
        assert run is not None
        assert run.ok
        assert "show me the items" in run.result_text
    finally:
        pool.close()


def test_each_process_is_asked_exactly_one_question(fake_cli):
    """The property that keeps a pooled turn identical to an unpooled one.

    The fake numbers every message it receives, so a process that had been
    reused would answer "message #2". Any answer but #1 means conversation
    history is accumulating where the pipeline cannot see it.
    """
    pool = _pool(fake_cli, size=3)
    try:
        for _ in range(5):
            run = pool.ask("q")
            assert run is not None
            assert "message #1 to this process" in run.result_text
    finally:
        pool.close()


def test_the_process_is_dead_once_it_has_answered(fake_cli):
    pool = _pool(fake_cli)
    try:
        pool.ask("q")
        time.sleep(0.2)
        # Nothing used is still parked: everything idle must be a fresh spawn.
        with pool._lock:
            parked = list(pool._idle)
        assert all(w.alive() for w in parked)
    finally:
        pool.close()


def test_usage_and_timings_come_back(fake_cli):
    pool = _pool(fake_cli)
    try:
        run = pool.ask("q")
        assert run.prompt_tokens == 1 + 3       # input + cache read
        assert run.completion_tokens == 2
        assert run.cache_read_tokens == 3
        assert run.wall_ms > 0
        assert run.warm_ms >= 0
    finally:
        pool.close()


def test_a_disabled_pool_declines_rather_than_answering(fake_cli):
    """size=0 is the escape hatch back to the one-shot subprocess."""
    exe, script = fake_cli
    pool = ClaudePool(command=exe, system_prompt="SP", model=None, size=0)
    try:
        assert pool.ask("q") is None
    finally:
        pool.close()


def test_a_closed_pool_declines(fake_cli):
    pool = _pool(fake_cli)
    pool.close()
    assert pool.ask("q") is None


def test_a_process_that_says_nothing_declines_rather_than_hanging(tmp_path):
    """A wedged CLI must become a fallback, not a stalled request.

    Returning None is what lets the provider spawn a one-shot process
    instead, so the user still gets an answer -- slowly rather than never.
    """
    script = tmp_path / "mute.py"
    script.write_text("import sys, time\nsys.stdin.readline()\ntime.sleep(30)\n",
                      encoding="utf-8")
    pool = ClaudePool(command=sys.executable, system_prompt="SP", model=None,
                      size=0, warmup=0.05, reply_timeout=0.5)
    pool._argv = lambda: [sys.executable, str(script)]
    pool._size = 1
    pool._refill()
    try:
        started = time.perf_counter()
        assert pool.ask("q") is None
        assert time.perf_counter() - started < 5, "should give up on the timeout"
    finally:
        pool.close()


def test_a_process_that_dies_declines_rather_than_raising(tmp_path):
    script = tmp_path / "dies.py"
    script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    pool = ClaudePool(command=sys.executable, system_prompt="SP", model=None,
                      size=0, warmup=0.05, reply_timeout=2.0)
    pool._argv = lambda: [sys.executable, str(script)]
    pool._size = 1
    pool._refill()
    time.sleep(0.3)
    try:
        assert pool.ask("q") is None
    finally:
        pool.close()


def test_close_leaves_nothing_running(fake_cli):
    pool = _pool(fake_cli, size=3)
    time.sleep(0.3)
    with pool._lock:
        procs = [w.proc for w in pool._idle]
    assert procs, "expected the pool to have warmed something"
    pool.close()
    time.sleep(0.3)
    assert all(p.poll() is not None for p in procs)


def test_the_question_reaches_the_process_verbatim(fake_cli):
    """The user prompt must not be reshaped on its way through the pool."""
    pool = _pool(fake_cli)
    try:
        odd = 'quotes " and \\ backslash and \n newline'
        run = pool.ask(odd)
        assert run is not None
        assert odd in run.result_text
    finally:
        pool.close()
