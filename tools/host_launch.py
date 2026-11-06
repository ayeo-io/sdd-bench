#!/usr/bin/env python3
# =============================================================================
# compass - start one `claude -p` session
# =============================================================================
# The one place Compass starts a model session (ADR-030). The eval harness
# (`evals/harness.py`) calls it for every session it drives. 9.0.0 removed
# `compass run`, its other caller (ADR-090).
#
# It starts the process and returns what came back. It reads no credential
# and adds none: the caller's environment is passed on as it is.
#
# DEPENDENCY: standard library (json, os, selectors, signal, subprocess, sys,
# threading, time).
# =============================================================================
"""Start one `claude -p` call and read the result event it prints."""
from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, NamedTuple


class Launch(NamedTuple):
    """What one call returned. `timed_out` is True when the call ran past
    its timeout and was ended; `returncode` is then -1. `held` is True when
    a process the call started was still holding its output after it
    exited, and was ended (only for a call run as another user)."""
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    held: bool = False


class SessionCall(NamedTuple):
    """What `run_session_user_call` returns: the same fields as
    `subprocess.CompletedProcess` that callers read, and `held`."""
    returncode: int
    stdout: str | bytes
    stderr: str | bytes
    held: bool


def session_user_args(uid, gid):
    """The `subprocess` arguments that start a process as an unprivileged
    session user. The one place they are built, so the session, git and the
    test command, and the kill-all cannot drift apart. A new session and no
    standard input: a process that kept the caller's controlling terminal
    could push a line into it (`TIOCSTI`) for the caller's shell to run.
    Supplementary groups are cleared only when this process can clear them,
    which needs root."""
    args = {"user": uid, "group": gid, "start_new_session": True,
            "stdin": subprocess.DEVNULL}
    if os.geteuid() == 0:
        args["extra_groups"] = []
    return args


def run_session_user_call(command, *, end_processes: Callable[[], None],
                          grace: float = 5.0, text: bool = True, **kwargs):
    """Run `command` and capture its output without waiting on a process
    it left behind.

    `subprocess.run` with captured output returns only when every holder
    of the output pipe has closed it, so a process a session started that
    keeps the pipe open would hold the caller as long as it lives. Here the
    output is read on two threads while the call runs (so a large output
    never blocks the child), the call itself is waited for, and the readers
    get `grace` seconds to reach the end. If they have not, something still
    holds the pipe: `end_processes` is called - the caller's kill-all - and
    the call is reported as `held`.

    The pipes are read as bytes and decoded once at the end, with bad
    bytes replaced: decoding while reading would let one byte that is not
    UTF-8 stop the reader, and a child writing more than a pipe holds would
    then block for good. Text gets the newlines `subprocess.run(text=True)`
    gives. An interrupt ends the call and the user's processes before it
    is raised, as `subprocess.run` ends its child."""
    proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **kwargs)
    chunks: dict[str, list[bytes]] = {"out": [], "err": []}
    stop = threading.Event()

    def pump(stream, key):
        # Each wait lasts at most 0.2 seconds, so the reader can be told to
        # stop: a process the kill-all could not end may hold the pipe for
        # good, and a reader blocked in `read` would then never finish. A
        # selector, not `select.select`, which cannot watch a descriptor
        # numbered 1024 or higher and would lose the output without a word.
        fd = stream.fileno()
        with selectors.DefaultSelector() as waiting:
            waiting.register(fd, selectors.EVENT_READ)
            while not stop.is_set():
                if not waiting.select(0.2):
                    continue
                piece = os.read(fd, 65536)
                if not piece:
                    return
                chunks[key].append(piece)

    readers = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
    try:
        for reader in readers:
            reader.start()
        proc.wait()
        deadline = time.monotonic() + grace
        for reader in readers:
            reader.join(max(0.0, deadline - time.monotonic()))
        held = any(reader.is_alive() for reader in readers)
        if held:
            end_processes()
            for reader in readers:
                reader.join(grace)
    except BaseException:
        proc.kill()
        end_processes()
        proc.wait()
        raise
    finally:
        # Stopped and closed whether or not the kill-all worked, so a held
        # call leaves no thread reading and no pipe open behind it.
        stop.set()
        for reader in readers:
            if reader.ident is not None:  # an interrupt can land before a start
                reader.join()
        for stream in (proc.stdout, proc.stderr):
            stream.close()
    out, err = b"".join(chunks["out"]), b"".join(chunks["err"])
    if text:
        # The same newlines `subprocess.run(text=True)` gives, so a root
        # run's diff and test output read as a non-root run's do.
        out = out.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
        err = err.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    return SessionCall(proc.returncode, out, err, held)


