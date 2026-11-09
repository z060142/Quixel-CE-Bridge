# -*- coding: utf-8 -*-
# Simulate the failing user environment on the engine's embedded CPython 3.7:
# Tools/python/packages/common.zip (python-future py2 shims) at sys.path[0],
# then import every plugin module. Run via _test/embed37.py.
import os
import sys

ENGINE = r"S:\Crytek\cryengine-57-lts\5.7.1"
PLUGIN = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "QuixelCEBridge")
LOG = open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "sim37_out.log"), "w")


def print(*args):
    LOG.write(" ".join(str(a) for a in args) + "\n")
    LOG.flush()


COMMON_ZIP = os.path.join(ENGINE, "Tools", "python", "packages", "common.zip")
sys.path.insert(0, COMMON_ZIP)
sys.path.insert(0, os.path.abspath(PLUGIN))
print("sys.path[:3]:", sys.path[:3])

# 1) prove the old import chain breaks exactly like on the user's machine
try:
    from xml.sax.saxutils import quoteattr  # noqa
    print("UNEXPECTED: saxutils import survived")
except ImportError as error:
    print("reproduced user failure:", str(error)[:80])

# 2) the plugin package must import cleanly now (all modules)
import quixel_ce_bridge  # noqa
from quixel_ce_bridge import (  # noqa
    bridge_payload, controller, external, fbxfix, geometry_pipeline, importer,
    logger, mtl_writer, paths, sandbox_api, scene, settings, texture_pipeline,
)

# 3) ui only if PySide2 is importable in this environment
try:
    from quixel_ce_bridge import ui  # noqa
    print("ui imports OK (PySide2 present)")
except ImportError as error:
    print("ui skipped (no PySide2 outside Sandbox):", str(error)[:60])

# 4) stdlib building blocks the plugin relies on, still fine with common.zip first
import shutil, subprocess, tempfile, threading, uuid, zipfile  # noqa
print("all plugin modules imported OK on embedded py37 + common.zip first")

# 5) sanity: quoteattr/escape output
from quixel_ce_bridge.mtl_writer import quoteattr, escape  # noqa
print("quoteattr:", quoteattr('a"b<c>&d\ne'))
print("escape:", escape("<&>"))
LOG.close()
