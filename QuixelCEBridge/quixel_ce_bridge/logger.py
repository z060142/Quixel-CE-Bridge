# -*- coding: utf-8 -*-
"""Thread-safe logging.

the editor API may only be called from the main thread, so worker
threads write to sys.stdout / sys.stderr (Sandbox redirects both into the
Console) and into an in-memory ring buffer the UI panel polls.
"""
import collections
import os
import sys
import threading
import time

PREFIX = "[QuixelCEBridge] "
_lock = threading.Lock()
_buffer = collections.deque(maxlen=2000)
_sequence = [0]
_log_file = None


def set_log_file(path):
    global _log_file
    _log_file = path
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 2 * 1024 * 1024:
            os.remove(path)
    except OSError:
        pass


def _emit(level, message):
    line = "%s%s%s" % (PREFIX, "" if level == "INFO" else level + ": ", message)
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        _sequence[0] += 1
        _buffer.append((_sequence[0], level, "%s %s" % (stamp, line)))
        stream = sys.stdout if level == "INFO" else sys.stderr
        try:
            stream.write(line + "\n")
            stream.flush()
        except Exception:
            pass
        if _log_file:
            try:
                with open(_log_file, "a", encoding="utf-8") as handle:
                    handle.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
            except Exception:
                pass


def info(message):
    _emit("INFO", message)


def warning(message):
    _emit("WARNING", message)


def error(message):
    _emit("ERROR", message)


def lines_since(sequence):
    """Return [(seq, level, text)] newer than `sequence`."""
    with _lock:
        return [entry for entry in _buffer if entry[0] > sequence]
