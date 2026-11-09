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
# Import a Bridge export JSON (e.g. from "Custom Disk Export") or a Quixel
# .zip download (as shipped by bridge: flat fbx + maps + <id>.json) without
# the socket.
import sandbox
path = sandbox.general.open_file_box()
if isinstance(path, bytes):
    path = path.decode("utf-8")
if path:
    ctrl.submit_file(path)
