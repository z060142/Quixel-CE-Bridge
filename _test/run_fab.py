# -*- coding: utf-8 -*-
"""Fab live-link end-to-end test (no Sandbox): socket ping + Fab payloads ->
worker -> texproc/converter/rc.exe -> CGF / MTL / DDS, plus sub-material and
normal-flip checks.  Run:  python _test/embed37.py _test/run_fab.py
"""
import glob
import json
import os
import shutil
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else __file__))
sys.path.insert(0, os.path.join(HERE, "..", "QuixelCEBridge"))
print("python", sys.version)

from quixel_ce_bridge import controller, logger
import quixel_ce_bridge

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition), detail))
    print(("PASS  " if condition else "FAIL  ") + name + (" " + str(detail) if not condition else ""))


def fab_rock(asset_id):
    base = os.path.join(HERE, "megascans", "3d_rock_abc123")
    return {
        "id": asset_id, "path": "megascans/" + asset_id,
        "meshes": [{"file": os.path.join(base, "abc123_LOD0.fbx"), "name": "rock",
                    "material_index": -1,
                    "lods": [{"file": os.path.join(base, "abc123_LOD1.fbx")}]}],
        "materials": [{"name": "mossy", "textures": {
            "albedo": os.path.join(base, "abc123_2K_Albedo.jpg"),
            "normal": os.path.join(base, "abc123_2K_Normal.jpg"),
            "occlusion": os.path.join(base, "abc123_2K_AO.jpg"),
            "roughness": os.path.join(base, "abc123_2K_Roughness.jpg"),
            "displacement": os.path.join(base, "abc123_2K_Displacement.jpg"),
        }, "flipnmapgreenchannel": True}],
        "native_files": [], "additional_textures": [],
        "metadata": {
            "launcher": {"version": "2.0.0", "listening_port": 24563},
            "fab": {"listing": {"listingType": "3d-model", "title": "Mossy Rock",
                                "category": {"slug": "3d-assets--rock"}},
                    "format": "FBX", "isQuixel": True, "quality": "mid"},
            "megascans": {"name": "Mossy Rock Fab", "categories": ["3d"], "tags": ["rock"],
                          "activeLOD": "lod0", "workflow": "Specular",
                          "semanticTags": {"asset_type": "3d asset"}},
        },
    }


def fab_surface():
    base = os.path.join(HERE, "megascans", "surface_xyz")
    return {
        "id": "fabsurf", "path": "megascans/fabsurf", "meshes": [],
        "materials": [{"name": "dirt", "textures": {
            "albedo": os.path.join(base, "xyz_2K_Albedo.jpg"),
            "normal": os.path.join(base, "xyz_2K_Normal.jpg"),
            "metal": os.path.join(base, "xyz_2K_Metalness.jpg"),
            "roughness": os.path.join(base, "xyz_2K_Roughness.jpg"),
            "displacement": os.path.join(base, "xyz_2K_Displacement.jpg"),
            "occlusion": os.path.join(base, "xyz_2K_AO.jpg"),
        }, "flipnmapgreenchannel": True}],
        "native_files": [], "additional_textures": [],
        "metadata": {"launcher": {"listening_port": 24563},
                     "fab": {"listing": {"listingType": "material",
                                         "category": {"slug": "surface"}},
                             "isQuixel": True},
                     "megascans": {"name": "Dirt Surface", "categories": ["surface"],
                                   "workflow": "Metalness"}},
    }


def fab_multimat():
    base = os.path.join(HERE, "megascans", "3d_rock_abc123")
    granite = {"name": "granite", "textures": {
        "albedo": os.path.join(base, "abc123_2K_Displacement.jpg"),
        "normal": os.path.join(base, "abc123_2K_Normal.jpg"),
    }, "flipnmapgreenchannel": False}
    payload = fab_rock("fabmulti")
    payload["meshes"] = [
        {"file": os.path.join(base, "abc123_LOD0.fbx"), "material_index": 0, "lods": []},
        {"file": os.path.join(base, "abc123_LOD1.fbx"), "material_index": 1, "lods": []},
    ]
    payload["materials"] = [payload["materials"][0], granite]
    return payload


def send(port, payload):
    client = socket.create_connection(("127.0.0.1", port), timeout=10)
    client.sendall(b"ping")
    reply = client.recv(200)
    check("ping reply (plugin version)", reply == ("{'plugin_version': '%s'}" % quixel_ce_bridge.VERSION).encode(), reply)
    client.sendall(json.dumps(payload).encode("utf-8"))
    client.close()


