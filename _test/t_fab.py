# -*- coding: utf-8 -*-
"""Fab payload parsing + server protocol tests (no engine tools needed).

Run:  python _test/t_fab.py           (fast, any python)
      python _test/embed37.py _test/t_fab.py   (under the engine's 3.7)
"""
import json
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else __file__))
sys.path.insert(0, os.path.join(HERE, "..", "QuixelCEBridge"))

from quixel_ce_bridge.bridge_payload import parse_payload
from quixel_ce_bridge.server import BridgeServer

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("PASS  %s" % name)
    else:
        print("FAIL  %s %s" % (name, detail))
        FAILURES.append(name)


ROCK = os.path.join(HERE, "megascans", "3d_rock_abc123")
PLANT = os.path.join(HERE, "megascans", "plant_p1")
SURFACE = os.path.join(HERE, "megascans", "surface_xyz")


def fab_rock():
    return {
        "id": "fabrock01", "path": "megascans/fabrock01",
        "meshes": [{"file": os.path.join(ROCK, "abc123_LOD0.fbx"), "name": "rock",
                    "material_index": -1,
                    "lods": [{"file": os.path.join(ROCK, "abc123_LOD1.fbx"), "material_index": -1}]}],
        "materials": [{"name": "mossy", "textures": {
            "albedo": os.path.join(ROCK, "abc123_2K_Albedo.jpg"),
            "normal": os.path.join(ROCK, "abc123_2K_Normal.jpg"),
            "occlusion": os.path.join(ROCK, "abc123_2K_AO.jpg"),
            "roughness": os.path.join(ROCK, "abc123_2K_Roughness.jpg"),
            "displacement": os.path.join(ROCK, "abc123_2K_Displacement.jpg"),
            "cavity": None, "orm": os.path.join(ROCK, "abc123_2K_AO.jpg"),
        }, "flipnmapgreenchannel": True}],
        "native_files": [], "additional_textures": [],
        "metadata": {
            "launcher": {"version": "2.0.0", "listening_port": 24563},
            "fab": {"listing": {"listingType": "3d-model", "title": "Mossy Rock",
                                "category": {"slug": "3d-assets--rock"}, "tags": [{"slug": "rock"}]},
                    "format": "FBX", "isQuixel": True, "quality": "mid"},
            "megascans": {"id": "abc123", "name": "Mossy Rock Fab", "categories": ["3d", "rock"],
                          "tags": ["rock"], "activeLOD": "lod0", "minLOD": "lod5", "workflow": "Specular",
                          "semanticTags": {"asset_type": "3d asset", "name": "Mossy Rock Fab"}},
        },
    }


def test_fab_rock():
    assets = parse_payload(json.dumps(fab_rock()))
    check("rock: one asset", len(assets) == 1, str(assets))
    a = assets[0]
    check("rock: type 3d", a.type == "3d", a.type)
    check("rock: id", a.id == "fabrock01", a.id)
    check("rock: display name from quixel", a.display_name == "Mossy Rock Fab", a.display_name)
    check("rock: safe_base", a.safe_base == "mossy_rock_fabrock01", a.safe_base)
    check("rock: maps normalized",
          sorted(a.textures) == ["albedo", "ao", "displacement", "normal", "orm", "roughness"],
          sorted(a.textures))
    check("rock: occlusion -> ao path", a.textures["ao"].path.endswith("abc123_2K_AO.jpg"))
    check("rock: null texture ignored", all(m.path for m in a.textures.values()))
    check("rock: flip green", a.normal_flip_green is True)
    check("rock: workflow", a.workflow == "specular", a.workflow)
    check("rock: two meshes", len(a.meshes) == 2, a.meshes)
    lods = sorted(m.lod for m in a.meshes)
    check("rock: lod chain 0,1", lods == [0, 1], lods)
    check("rock: variations", list(a.variations()) == [1], a.variations())
    check("rock: fab callback", a.fab_callback == {"port": 24563, "id": "fabrock01",
                                                   "path": "megascans/fabrock01"}, a.fab_callback)
    check("rock: no unsupported", a.unsupported_meshes() == [])


def test_fab_multimat():
    payload = fab_rock()
    payload["id"] = "fabmulti"
    payload["meshes"] = [
        {"file": os.path.join(ROCK, "abc123_LOD0.fbx"), "material_index": 0, "lods": []},
        {"file": os.path.join(ROCK, "abc123_LOD1.fbx"), "material_index": 1, "lods": []},
    ]
    second = dict(payload["materials"][0])
    second["name"] = "granite"
    second["textures"] = {"albedo": os.path.join(ROCK, "abc123_2K_Albedo.jpg")}
    second["flipnmapgreenchannel"] = False
    payload["materials"] = [payload["materials"][0], second]
    assets = parse_payload(json.dumps(payload))
    a = assets[0]
    check("multi: one asset", len(assets) == 1)
    check("multi: main + 1 extra material", len(a.extra_materials) == 1, a.extra_materials)
    check("multi: main material name", a.main_material_name == "mossy", a.main_material_name)
    check("multi: extra name", a.extra_materials[0]["name"] == "granite")
    check("multi: extra flip", a.extra_materials[0]["flip"] is False)
    check("multi: two variations", sorted(a.variations()) == [1, 2], a.variations())
    by_var = a.variations()
    check("multi: var1 mat 0", by_var[1][0].material_index == 0)
    check("multi: var2 mat 1", by_var[2][0].material_index == 1)


