# Full offline e2e with the REAL Bridge raw export (sofa ybmjefm).
import os, sys, time
HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
sys.path.insert(0, os.path.join(HERE, "..", "QuixelCEBridge"))
from quixel_ce_bridge import controller, logger
ctrl = controller.get()
ctrl.settings.set("assets_root", os.path.join(HERE, "gameproject", "Assets"))
ctrl.settings.set("rc_exe", r"S:\Crytek\cryengine-57-lts\5.7.1\Tools\rc\rc.exe")
ctrl.settings.set("texture.output_resolution", "2048")   # 8K -> 2K for a quick test run
ctrl.settings.set("port", 24998)
ctrl.start_pump()
n = ctrl.submit_file(r"E:\Modeling\interior_classic_sofa_chaise_velvet_red_ornate_ybmjefm_raw\ybmjefm.json")
deadline = time.time() + 1800
while time.time() < deadline:
    ctrl.pump()
    if len(ctrl.history) >= 1 and ctrl.pending == 0:
        break
    time.sleep(0.25)
for r in ctrl.history:
    print("RESULT ok=%s" % r.ok, r.material_game_path, [n for _, n in r.objects], "err:", r.errors, "warn:", r.warnings)
