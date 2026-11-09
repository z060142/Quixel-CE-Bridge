# -*- coding: utf-8 -*-
"""Path helpers: tool discovery, safe asset names, game-relative paths."""
import os
import re
import sys

from .settings import PLUGIN_DIR


def norm(path):
    return os.path.normpath(os.path.abspath(path)) if path else path


def engine_root_candidates():
    """Possible engine roots (folder containing Tools/rc/rc.exe)."""
    candidates = []
    exe = getattr(sys, "executable", "") or ""
    if exe:
        # <engine>/bin/win_x64/Sandbox.exe
        candidates.append(os.path.dirname(os.path.dirname(os.path.dirname(exe))))
    # <engine>/Editor/Python/plugins/QuixelCEBridge
    candidates.append(os.path.abspath(os.path.join(PLUGIN_DIR, "..", "..", "..", "..")))
    for env in ("CRYENGINE_ROOT", "CE_ENGINE_ROOT"):
        if os.environ.get(env):
            candidates.append(os.environ[env])
    seen, result = set(), []
    for item in candidates:
        key = os.path.normcase(os.path.abspath(item))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def find_rc(configured=""):
    if configured and os.path.isfile(configured):
        return norm(configured)
    if os.environ.get("CE_RC_EXE") and os.path.isfile(os.environ["CE_RC_EXE"]):
        return norm(os.environ["CE_RC_EXE"])
    for root in engine_root_candidates():
        candidate = os.path.join(root, "Tools", "rc", "rc.exe")
        if os.path.isfile(candidate):
            return norm(candidate)
    return None


def find_bundled(configured, exe_name):
    if configured and os.path.isfile(configured):
        return norm(configured)
    candidate = os.path.join(PLUGIN_DIR, "bin", exe_name)
    return norm(candidate) if os.path.isfile(candidate) else None


_SAFE = re.compile(r"[^a-z0-9_]+")


def safe_name(text, fallback="asset"):
    """CRYENGINE-friendly lowercase identifier (ASCII, no spaces)."""
    text = (text or "").strip().lower()
    text = _SAFE.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def game_relative(path, assets_root):
    """Absolute path -> lowercase game path with forward slashes."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(assets_root))
    if rel.startswith(".."):
        raise ValueError("%s is outside the assets root %s" % (path, assets_root))
    return rel.replace("\\", "/").lower()


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)
    return path