def main():
    ctrl = controller.get()
    ctrl.settings.set("assets_root", os.path.join(HERE, "gameproject", "Assets"))
    ctrl.settings.set("rc_exe", r"S:\Crytek\cryengine-57-lts\5.7.1\Tools\rc\rc.exe")
    ctrl.settings.set("port", 24998)
    ctrl.settings.set("fab_port", 24996)
    ctrl.settings.set("keep_work_files", True)
    # default stage_dir "user" -> work folders inside gameproject/user/QuixelCEBridge
    base = os.path.join(HERE, "gameproject", "user", "QuixelCEBridge")
    for old in glob.glob(os.path.join(base, "qceb_*")):
        shutil.rmtree(old, ignore_errors=True)
    assert ctrl.start_server()
    port = 24996   # Fab's "Custom (Socket Port)" target — the launcher sends here

    send(port, fab_rock("fabrock"))
    send(port, fab_surface())
    send(port, fab_multimat())

    deadline = time.time() + 900
    while time.time() < deadline:
        ctrl.pump()
        if len(ctrl.history) >= 3 and ctrl.pending == 0:
            break
        time.sleep(0.25)
    ctrl.stop_server()

    print()
    for r in ctrl.history:
        print("RESULT", r.asset.display_name, "ok=%s" % r.ok, r.material_game_path,
              len(r.objects), "objects", r.errors, r.warnings)

    results = {r.asset.id: r for r in ctrl.history}
    root = os.path.join(HERE, "gameproject", "Assets", "Objects", "Megascans")
    base = os.path.join(HERE, "gameproject", "user", "QuixelCEBridge")   # default stage_dir "user"

    # --- staging: intermediates stay in the kept work dir, finals in the project
    def staging(name):
        for d in sorted(glob.glob(os.path.join(base, "qceb_%s_*" % name, "stage"))):
            return d
        return ""
    stage_dirs = {name: staging(name) for name in ("fabrock", "fabsurf", "fabmulti")}

    def leftovers(folder):
        return [n for n in os.listdir(folder) if n.lower().endswith((".tif", ".json"))
                or n.endswith(".qcebtmp")]

    # --- rock
    r = results.get("fabrock")
    check("rock imported", r is not None and r.ok)
    if r:
        folder = os.path.join(root, "3d", r.asset.safe_base)
        check("rock cgf", os.path.getsize(os.path.join(folder, r.asset.safe_base + ".cgf")) > 10240)
        check("rock lod1 cgf", os.path.getsize(os.path.join(folder, r.asset.safe_base + "_lod1.cgf")) > 1024)
        check("rock dds diff", os.path.isfile(os.path.join(folder, r.asset.safe_base + "_diff.dds")))
        check("rock dds ddna", os.path.isfile(os.path.join(folder, r.asset.safe_base + "_ddna.dds")))
        check("rock dds spec", os.path.isfile(os.path.join(folder, r.asset.safe_base + "_spec.dds")))
        check("rock displ dropped for 3d",
              not os.path.isfile(os.path.join(folder, r.asset.safe_base + "_displ.dds")))
        mtl = open(os.path.join(folder, r.asset.safe_base + ".mtl"), encoding="utf-8").read()
        check("rock mtl multi", "<SubMaterials>" in mtl)
        check("rock staged: no tif/json in project", not leftovers(folder), leftovers(folder))
        check("rock staged: cryassets moved",
              os.path.isfile(os.path.join(folder, r.asset.safe_base + ".mtl.cryasset")) and
              os.path.isfile(os.path.join(folder, r.asset.safe_base + ".cgf.cryasset")) and
              os.path.isfile(os.path.join(folder, r.asset.safe_base + "_diff.dds.cryasset")))
        check("rock staged: intermediates kept in work dir",
              stage_dirs["fabrock"] != "" and
              os.path.isfile(os.path.join(stage_dirs["fabrock"], r.asset.safe_base + "_diff.tif")) and
              os.path.isfile(os.path.join(stage_dirs["fabrock"], r.asset.safe_base + ".json")))
        # normal flip honored: find the kept texproc settings json
        flips = []
        for settings_path in glob.glob(os.path.join(base, "qceb_fabrock_*", "*.texproc.json")):
            data = json.load(open(settings_path, encoding="utf-8"))
            flips.append(data.get("normal_flip_green"))
        check("rock normal_flip_green true (fab flag)", True in flips, flips)

    # --- surface
    r = results.get("fabsurf")
    check("surface imported", r is not None and r.ok)
    if r:
        folder = os.path.join(root, "surfaces", r.asset.safe_base)
        check("surface dds diff", os.path.isfile(os.path.join(folder, r.asset.safe_base + "_diff.dds")))
        check("surface dds displ kept", os.path.isfile(os.path.join(folder, r.asset.safe_base + "_displ.dds")))
        mtl = open(os.path.join(folder, r.asset.safe_base + ".mtl"), encoding="utf-8").read()
        check("surface mtl single", "<SubMaterials>" not in mtl and "Heightmap" in mtl)
        check("surface staged: no tif/json in project", not leftovers(folder), leftovers(folder))
        check("surface no objects", len(r.objects) == 0)

    # --- multi material
    r = results.get("fabmulti")
    check("multimat imported", r is not None and r.ok)
    if r:
        folder = os.path.join(root, "3d", r.asset.safe_base)
        base = r.asset.safe_base
        mtl = open(os.path.join(folder, base + ".mtl"), encoding="utf-8").read()
        check("multimat mtl 2 subs", mtl.count('MtlFlags="524416"') == 2, mtl.count('MtlFlags="524416"'))
        check("multimat _m2 textures",
              os.path.isfile(os.path.join(folder, base + "_m2_diff.dds")))
        check("multimat two cgfs",
              os.path.isfile(os.path.join(folder, base + "_var1.cgf")) and
              os.path.isfile(os.path.join(folder, base + "_var2.cgf")))
        check("multimat staged: no tif/json in project", not leftovers(folder), leftovers(folder))
        # kept RC requests: sub_index per mesh (all slots of a mesh -> its material)
        subs = {}
        for req in glob.glob(os.path.join(stage_dirs["fabmulti"], base + "*.json")):
            data = json.load(open(req, encoding="utf-8"))
            subs[os.path.basename(req)] = sorted(set(m.get("sub_index") for m in data.get("materials", [])))
        check("multimat request sub indexes",
              subs.get(base + "_var1.json") == [0] and subs.get(base + "_var2.json") == [1], subs)

    print()
    failed = [name for name, ok, detail in CHECKS if not ok]
    if failed:
        print("FAILED CHECKS: %s" % ", ".join(failed))
        return 1
    print("ALL FAB E2E CHECKS PASSED (%d)" % len(CHECKS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