def test_fab_surface():
    payload = fab_rock()
    payload["id"] = "fabsurf"
    payload["meshes"] = []
    payload["materials"] = [{"name": "dirt", "textures": {
        "albedo": os.path.join(SURFACE, "xyz_2K_Albedo.jpg"),
        "normal": os.path.join(SURFACE, "xyz_2K_Normal.jpg"),
        "metal": os.path.join(SURFACE, "xyz_2K_Metalness.jpg"),
        "roughness": os.path.join(SURFACE, "xyz_2K_Roughness.jpg"),
        "displacement": os.path.join(SURFACE, "xyz_2K_Displacement.jpg"),
        "occlusion": os.path.join(SURFACE, "xyz_2K_AO.jpg"),
    }}]
    payload["metadata"]["fab"]["listing"]["listingType"] = "material"
    payload["metadata"]["megascans"] = {"name": "Dirt Surface", "categories": ["surface", "dirt"],
                                        "tags": [], "activeLOD": "", "workflow": "Metalness"}
    assets = parse_payload(json.dumps(payload))
    a = assets[0]
    check("surface: type surface", a.type == "surface", a.type)
    check("surface: metal -> metalness", "metalness" in a.textures, sorted(a.textures))
    check("surface: workflow metalness", a.workflow == "metalness", a.workflow)
    check("surface: no meshes", a.meshes == [])
    check("surface: not 3d", a.is_3d is False)


def test_fab_plant():
    payload = fab_rock()
    payload["id"] = "fabplant"
    payload["meshes"] = [{"file": os.path.join(PLANT, "Var1_LOD0.fbx"), "material_index": -1,
                          "lods": [{"file": os.path.join(PLANT, "Var1_LOD1.fbx")},
                                   {"file": os.path.join(PLANT, "Var1_LOD4.fbx")}]}]
    payload["materials"] = [{"name": "fern", "textures": {
        "albedo": os.path.join(PLANT, "Textures", "Atlas", "albedo.jpg"),
        "opacity": os.path.join(PLANT, "Textures", "Atlas", "opacity.jpg"),
        "normal": os.path.join(PLANT, "Textures", "Atlas", "normal.jpg"),
    }, "flipnmapgreenchannel": False}]
    payload["metadata"]["fab"]["listing"]["category"]["slug"] = "nature-plants--plants--ferns"
    payload["metadata"]["megascans"] = {"name": "Fern Plant", "categories": ["3dplant"],
                                        "tags": [], "activeLOD": "lod0", "minLOD": "lod2"}
    assets = parse_payload(json.dumps(payload))
    a = assets[0]
    check("plant: type 3dplant", a.type == "3dplant", a.type)
    check("plant: is_plant", a.is_plant is True)
    check("plant: 3 meshes", len(a.meshes) == 3, a.meshes)
    check("plant: opacity kept", "opacity" in a.textures)
    check("plant: min_lod", a.min_lod == 2, a.min_lod)


def test_fab_nonquixel():
    payload = {
        "id": "mkt123", "path": "marketplace/mkt123",
        "meshes": [{"file": r"C:\cache\mkt123\model.glb", "material_index": -1, "lods": []}],
        "materials": [{"name": "mat", "textures": {
            "albedo": r"C:\cache\mkt123\tex\diffuse.png",
            "normal": r"C:\cache\mkt123\tex\normal.png",
            "roughness": r"C:\cache\mkt123\tex\rough.png",
        }}],
        "native_files": [r"C:\cache\mkt123\scene.blend"], "additional_textures": [],
        "metadata": {"launcher": {"listening_port": 24563},
                     "fab": {"listing": {"listingType": "3d-model", "title": "Marketplace Thing",
                                         "category": {"slug": "props"}},
                             "isQuixel": False}},
    }
    assets = parse_payload(json.dumps(payload))
    a = assets[0]
    check("mkt: one asset", len(assets) == 1)
    check("mkt: type 3d", a.type == "3d", a.type)
    check("mkt: name from listing", a.display_name == "Marketplace Thing", a.display_name)
    check("mkt: glb unsupported", [m.format for m in a.unsupported_meshes()] == ["glb"])
    check("mkt: no variations", a.variations() == {})
    check("mkt: textures kept", sorted(a.textures) == ["albedo", "normal", "roughness"])
    check("mkt: native files", a.extra_files.get("native") == [r"C:\cache\mkt123\scene.blend"])
    check("mkt: callback", a.fab_callback["port"] == 24563)


