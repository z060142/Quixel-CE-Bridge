# Mock `sandbox` + real PySide2 (engine build) to exercise scene.py and ui.py on Python 3.7.
print("begin", flush=True)
import os, sys, types, time
HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
sys.path.insert(0, os.path.join(HERE, "..", "QuixelCEBridge"))
sys.path.insert(0, r"S:\Crytek\cryengine-57-lts\5.7.1\bin\win_x64")


calls = []
class Obj(object):
    def __init__(self, name): self.name = name
sb = types.ModuleType("sandbox")
sb.general = types.SimpleNamespace(
    get_game_folder=lambda: os.path.join(HERE, "gameproject", "Assets"),
    get_current_view_position=lambda: (100.0, 200.0, 30.0),
    get_current_view_rotation=lambda: (-10.0, 0.0, 90.0),
    create_object=lambda cls, f, n, x, y, z: (calls.append(("create", cls, f, n, round(x, 2), round(y, 2), round(z, 2))), Obj(n + "_1"))[1],
    message_box_ok=lambda t: None, log=lambda t: None)
sb.object = types.SimpleNamespace(set_custom_material=lambda n, m: calls.append(("mat", n, m)),
                                  get_all_objects=lambda c, l: [])
sb.selection = types.SimpleNamespace(get_object_names=lambda: [b"SelectedBox"], clear=lambda: None,
                                     select_objects=lambda names: calls.append(("select", names)))
sb.keybind = types.SimpleNamespace(add_custom_command=lambda *a: calls.append(("cmd",) + a))
sys.modules["sandbox"] = sb
bridge = types.ModuleType("SandboxBridge")
bridge.register_window = lambda cls, name, **kw: calls.append(("window", cls.__name__, name, kw))
sys.modules["SandboxBridge"] = bridge

from PySide2 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

# Run startup.py exactly like Sandbox does (shared __main__, argv[0] = path)
startup = os.path.join(HERE, "..", "QuixelCEBridge", "startup.py")
sys.argv = [startup]
exec(compile(open(startup, encoding="utf-8").read(), startup, "exec"), {"__name__": "__main__"})

from quixel_ce_bridge import controller, ui
ctrl = controller.get()
ctrl.settings.set("rc_exe", r"S:\Crytek\cryengine-57-lts\5.7.1\Tools\rc\rc.exe")
panel = ui.BridgePanel()
panel.show()
print("diag:", panel.diag.text().replace("\n", " | "))

ctrl.submit_file(os.path.join(HERE, "bridge_payload.json"))
deadline = time.time() + 600
while time.time() < deadline and (len(ctrl.history) < 3 or ctrl.pending):
    app.processEvents()
    time.sleep(0.05)
app.processEvents()
ctrl.stop_server()
for c in calls:
    print("CALL", c)
print("log lines in panel:", panel.log.blockCount())
