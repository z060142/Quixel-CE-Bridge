# -*- coding: utf-8 -*-
# Distinguish raise vs hard-crash when common.zip shadows reprlib on py37.
import os
import sys

ENGINE = r"S:\Crytek\cryengine-57-lts\5.7.1"
HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
LOG = open(os.path.join(HERE, "std37b_out.log"), "w")


def log(*args):
    LOG.write(" ".join(str(a) for a in args) + "\n")
    LOG.flush()


COMMON = os.path.join(ENGINE, "Tools", "python", "packages", "common.zip")
sys.path.insert(0, COMMON)
log("step1: common.zip inserted at [0]")

try:
    import collections  # noqa
    log("collections imported fine?!", collections.__file__)
except BaseException:
    import traceback
    log("collections RAISED:")
    log(traceback.format_exc())
    log("step2: drop common.zip from sys.path and retry")
    sys.path.remove(COMMON)
    import collections  # noqa
    log("retry without common.zip: OK ->", collections.__file__)
log("done")
LOG.close()
