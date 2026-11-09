# QuixelCEBridge

Live-link plugin for Quixel Bridge → CRYENGINE 5.7 Sandbox — **not yet
field-tested**, treat it as a work in progress.

Modeled after Blender's MSPlugin, it converts Megascans assets pushed from
Bridge into native CRYENGINE formats: textures → `_diff/_ddna/_spec/…` DDS,
meshes → CGF (with LODs), materials → `.mtl` (Illum / Vegetation shader),
then places the meshes in the level / assigns materials to the selection.
Megascans downloads can also be imported manually as an export **JSON** or
the **.zip** you get from Bridge, without Bridge running.

Pure Python (3.7), no build step required. Texture conversion is powered
by the core of
[Cryengine-Texture-Processor](https://github.com/z060142/Cryengine-Texture-Processor)
(bundled here as `texproc.exe` / `converter.exe`); mesh and DDS compilation
uses the engine's `rc.exe`.

---

## 1. Installation

Copy the whole `QuixelCEBridge` folder into the engine's Python plugin
directory (inside your CRYENGINE 5.7 installation):

```
<engine root>\Editor\Python\plugins\QuixelCEBridge\
```

Folder layout:

```
QuixelCEBridge\
    startup.py            entry point (runs automatically when Sandbox starts)
    config.json           settings (edit as needed)
    quixel_ce_bridge\     main package
    scripts\              menu command scripts (Tools > menu)
    bin\texproc.exe       texture conversion CLI
    bin\converter.exe     FBX → RC request CLI
```

After Sandbox starts, the Python console should show (stderr also goes to the
editor console):

```
[QuixelCEBridge] QuixelCEBridge 1.0.1 loading from ...
[QuixelCEBridge] listening for Quixel Bridge on 127.0.0.1:24981
[QuixelCEBridge]    rc.exe         <engine root>\Tools\rc\rc.exe
[QuixelCEBridge]    assets root    <current project's Assets path>
...
```

A log file is also written to `QuixelCEBridge\quixel_ce_bridge.log`.

## 2. Bridge-side settings

1. Bridge → **Export Settings** (bottom right)
2. Set **Export to** to **Custom Socket**
3. **Host** `127.0.0.1`, **Port** `24981` (must match config.json)
4. Geometry format: **FBX (Binary)**; textures can be JPG or PNG
5. If you want LODs / multiple variants, tick the corresponding
   LODs / Variations on the asset export entries

When you click **Export** in Bridge, the plugin receives the JSON and
imports everything automatically.

> Sending `Bye Megascans` from Bridge stops the listener (same behavior as
> MSPlugin); use the command to start listening again afterwards.

## 3. Using it inside the editor

* Panel: **Tools > Megascans > Quixel CE Bridge** (PySide2 panel: port,
  output folder, texture/geometry/material toggles, diagnostics, log,
  manual JSON / zip import buttons)
* Commands (Tools menu / Python console):
  * `QuixelCEBridge: Start Listening` / `Stop Listening`
  * `QuixelCEBridge: Import Bridge JSON` — manual import without Bridge
    running: an export JSON **or a Quixel .zip download** (the panel button
    accepts zips too)
  * `QuixelCEBridge: Process Pending` — pump the queue manually (usually not
    needed, QTimer runs it automatically)
  * `QuixelCEBridge: Status` — print tool paths / status

What an import produces:
* Textures (explicitly compiled with RC presets, not the automatic preset):
  `_diff.dds` (AlbedoWithCoverage, plants carry coverage alpha)
  `_ddna.dds` (NormalsWithSmoothness, roughness baked into alpha)
  `_spec.dds` (Reflectance), `_displ.dds` (Displacement), `_sss.dds`, etc.
* Material: `<name>.mtl` + `.mtl.cryasset`; the mesh is always multi-material
  (sub0 = mesh, sub1 = plant billboard)
* Meshes: `<name>.cgf`, `<name>_lod1.cgf`…; multiple variants →
  `<name>_varN.cgf`
* 3D assets are placed 3 m in front of the camera and selected; Surface
  assets are assigned to the current selection

## 4. Quick testing without Bridge

`_test\bridge_payload.json` (in the repo root's `_test\`) is a ready-to-use
fake Bridge export (a 3D rock, a metal surface, a plant + billboard, with
textures pointing at `_test\megascans\`).

**Importing a Quixel download zip**: an asset zip downloaded from Bridge (or
megascans.com) is just fbx + maps + `<id>.json` — no need to unpack it first:

* Panel button **Import Bridge JSON / Quixel zip...** and pick the zip; or
* Command `QuixelCEBridge: Import Bridge JSON` and pick the zip; or
* Python: `quixel_ce_bridge.controller.get().submit_file(r"C:\...\xxx_mid.zip")`

The plugin extracts it to a temp folder and cleans up after importing. The
fbx inside zips gets the same Raw-layer repair (UserData layers / vertex
cap) — see the troubleshooting section.

1. Open any project in Sandbox
2. **Tools > QuixelCEBridge: Import Bridge JSON**, pick
   `_test\bridge_payload.json` — or exercise the real socket with a
   one-liner:

   ```bash
   python -c "import socket;s=socket.create_connection(('127.0.0.1',24981));s.sendall(open(r'C:\path\to\QuixelBridge_CE\_test\bridge_payload.json','rb').read());s.close()"
   ```

3. Watch the Python console log and the output under
   `<project Assets>\Objects\Megascans\`

## 5. config.json reference

| Key | Default | Notes |
|---|---|---|
| `host` / `port` | `127.0.0.1` / `24981` | Listen address (must match Bridge) |
| `auto_start` | `true` | Start listening on startup |
| `assets_root` | `""` | Absolute project Assets path; empty = `get_game_folder()` |
| `output_subdir` | `Objects/Megascans` | Output subfolder |
| `rc_exe` | `""` | Empty = auto-find `<engine>\Tools\rc\rc.exe` |
| `texture.output_resolution` | `original` | `original` or `2048`/`4096`… |
| `texture.normal_is_opengl` | `true` | Bridge normals are OpenGL; flips the green channel |
| `texture.bake_ao_into_diffuse` | `false` | Bake AO into `_diff` |
| `texture.generate_dds` | `true` | false = keep TIF only (Sandbox compiles on first use) |
| `texture.delete_tif_after_dds` | `false` |  |
| `texture.prefer_exr_displacement` | `false` |  |
| `geometry.import_lods` | `true` | LOD1+ → `_lodN.cgf` |
| `geometry.physicalize` | `no` | `no` = no collision but keeps the full-resolution mesh; `default`/`obstruct`/`no_collide`/`proxy_only` = collision, but Raw meshes above `max_cgf_verts` get truncated |
| `geometry.max_cgf_verts` | `100000` | Raw FBX repair: truncate to whole triangles above this vertex count; `0` = disable the repair |
| `geometry.unit_size` | `""` | Empty = `file` (read from the FBX) |
| `material.shader` / `plant_shader` | `Illum` / `Illum` | `Vegetation` recommended for plants |
| `material.surface_pom` | `false` | Enable parallax occlusion for surfaces (uses `_displ`) |
| `placement.place_in_level` | `false` | Place 3D assets in front of the camera; unchecked = files only, place manually from the asset browser later |
| `placement.spawn_distance` | `3.0` | metres |
| `placement.apply_surface_to_selection` | `true` | Assign surface assets to the selection |
| `keep_work_files` | `false` | Debug: keep texproc/converter intermediates |

## 6. Troubleshooting

* **Port in use**: `cannot listen on 127.0.0.1:24981` — change the port in
  config.json **and** Bridge, restart the listener; make sure Blender's
  MSPlugin (28888) isn't fighting for the same port.
* **rc.exe NOT FOUND**: set `rc_exe` explicitly in config.
* **texproc.exe NOT FOUND**: make sure `bin\` is still inside the plugin folder.
* **assets root NOT FOUND / path points into the engine folder**: CE 5.7's
  `general.get_game_folder()` glues the project's asset directory onto the
  **engine** root (CryEdit.cpp: `Make(GetEnginePath(), GetGameFolder())`).
  The plugin corrects it automatically: `sys_game_folder` (the .cryproject's
  assetDirectory) joined with the project root (the engine sets the process
  working directory to the project root while loading the .cryproject —
  ProjectManager.cpp:214). The log then shows
  `assets root … (project path, engine-reported was …)`. If the correction
  fails it falls back to the engine-reported path; you can also hard-code
  `assets_root` in config.json.
* **Import fails with "unsupported mesh format"**: switch the Bridge export
  format to FBX.
* **Raw mesh / CGF only ~1KB**: RC has two silent killers (no errors, exit
  code 0): ① Quixel Raw FBX's `LayerElementUserData` layers make RC's FBX
  pipeline drop the whole mesh; ② physicalized CGFs cap at 65 535 vertices
  (after welding) — above that an empty mesh is written. The plugin repairs
  and truncates automatically before converting
  (`geometry.max_cgf_verts`); the log then shows
  `FBX repaired … truncated`. If it still fails, lower the value or export a
  lower-resolution tier from Bridge.
* **Want the full 500k+ vertex Raw mesh**: set `geometry.physicalize` to
  `no` (RC's 65 535 vertex cap only exists when physicalizing; without
  physicalization the full mesh compiles fine — verified at 500k vertices /
  1M faces → 36.5MB CGF). The trade-off is no collision — the asset is
  walk-through in Sandbox, fine for decoration; use the default truncating
  mode when you need collision.
* **Start-up fails with `ImportError: This package should not be accessible
  on Python 3` from `http/...`**: some engine installs ship the python-future
  compatibility bundle (`Tools\python\packages\common.zip`) on `sys.path`,
  whose py2-only `http` package shadows the stdlib and breaks any import
  chain that reaches `http.client` (e.g. `xml.sax.saxutils` →
  `urllib.request` → `http.client`). The plugin no longer imports anything
  that can reach it (mtl_writer ships its own XML escaping) — make sure you
  are on version 1.0.1+ if you see this trace.
* **CGF appears but has no material**: check that
  `Objects/Megascans\<...>\<name>.mtl` exists and open it in the Material
  Editor; texture paths are relative to the `.mtl` (`./xxx.dds`).
* **Panel doesn't show up**: when PySide2 is missing Sandbox only registers
  the commands; the console will install it via
  `pip` (`Editor\Python\windows\python.exe -m pip install PySide2`).
