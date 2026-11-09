# Offline end-to-end test (no Sandbox): socket -> worker -> texproc/converter/rc.
import json, os, socket, sys, time
HERE = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else __file__))
sys.path.insert(0, os.path.join(HERE, "..", "QuixelCEBridge"))
print("python", sys.version)

from quixel_ce_bridge import controller, logger, scene
ctrl = controller.get()
ctrl.settings.set("assets_root", os.path.join(HERE, "gameproject", "Assets"))
ctrl.settings.set("rc_exe", r"S:\Crytek\cryengine-57-lts\5.7.1\Tools\rc\rc.exe")
ctrl.settings.set("port", 24999)
ctrl.settings.set("keep_work_files", True)
ctrl.settings.set("material.plant_shader", "Vegetation")
assert ctrl.start_server()

payload = open(os.path.join(HERE, "bridge_payload.json"), "rb").read()
s = socket.create_connection(("localhost", 24999))
s.sendall(payload)
s.close()

deadline = time.time() + 900
seen = 0
while time.time() < deadline:
    ctrl.pump()
    if len(ctrl.history) >= 3 and ctrl.pending == 0:
        break
    time.sleep(0.25)
ctrl.stop_server()
for r in ctrl.history:
    print("RESULT", r.asset.display_name, "ok=%s" % r.ok, r.material_game_path, r.objects, r.errors, r.warnings)
