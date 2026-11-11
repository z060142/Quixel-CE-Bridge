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


_UUID = re.compile(r"[0-9a-f]{8}(_[0-9a-f]{4}){3}_[0-9a-f]{12}")

# The asset name appears twice in every output path (<folder>/<name>_<map>.dds.cryasset), and
# Sandbox.exe is not long-path aware (MAX_PATH 260), so the name must stay short.
MAX_BASE_NAME = 64


def is_uuid(text):
    return bool(_UUID.fullmatch(safe_name(text or "", "")))


def asset_base_name(name, asset_id, limit=MAX_BASE_NAME):
    """Folder / file stem of an imported asset, at most `limit` chars.

    Megascans names look like 'Mossy Rock wlpmfhhaw': the last word is dropped
    and the short id appended ('mossy_rock_wlpmfhhaw'). Fab assets carry a
    UUID id: it never goes into the name (too long, MAX_PATH), and the last
    word is kept because it is a variant number ('... Hard 01' / '... Hard 02').
    The original id and name are stored in the .cryasset files (see importer).
    """
    token = (name or "").strip().replace(" ", "_")
    if is_uuid(asset_id):
        stem = safe_name(token, "") if not is_uuid(token) else ""
        return safe_name(stem[:limit], "asset_" + safe_name(asset_id)[:8])
    if len(token.split("_")) > 2:
        token = "_".join(token.split("_")[:-1])
    ident = safe_name(asset_id)
    room = max(limit - len(ident) - 1, 8)
    return safe_name("%s_%s" % (safe_name(token)[:room], ident))


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
