# -*- coding: utf-8 -*-
# Find which plugin import kills the embedded py37 with common.zip first.
import os
import sys

ENGINE = r"S:\Crytek\cryengine-57-lts\5.7.1"
HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
LOG = open(os.path.join(HERE, "bisect37_out.log"), "w")


def log(*args):
    LOG.write(" ".join(str(a) for a in args) + "\n")
    LOG.flush()


sys.path.insert(0, os.path.join(ENGINE, "Tools", "python", "packages", "common.zip"))
sys.path.insert(0, os.path.join(HERE, "..", "QuixelCEBridge"))
log("start", sys.path[:2])

MODS = [
    "logger", "settings", "paths", "external", "bridge_payload", "sandbox_api",
    "scene", "server", "mtl_writer", "fbxfix", "geometry_pipeline",
    "texture_pipeline", "importer", "controller", "quixel_ce_bridge",
]
for mod in MODS:
    log("importing", mod, "...")
    __import__("quixel_ce_bridge." + mod)
    log("  ok", mod)

for std in ["uuid", "zipfile", "subprocess", "shutil", "tempfile", "threading", "queue", "socket", "struct", "json", "logging", "re", "collections", "math", "time", "zlib", "traceback", "concurrent.futures"]:
    log("stdlib", std, "...")
    __import__(std)
    log("  ok", std)
log("ALL OK")
LOG.close()
