# -*- coding: utf-8 -*-
# Faithful reproduction of the user's environment on embedded py37:
# a python-future style 'http' guard shadows the stdlib (their Launcher
# python37.zip lacks http/, so common.zip's guard wins). The plugin must
# import cleanly despite that. Run via _test/embed37.py.
import os
import sys

HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
LOG = open(os.path.join(HERE, "sim37b_out.log"), "w")


def log(*args):
    LOG.write(" ".join(str(a) for a in args) + "\n")
    LOG.flush()


SIM_ZIP = os.path.join(os.environ.get("TEMP", r"C:\Users\Bigspring\AppData\Local\Temp"),
                       "qceb_future_sim", "mini_future.zip")
sys.path.insert(0, SIM_ZIP)          # shadow stdlib 'http' like the user's common.zip does
sys.path.insert(0, os.path.join(HERE, "..", "QuixelCEBridge"))
log("sim zip on path:", SIM_ZIP in sys.path, "| plugin dir:", sys.path[0])

# 1) the exact failure the user hit, with the old import chain
try:
    from xml.sax.saxutils import quoteattr  # noqa
    log("UNEXPECTED: saxutils survived")
except ImportError as error:
    log("user failure reproduced:", str(error)[:70])

# 2) the plugin must import everything cleanly now
import quixel_ce_bridge  # noqa
from quixel_ce_bridge import (  # noqa
    bridge_payload, controller, external, fbxfix, geometry_pipeline, importer,
    logger, mtl_writer, paths, sandbox_api, scene, settings, texture_pipeline,
)
log("all plugin modules imported OK")

# 3) exercise mtl writing end to end inside this environment
from quixel_ce_bridge.mtl_writer import MaterialDef, write_mtl  # noqa

mat = MaterialDef("weird & <name> \"quoted\"",
                  {"diffuse": "./sofa_diff.dds", "normal": "./sofa_ddna.dds"},
                  shader="Illum")
log("MaterialDef built, name:", mat.name)
out = os.path.join(os.environ.get("TEMP", r"C:\Users\Bigspring\AppData\Local\Temp"),
                   "qceb_future_sim", "sim_test.mtl")
write_mtl(out, [mat], force_multi=True)
log("mtl written:", os.path.getsize(out), "bytes")
with open(out) as handle:
    head = [next(handle) for _ in range(3)]
log("mtl line1:", head[0].strip()[:100])
log("mtl line2:", head[1].strip()[:100])
log("mtl line3:", head[2].strip()[:130])
import xml.etree.ElementTree as ET  # noqa
ET.parse(out)
ET.parse(out + ".cryasset")
log("mtl + cryasset parse as valid XML")
log("ALL OK")
LOG.close()
