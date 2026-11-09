# -*- coding: utf-8 -*-
import os, sys
# general.run_file sets argv[0] to the script; __file__ may be stale in __main__
for _qceb_dir in [os.path.dirname(os.path.dirname(os.path.abspath(p)))
                  for p in (sys.argv[0] if sys.argv else "", globals().get("__file__", ""))]:
    if os.path.isdir(os.path.join(_qceb_dir, "quixel_ce_bridge")):
        break
if _qceb_dir not in sys.path:
    sys.path.insert(0, _qceb_dir)
from quixel_ce_bridge import controller, logger
ctrl = controller.get()
for key, value in ctrl.diagnostics().items():
    logger.info("%-14s %s" % (key, value))
logger.info("status: %s, pending: %d" % (ctrl.status, ctrl.pending))
