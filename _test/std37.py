# -*- coding: utf-8 -*-
import os
import sys

ENGINE = r"S:\Crytek\cryengine-57-lts\5.7.1"
HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
LOG = open(os.path.join(HERE, "std37_out.log"), "w")


def log(*args):
    LOG.write(" ".join(str(a) for a in args) + "\n")
    LOG.flush()


sys.path.insert(0, os.path.join(ENGINE, "Tools", "python", "packages", "common.zip"))
log("common.zip at sys.path[0]")

for mod in ["os", "sys", "time", "collections", "threading", "queue", "logging",
            "string", "keyword", "operator", "itertools", "heapq", "reprlib",
            "numbers", "abc", "copy", "types", "weakref", "functools"]:
    log("import", mod, "...")
    __import__(mod)
    log("  ok", mod)
log("ALL OK")
LOG.close()