def test_fab_no_metadata():
    """Fab-style payload without the metadata block must still parse."""
    payload = {"id": "naked01", "path": "x",
               "meshes": [{"file": os.path.join(ROCK, "abc123_LOD0.fbx"), "lods": []}],
               "materials": [{"textures": {"albedo": os.path.join(ROCK, "abc123_2K_Albedo.jpg")}}]}
    assets = parse_payload(json.dumps(payload))
    check("naked: one asset", len(assets) == 1)
    a = assets[0]
    check("naked: type 3d", a.type == "3d", a.type)
    check("naked: albedo", "albedo" in a.textures)
    check("naked: flip defaults to False (Fab semantics)", a.normal_flip_green is False)


def test_old_formats_regress():
    raw = open(os.path.join(HERE, "bridge_payload.json"), "rb").read()
    assets = parse_payload(raw)
    check("old: 3 socket assets", len(assets) == 3, len(assets))
    rock = [a for a in assets if a.id == "abc123"][0]
    check("old: rock type 3d", rock.type == "3d", rock.type)
    check("old: rock maps", sorted(rock.textures) == ["albedo", "ao", "displacement", "normal", "roughness"],
          sorted(rock.textures))
    check("old: rock meshes 2", len(rock.meshes) == 2)
    check("old: rock flip untouched", rock.normal_flip_green is None)
    check("old: rock no extra materials", rock.extra_materials == [])
    plant = [a for a in assets if a.id == "p1"][0]
    check("old: plant type", plant.type == "3dplant", plant.type)
    sofa_src = r"E:\Modeling\interior_classic_sofa_chaise_velvet_red_ornate_ybmjefm_raw\ybmjefm.json"
    if os.path.isfile(sofa_src):
        assets = parse_payload(open(sofa_src, "rb").read(), os.path.dirname(sofa_src))
        check("old: metadata v2 still parses", len(assets) == 1 and assets[0].is_3d, len(assets))
    else:
        print("SKIP  old: metadata v2 (fixture missing)")


def test_server_protocol():
    received = []
    server = BridgeServer("127.0.0.1", 24997, received.append, plugin_version="9.9.9",
                          fab_port=24996)
    check("server: start", server.start() is True)
    try:
        # 1) ping -> version reply, then the payload on the SAME connection
        client = socket.create_connection(("127.0.0.1", 24997), timeout=5)
        client.sendall(b"ping")
        reply = client.recv(200)
        check("server: ping reply", reply == b"{'plugin_version': '9.9.9'}", reply)
        client.sendall(json.dumps(fab_rock()).encode("utf-8"))
        client.close()
        deadline = time.time() + 5
        while not received and time.time() < deadline:
            time.sleep(0.05)
        check("server: payload after ping", len(received) == 1 and b"fabrock01" in received[0])
        # 2) null-terminated payload (Fab appends \0 like its own plugins)
        client = socket.create_connection(("127.0.0.1", 24997), timeout=5)
        client.sendall((json.dumps(fab_rock()) + "\0").encode("utf-8"))
        client.close()
        deadline = time.time() + 5
        while len(received) < 2 and time.time() < deadline:
            time.sleep(0.05)
        check("server: null-terminated payload", len(received) == 2)
        # 3) same flow on the Fab port
        client = socket.create_connection(("127.0.0.1", 24996), timeout=5)
        client.sendall(b"ping")
        reply = client.recv(200)
        check("server: fab port ping reply", reply == b"{'plugin_version': '9.9.9'}", reply)
        client.sendall(json.dumps(fab_rock()).encode("utf-8"))
        client.close()
        deadline = time.time() + 5
        while len(received) < 3 and time.time() < deadline:
            time.sleep(0.05)
        check("server: fab port payload", len(received) == 3)
        # 4) Bye Fab does NOT stop the listener (either port)
        client = socket.create_connection(("127.0.0.1", 24996), timeout=5)
        client.sendall(b"Bye Fab")
        client.close()
        time.sleep(0.5)
        check("server: still running after Bye Fab", server.running is True)
        # 5) Bye Megascans still stops it (closes all ports)
        client = socket.create_connection(("127.0.0.1", 24997), timeout=5)
        client.sendall(b"Bye Megascans")
        client.close()
        deadline = time.time() + 5
        while server.running and time.time() < deadline:
            time.sleep(0.05)
        check("server: Bye Megascans stops", server.running is False)
    finally:
        server.stop()


def test_server_fab_port_taken():
    """A busy Fab port must not break the main Bridge port."""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 24996))
    blocker.listen(1)
    received = []
    server = BridgeServer("127.0.0.1", 24997, received.append, plugin_version="9.9.9",
                          fab_port=24996)
    check("server: start with busy fab port", server.start() is True)
    try:
        client = socket.create_connection(("127.0.0.1", 24997), timeout=5)
        client.sendall(json.dumps(fab_rock()).encode("utf-8"))
        client.close()
        deadline = time.time() + 5
        while not received and time.time() < deadline:
            time.sleep(0.05)
        check("server: main port still works", len(received) == 1)
    finally:
        server.stop()
        blocker.close()


def main():
    test_fab_rock()
    test_fab_multimat()
    test_fab_surface()
    test_fab_plant()
    test_fab_nonquixel()
    test_fab_no_metadata()
    test_old_formats_regress()
    test_server_protocol()
    test_server_fab_port_taken()
    print()
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("ALL FAB TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