def launch_claude(claude_exe, message, args, cwd, env, timeout=None, user=None,
                  end_processes=None):
    """Run `claude -p <message> <args...>` in `cwd` with `env`, with no
    standard input, and return a `Launch`.

    With a `timeout`, the session starts in its own process group, and a
    call past `timeout` seconds has the whole group ended - the session and
    anything it started - and is reported as timed out, not raised. Ending
    only `claude` would leave a command it started running after the run
    has stopped. Without a timeout the call waits, as the eval harness's
    sessions, bounded by their budget, always have.

    With a `user`, a `(uid, gid)` pair, the session starts as that user and
    group (`session_user_args`): the eval harness run as root uses it to
    keep each session unprivileged. Its output is then read by
    `run_session_user_call`, so a process the session left holding the
    output cannot hold the harness; `end_processes` is what ends it."""
    command = [claude_exe, "-p", message, *args]
    as_user = {}
    if user is not None:
        # The timed path adds its own new session and input below.
        as_user = {key: value for key, value in session_user_args(*user).items()
                   if key not in ("start_new_session", "stdin")}
    if timeout is None and user is not None:
        call = run_session_user_call(
            command, end_processes=end_processes or (lambda: None),
            cwd=str(cwd), env=env, **session_user_args(*user))
        return Launch(call.returncode, call.stdout or "", call.stderr or "",
                      False, call.held)
    if timeout is None:
        proc = subprocess.run(command, cwd=str(cwd), env=env,
                              capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
        return Launch(proc.returncode, proc.stdout or "", proc.stderr or "",
                      False)
    # An interrupt that lands while the session is being created would
    # raise before `proc` is known, and the session would keep running in
    # its own group. Hold the interrupt signals until `proc` is set, then
    # replay them inside the `try` below, where the session is ended.
    hold = _InterruptHold()
    proc = None
    try:
        proc = subprocess.Popen(command, cwd=str(cwd), env=env, text=True,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True,
                                preexec_fn=hold.release_in_child,
                                **as_user)
        hold.release()
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _end_group(proc)
        stdout, stderr = proc.communicate()
        return Launch(-1, stdout or "", stderr or "", True)
    except BaseException:
        # Interrupted (Ctrl-C, a cancelled CI job): the session has its own
        # group, so the signal did not reach it. End it before going on.
        if proc is not None:
            _end_group(proc)
            proc.wait()
        if isinstance(sys.exc_info()[1], _DefaultAction):
            signal.raise_signal(sys.exc_info()[1].signum)
        raise
    finally:
        hold.restore()
    return Launch(proc.returncode, stdout or "", stderr or "", False)


class _InterruptHold:
    """Holds SIGINT and SIGTERM while the session is created, then replays
    what arrived.

    In the main thread it replaces the Python handlers with a recorder.
    That holds whichever thread the system hands the signal to: a signal
    mask covers only the thread that set it, and Python raises a handler's
    exception in the main thread whichever thread took the signal. Outside
    the main thread Python cannot change a handler, so it blocks the
    signals in this thread only, which does not cover other threads."""

    SIGNALS = ("SIGINT", "SIGTERM")

    def __init__(self):
        self.recorded = []
        self.previous = {}
        self.mask = None
        self.active = True
        names = [getattr(signal, name) for name in self.SIGNALS]
        if threading.current_thread() is threading.main_thread():
            for signum in names:
                self.previous[signum] = signal.signal(signum, self._record)
        elif hasattr(signal, "pthread_sigmask"):
            self.mask = signal.pthread_sigmask(signal.SIG_BLOCK, set(names))

    def _record(self, signum, frame):
        self.recorded.append(signum)

    def release_in_child(self):
        """Runs in the session process before it starts, so it does not
        inherit the block."""
        if self.mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, self.mask)

    def restore(self):
        """Put back the handlers and the mask. Safe to call twice."""
        if not self.active:
            return
        self.active = False
        for signum, handler in self.previous.items():
            signal.signal(signum, handler)
        self.release_in_child()

    def release(self):
        """Restore, then act on a signal that arrived during the hold as
        its earlier handler would have: raise from a Python handler, end
        the process for the default action, ignore it when it was ignored.
        The caller's `except` ends the session on a raise."""
        self.restore()
        while self.recorded:
            signum = self.recorded.pop(0)
            handler = self.previous.get(signum)
            if callable(handler):
                handler(signum, None)
            elif handler == signal.SIG_DFL:
                raise _DefaultAction(signum)


class _DefaultAction(BaseException):
    """A held signal whose handler was the default action. The launcher
    ends the session, then runs the action again with `signal.raise_signal`."""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def _end_group(proc):
    """End the session's process group: the session and what it started."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def session_summary(stdout):
    """The last `result` event's session id, cost, error flag and final
    text, read from
    the line-delimited JSON output, or empty values when it holds none."""
    summary = {"session_id": None, "cost_usd": None, "is_error": None,
               "result": None}
    for line in (stdout or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            summary = {"session_id": event.get("session_id"),
                       "cost_usd": event.get("total_cost_usd"),
                       "is_error": event.get("is_error"),
                       "result": event.get("result")}
    return summary
