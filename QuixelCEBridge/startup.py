# -*- coding: utf-8 -*-
"""QuixelCEBridge - CRYENGINE 5.7 Sandbox plugin entry point.

Install: copy this folder to <engine>/Editor/Python/plugins/QuixelCEBridge/
Sandbox runs this file with PyRun_SimpleFile in the shared __main__ namespace,
so everything lives inside a function and only one private name is left behind.
"""


def _quixel_ce_bridge_startup():
    import os
    import sys
    import traceback

    # Sandbox runs this via "general.run_file", which sets argv[0]; __file__ in
    # the shared __main__ namespace may belong to another script.
    here = None
    for candidate in (sys.argv[0] if sys.argv else "", globals().get("__file__", "")):
        folder = os.path.dirname(os.path.abspath(candidate)) if candidate else ""
        if folder and os.path.isdir(os.path.join(folder, "quixel_ce_bridge")):
            here = folder
            break
    if here is None:
        sys.stderr.write("[QuixelCEBridge] cannot locate plugin folder\n")
        return
    if here not in sys.path:
        sys.path.insert(0, here)

    try:
        from quixel_ce_bridge import PLUGIN_NAME, VERSION, logger, controller
        logger.set_log_file(os.path.join(here, "quixel_ce_bridge.log"))
        logger.info("%s %s loading from %s" % (PLUGIN_NAME, VERSION, here))

        ctrl = controller.get()
        ctrl.start_pump()

        try:
            import sandbox
            from quixel_ce_bridge.sandbox_api import group
            keybind = group("keybind")
            if keybind is None:
                logger.warning("sandbox.keybind is unavailable")
            else:
                scripts = os.path.join(here, "scripts")
                for ui_name, script in (
                    ("QuixelCEBridge: Start Listening", "start_listening.py"),
                    ("QuixelCEBridge: Stop Listening", "stop_listening.py"),
                    ("QuixelCEBridge: Import Bridge JSON", "import_json.py"),
                    ("QuixelCEBridge: Process Pending", "process_pending.py"),
                    ("QuixelCEBridge: Status", "status.py"),
                ):
                    path = os.path.join(scripts, script).replace("\\", "/")
                    keybind.add_custom_command(ui_name, "general.run_file '%s'" % path, "")
        except Exception as error:  # noqa
            logger.warning("custom commands not registered: %s" % error)

        try:
            from quixel_ce_bridge import ui
            ui.register()
        except Exception as error:  # noqa
            logger.warning("UI panel unavailable (%s); use the custom commands instead" % error)

        if ctrl.settings.get("auto_start", True):
            ctrl.start_server()
        for key, value in ctrl.diagnostics().items():
            logger.info("  %-14s %s" % (key, value))

        # Log which sandbox command groups this build actually exposes.
        from quixel_ce_bridge.sandbox_api import group
        groups = [n for n in ("general", "object", "selection", "keybind", "material")
                  if group(n) is not None]
        logger.info("sandbox groups: %s" % (", ".join(groups) or "none"))
    except Exception:  # noqa
        sys.stderr.write("[QuixelCEBridge] start-up failed:\n" + traceback.format_exc())


_quixel_ce_bridge_startup()
