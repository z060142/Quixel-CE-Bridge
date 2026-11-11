# -*- coding: utf-8 -*-
"""QuixelCEBridge - CRYENGINE 5.7 Sandbox plugin entry point (CrythonNative).

Install: put this folder under a CrythonNative plugin directory, i.e. one of
  <engine>/Editor/Python/crython_plugins/QuixelCEBridge/
  <project>/Editor/Python/crython_plugins/QuixelCEBridge/
  or any folder listed in the CRYTHON_PLUGIN_PATH environment variable (';' separated;
  point it at the folder that CONTAINS QuixelCEBridge).
CrythonNative runs this file in its own namespace with a correct __file__.
"""
import os
import sys
import traceback

import CrythonNative as cn

here = os.path.dirname(os.path.abspath(__file__))
if here not in sys.path:
    sys.path.insert(0, here)


def _pick_and_import(ctrl):
    """Import a Bridge export JSON or a Quixel .zip download without the socket."""
    from PySide2.QtWidgets import QFileDialog
    path, _filter = QFileDialog.getOpenFileName(
        None, "QuixelCEBridge: Import Bridge JSON / Quixel zip", "",
        "Bridge export (*.json *.zip);;All files (*)")
    if path:
        ctrl.submit_file(path)


def _status(ctrl, logger):
    for key, value in ctrl.diagnostics().items():
        logger.info("%-14s %s" % (key, value))
    logger.info("status: %s, pending: %d" % (ctrl.status, ctrl.pending))


def _pending(ctrl, logger):
    ctrl.pump()   # finish queued imports now
    logger.info("pending jobs: %d" % ctrl.pending)


def _startup():
    from quixel_ce_bridge import PLUGIN_NAME, VERSION, logger, controller
    logger.set_log_file(os.path.join(here, "quixel_ce_bridge.log"))
    logger.info("%s %s loading from %s" % (PLUGIN_NAME, VERSION, here))

    ctrl = controller.get()
    ctrl.start_pump()

    # Editor commands: Tools > Custom Commands, bindable to shortcuts as crython.<id>
    for command_id, label, fn in (
        ("quixel_start", "QuixelCEBridge: Start Listening", ctrl.start_server),
        ("quixel_stop", "QuixelCEBridge: Stop Listening", ctrl.stop_server),
        ("quixel_import_json", "QuixelCEBridge: Import Bridge JSON", lambda: _pick_and_import(ctrl)),
        ("quixel_process_pending", "QuixelCEBridge: Process Pending", lambda: _pending(ctrl, logger)),
        ("quixel_status", "QuixelCEBridge: Status", lambda: _status(ctrl, logger)),
    ):
        try:
            cn.editor.register_command(command_id, fn, label=label)
        except Exception as error:  # noqa
            logger.warning("command %s not registered: %s" % (command_id, error))

    try:
        from quixel_ce_bridge import ui
        ui.register()
    except Exception as error:  # noqa
        logger.warning("UI panel unavailable (%s); use the custom commands instead" % error)

    if ctrl.settings.get("auto_start", True):
        ctrl.start_server()
    for key, value in ctrl.diagnostics().items():
        logger.info("  %-14s %s" % (key, value))


try:
    _startup()
except Exception:  # noqa
    sys.stderr.write("[QuixelCEBridge] start-up failed:\n" + traceback.format_exc())
