"""Pre-warmed Claude Code processes, one query each.

The Claude Code CLI costs about 4.5 seconds to start, and that cost is paid on
every query because `CLILocalProvider` spawns a fresh `claude -p` per call and
throws it away. Measured directly on this machine: `claude --version` returns
in 0.32s, but `claude -p "reply with one word"` -- with no system prompt at
all -- takes 5.7 to 7.7s, and handing it the real 26KB system prompt makes it
no slower. So the cost is neither the prompt nor the inference. It is startup:
config resolution, credential load, session setup, teardown.

`--input-format stream-json` lets a process sit on stdin waiting for work, so
that startup can happen before anyone is waiting for an answer. A process is
spawned, given a few seconds to finish booting, and only then handed a
question. Measured against warm-up time, with the real prompt and real
questions:

    warm-up 0.0s -> query 4.54s / 4.71s
    warm-up 1.0s -> query 3.44s / 3.54s
    warm-up 2.0s -> query 2.22s / 2.58s
    warm-up 3.0s -> query 1.87s / 1.87s      <- plateau
    warm-up 4.0s -> query 2.16s / 2.39s

Three seconds is where it flattens; more buys nothing.

**Each process serves exactly one question and is then killed.** That is not
frugality, it is correctness. A reused process accumulates conversation
history inside the CLI, and this pipeline already builds and sends its own
context block per turn (`pipeline/lean_runner.py`). Two histories would
disagree. It is measurable: across four turns in one process,
`cache_read_input_tokens` climbed 10,189 -> 13,662, and a question repeated as
turn 4 came back faster than as turn 1 because the model had already answered
it. Retiring after one question means the user's question is the process's
first and only message, so a pooled turn and an unpooled turn see exactly the
same conversation -- which is what makes this a latency change and not a
behaviour change.

The pool is therefore a *replacement* pool rather than a reuse pool: it keeps
N booted processes standing by, and every checkout is followed by a fresh
spawn to take that slot.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field

from pipeline.models import ClaudeRun

# Where the warm-up curve above flattens. Paid on a background thread, so it
# costs wall clock only when the pool is empty and someone is waiting.
DEFAULT_WARMUP_SECONDS = 3.0

# Standing processes.
#
# Sized to cover the warm-up, not to cover concurrency. A replacement is only
# spawned once its predecessor has been used, so it needs DEFAULT_WARMUP
# seconds before it can serve anything; with questions arriving faster than
# that -- and a warm answer takes about two seconds -- a small pool runs dry
# and the next caller waits for a half-booted process. Measured: at size 2 the
# wait showed up as 0.38s on every query; size 3 fixed the average but left a
# p95 of 3.96s, which is the same starvation surfacing on a run of
# back-to-back questions. Four covers the warm-up at the rate a warm answer
# is produced, with one spare for the variance.
DEFAULT_POOL_SIZE = 4

# How long to wait for a `result` event before giving up on a process. Far
# below CLAUDE_TIMEOUT_SECONDS (180s by default): a wedged CLI holding an HTTP
# request for three minutes is a worse failure than a fast error.
DEFAULT_REPLY_TIMEOUT = 90.0


@dataclass
class _Warm:
    """One booted process, waiting for its single question.

    Its stdout is drained by a thread from the moment it starts. That is not
    tidiness: `readline()` on a pipe blocks until a line arrives, so a caller
    reading inline cannot honour a timeout, and a CLI that wedges after
    accepting the question would hold the request until the process died. A
    queue makes the deadline real. It also mops up the events the CLI emits
    before it is asked anything -- hook lifecycle, init -- so they cannot be
    mistaken for a reply.
    """

    proc: subprocess.Popen
    spawned_at: float
    lines: "queue.Queue[str | None]" = field(default_factory=queue.Queue)

    def __post_init__(self) -> None:
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        try:
            for line in self.proc.stdout:
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self.lines.put(None)      # sentinel: the process has stopped talking

    @property
    def warm_ms(self) -> float:
        return (time.perf_counter() - self.spawned_at) * 1000

    def ready(self, warmup: float) -> bool:
        return (time.perf_counter() - self.spawned_at) >= warmup

    def alive(self) -> bool:
        return self.proc.poll() is None

    def kill(self) -> None:
        """End the process. Terminate first, close after.

        Order matters and is not obvious. Closing `stdout` while the drain
        thread is blocked inside it waits for that thread's lock, which is
        only released when the read returns -- so a process that had stopped
        talking made `kill` block until it exited by itself. Measured at 29.5s
        against a deliberately mute process, which is the exact hang the reply
        timeout exists to prevent. Terminating first unblocks the reader, and
        then the handles close instantly.
        """
        try:
            self.proc.terminate()
        except Exception:
            pass
        # stdin is ours to close and nothing is blocked on it. stdout and
        # stderr are left to the drain thread and to garbage collection: the
        # child is already terminating, so they are about to hit EOF anyway.
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass


class ClaudePool:
    """Keeps warm `claude` processes standing by, one question each.

    Thread-safe: the HTTP server is threaded and two conversations can be in
    flight at once.
    """

    def __init__(self, command: str, system_prompt: str, model: str | None,
                 size: int = DEFAULT_POOL_SIZE,
                 warmup: float = DEFAULT_WARMUP_SECONDS,
                 reply_timeout: float = DEFAULT_REPLY_TIMEOUT):
        self._command = command
        self._system_prompt = system_prompt
        self._model = model
        self._size = max(0, size)
        self._warmup = warmup
        self._reply_timeout = reply_timeout

        self._lock = threading.Lock()
        self._idle: list[_Warm] = []
        self._pending = 0          # spawns in flight, so we do not over-fill
        self._closed = False
        self._refill()

    # ------------------------------------------------------------- spawning --

    def _argv(self) -> list[str]:
        cmd = [
            self._command, "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--system-prompt", self._system_prompt,
            "--tools", "",
            "--permission-mode", "bypassPermissions",
        ]
        if self._model:
            cmd += ["--model", self._model]
        return cmd

    def _spawn_one(self) -> None:
        """Boot one process and park it. Runs on a background thread."""
        warm = None
        try:
            proc = subprocess.Popen(
                self._argv(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", bufsize=1,
            )
            warm = _Warm(proc=proc, spawned_at=time.perf_counter())
        except OSError:
            # Could not spawn at all. The caller falls back to the one-shot
            # path, so this is a lost optimisation rather than a lost answer.
            warm = None
        finally:
            with self._lock:
                self._pending -= 1
                if warm is not None and not self._closed:
                    self._idle.append(warm)
                elif warm is not None:
                    warm.kill()

    def _refill(self) -> None:
        """Top the pool back up to `size`. Never blocks the caller."""
        with self._lock:
            if self._closed:
                return
            want = max(0, self._size - len(self._idle) - self._pending)
            self._pending += want
        for _ in range(want):
            threading.Thread(target=self._spawn_one, daemon=True).start()

    # ------------------------------------------------------------ checkout --

    def _take(self, deadline: float) -> _Warm | None:
        """A process that has finished booting, or None if none arrives."""
        while time.perf_counter() < deadline:
            with self._lock:
                if self._closed:
                    return None
                # Drop anything that died while parked.
                self._idle = [w for w in self._idle if w.alive()]
                for i, warm in enumerate(self._idle):
                    if warm.ready(self._warmup):
                        return self._idle.pop(i)
            time.sleep(0.05)
        return None

    def ask(self, user_prompt: str) -> ClaudeRun | None:
        """Put one question to a warm process and retire it.

        Returns None when the pool could not serve the question, which is the
        caller's signal to fall back to spawning a one-shot process. Returning
        None rather than raising keeps the fallback boring: a pool problem must
        never turn into a failed answer.
        """
        if self._size == 0 or self._closed:
            return None

        started = time.perf_counter()
        warm = self._take(started + self._warmup + 5.0)
        if warm is None:
            # Nothing warm and none arrived in time. Top up for next time and
            # let the caller take the slow path rather than wait longer.
            self._refill()
            return None

        warm_ms = warm.warm_ms
        try:
            run = self._converse(warm, user_prompt, started)
        finally:
            # One question per process, always -- see the module docstring.
            warm.kill()
            # Refill only now. Booting a Claude Code process is expensive
            # enough to slow the query running beside it: refilling before
            # the question was measurably worse, pushing the CLI's own
            # reported time from ~1.9s to ~2.8s. The pool is sized so that
            # taking one still leaves one for a concurrent question.
            self._refill()

        if run is not None:
            run.warm_ms = warm_ms
        return run

    def _converse(self, warm: _Warm, user_prompt: str,
                  started: float) -> ClaudeRun | None:
        from llm_api.cli_provider import apply_result_event

        message = {"type": "user", "message": {
            "role": "user", "content": [{"type": "text", "text": user_prompt}]}}
        try:
            warm.proc.stdin.write(json.dumps(message) + "\n")
            warm.proc.stdin.flush()
        except (OSError, ValueError):
            return None

        deadline = time.perf_counter() + self._reply_timeout
        tools: list[str] = []
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return None                       # wedged; caller falls back
            try:
                line = warm.lines.get(timeout=remaining)
            except queue.Empty:
                return None
            if line is None:
                return None                       # process died mid-answer
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []) or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        if block.get("name"):
                            tools.append(block["name"])
                continue

            if event.get("type") != "result":
                continue

            run = ClaudeRun(ok=False)
            apply_result_event(run, event)
            run.tools_used = tools
            run.exit_code = 0
            run.wall_ms = (time.perf_counter() - started) * 1000
            if not run.duration_ms:
                run.duration_ms = run.wall_ms
            return run

    # --------------------------------------------------------------- close --

    def close(self) -> None:
        with self._lock:
            self._closed = True
            idle, self._idle = self._idle, []
        for warm in idle:
            warm.kill()
