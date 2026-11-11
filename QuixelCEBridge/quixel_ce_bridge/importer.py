# -*- coding: utf-8 -*-
"""Import one Megascans asset (worker thread, no `sandbox` calls).

Output layout (all under <assets_root>/<output_subdir>/<type>/<name_id>/):

    <name_id>_diff.dds / _ddna.dds / _spec.dds / _displ.dds ...   textures
    <name_id>_billboard_diff.dds ...                              plant billboard set
    <name_id>.mtl (+ .cryasset)                                   material
    <name_id>.cgf, <name_id>_lod1.cgf ...                         single variation
    <name_id>_var2.cgf, <name_id>_var2_lod1.cgf ...               more variations

With "stage_imports" (default on) everything above is first built in a
staging folder inside the per-import work folder (see stage_base(): by
default <project>/user/QuixelCEBridge/qceb_<id>_<rand>/, i.e. inside the
game project but outside Assets, so the editor never scans it); when the
whole asset is done only the final files (.dds / .cgf / .mtl + their
.cryasset) are moved into the project. TIF sources and RC request jsons
never touch the asset folder, and on the same volume each file is moved
with a single atomic rename, so Sandbox's asset watcher never sees a
half-written file.

The returned ImportResult is consumed on the main thread by scene.py.
"""
import os
import re
import shutil
import tempfile
import time
import traceback
from xml.sax.saxutils import escape

from . import logger
from .external import ResourceCompiler, ToolError
from .geometry_pipeline import compile_mesh
from .mtl_writer import build_material, write_mtl
from .paths import ensure_dir, game_relative, is_uuid
from .texture_pipeline import process_texture_set


class ImportResult(object):
    def __init__(self, asset):
        self.asset = asset
        self.ok = False
        self.folder = None
        self.material_game_path = None        # e.g. objects/megascans/3d/rock_x/rock_x (no ext)
        self.objects = []                      # [(display name, cgf game path)]
        self.errors = []
        self.warnings = []
        self.seconds = 0.0

    def __repr__(self):
        return "ImportResult(%s ok=%s objects=%d)" % (self.asset.safe_base, self.ok, len(self.objects))


TYPE_FOLDERS = {"3d": "3d", "3dplant": "3dplant", "surface": "surfaces", "atlas": "atlases",
                "decal": "decals", "brush": "brushes", "displacement": "displacements"}

# What counts as a finished asset; everything else (TIF sources, RC request
# jsons, texproc settings) stays in the staging folder.
FINAL_EXTENSIONS = (".dds", ".cgf", ".mtl", ".cryasset")
TMP_SUFFIX = ".qcebtmp"


def publish_stage(stage_dir, dest_dir, keep_tif=False):
    """Move the final files of one asset from `stage_dir` into `dest_dir`.

    On the same volume (the default stage_dir "user" lives inside the
    project) every file is moved with a single atomic rename, so the
    project only ever sees complete files. Across volumes each file is
    first copied to '<dest>/<name>.qcebtmp' (an extension Sandbox's asset
    watcher ignores) and then renamed in place - still atomic per file.
    Returns (moved count, [(name, error)]). Raises ToolError when a copy
    already failed, in which case no destination file has been touched.
    """
    extensions = FINAL_EXTENSIONS + ((".tif",) if keep_tif else ())
    plan = []
    for root, _dirs, files in os.walk(stage_dir):
        rel_root = os.path.relpath(root, stage_dir)
        for name in sorted(files):
            if not name.lower().endswith(extensions):
                continue
            rel = name if rel_root == "." else os.path.join(rel_root, name)
            plan.append((os.path.join(root, name), os.path.join(dest_dir, rel)))

    def parent_of(dst):
        parent = os.path.dirname(dst)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)

    same_volume = (os.path.splitdrive(os.path.abspath(stage_dir))[0].lower()
                   == os.path.splitdrive(os.path.abspath(dest_dir))[0].lower())
    if same_volume:
        failures = []
        for src, dst in plan:
            try:
                parent_of(dst)
                os.replace(src, dst)   # atomic move
            except OSError as error:
                failures.append((os.path.basename(dst), str(error)))
        return len(plan) - len(failures), failures

    copies = []
    try:
        for src, dst in plan:
            parent_of(dst)
            tmp = dst + TMP_SUFFIX
            shutil.copy2(src, tmp)
            copies.append((tmp, dst))
    except Exception as error:  # noqa - destination untouched, nothing renamed yet
        for tmp, _dst in copies:
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise ToolError("could not copy %s into %s: %s"
                        % (getattr(error, "filename", None) or "files", dest_dir, error))
    failures = []
    for tmp, dst in copies:
        try:
            os.replace(tmp, dst)
        except OSError as error:
            failures.append((os.path.basename(dst), str(error)))
    return len(copies) - len(failures), failures


_QUIXEL_ID = re.compile(r'<Detail name="quixelId">([^<]*)</Detail>')


def annotate_cryassets(folder, asset):
    """Record the asset's original id / name in the <Details> of its .mtl / .cgf .cryasset files.

    Fab UUIDs are kept out of file names (MAX_PATH), so this is where the
    original identity lives; the Asset Browser shows these as asset details.
    """
    pairs = (("quixelId", asset.id), ("quixelName", asset.display_name),
             ("quixelType", getattr(asset, "type", "")), ("quixelWorkflow", getattr(asset, "workflow", "")))
    block = "".join('  <Detail name="%s">%s</Detail>\n' % (key, escape(str(value))) for key, value in pairs if value)
    if not block:
        return
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if not name.lower().endswith((".mtl.cryasset", ".cgf.cryasset")):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8", newline="") as handle:
                    text = handle.read()
                if 'name="quixelId"' in text:
                    continue
                if " </Details>" in text:
                    text = text.replace(" </Details>", block + " </Details>", 1)
                else:
                    text = text.replace("</AssetMetadata>", " <Details>\n" + block + " </Details>\n</AssetMetadata>", 1)
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(text)
            except (OSError, UnicodeError) as error:
                logger.warning("cannot annotate %s: %s" % (name, error))


def _unique_base(asset, assets_root, sub):
    """asset.safe_base, or safe_base_2 / _3 ... when that folder holds a DIFFERENT asset.

    Without the UUID in the name two Fab assets with the same title would
    overwrite each other. The owner is read from the quixelId written by
    annotate_cryassets(); folders without one (older imports) are reused.
    """
    root = os.path.join(assets_root, sub, TYPE_FOLDERS.get(asset.type, asset.type or "misc"))
    for number in range(1, 100):
        candidate = asset.safe_base if number == 1 else "%s_%d" % (asset.safe_base, number)
        try:
            with open(os.path.join(root, candidate, candidate + ".mtl.cryasset"), encoding="utf-8") as handle:
                owner = _QUIXEL_ID.search(handle.read())
        except (OSError, UnicodeError):
            return candidate
        if not owner or owner.group(1) == asset.id:
            return candidate
    return asset.safe_base


def _kind_for(asset):
    if asset.is_plant:
        return "plant"
    if asset.is_3d:
        return "3d"
    if asset.type in ("atlas", "decal"):
        return "decal"
    return "surface"


def _mesh_sub_index(mesh, count):
    """Fab meshes carry material_index (into the MTL sub list)."""
    index = getattr(mesh, "material_index", -1)
    return index if isinstance(index, int) and 0 <= index < count else 0


def _safe_id(name, limit=16):
    """Filesystem-safe, short work-folder prefix from an asset id."""
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in str(name)[:limit])
    return safe or "asset"


def stage_base(settings, assets_root):
    """Where the per-import work folders (staging + intermediates) live.

    stage_dir setting:
      "user" (default) -> <project>/user/QuixelCEBridge - inside the game
                          project but outside the folder the editor's asset
                          watcher scans, so half-finished files never reach it
      "temp"           -> the system temp folder
      absolute path    -> exactly there (any relative path is taken relative
                          to the project root)
    Returns "" for the system temp folder.

    The project root is chosen so staging is never INSIDE the scanned asset
    folder: "<proj>/Assets" -> "<proj>"; a folder that is the engine's game
    folder (reported by scene.game_folder - GameSDK-style projects where the
    whole game folder is the asset root) -> its parent, so user/ sits beside
    it; anything else (a custom output root) -> unchanged.
    """
    value = (settings.get("stage_dir") or "user").strip()
    root = os.path.normpath(assets_root or "")
    engine_root = (settings.get("_runtime.game_folder") or "").strip()
    game_root = bool(settings.get("_runtime.game_root")) or (
        bool(root and engine_root) and
        os.path.normcase(os.path.normpath(engine_root)) == os.path.normcase(root))
    if not root:
        project = ""
    elif os.path.basename(root).lower() == "assets" or game_root:
        project = os.path.dirname(root)
    else:
        project = root
    if not value or value.lower() == "user":
        return os.path.join(project, "user", "QuixelCEBridge") if project else ""
    if value.lower() == "temp":
        return ""
    if os.path.isabs(value):
        return value
    return os.path.join(project, value) if project else ""


def sweep_work_dirs(settings, assets_root, max_age_hours=24):
    """Remove work folders left behind by crashed imports (older than a day)."""
    base = stage_base(settings, assets_root)
    if not base or not os.path.isdir(base):
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    try:
        entries = os.listdir(base)
    except OSError:
        return 0
    for name in entries:
        if not name.startswith("qceb_"):
            continue
        path = os.path.join(base, name)
        try:
            if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
                logger.info("removed leftover work folder %s" % path)
        except OSError:
            pass
    return removed


def import_asset(asset, settings, assets_root, progress=None):
    """Run the full pipeline for one asset. Never raises; errors land in result."""
    started = time.time()
    result = ImportResult(asset)
    progress = progress or (lambda text: None)
    base = stage_base(settings, assets_root)
    prefix = "qceb_%s_" % _safe_id(asset.id)
    try:
        if base:
            os.makedirs(base, exist_ok=True)
            work_dir = tempfile.mkdtemp(prefix=prefix, dir=base)
        else:
            work_dir = tempfile.mkdtemp(prefix=prefix)
    except OSError as error:
        logger.warning("staging folder %s unavailable (%s); using the system temp folder"
                       % (base or "", error))
        work_dir = tempfile.mkdtemp(prefix=prefix)
    try:
        _import(asset, settings, assets_root, result, work_dir, progress)
        result.ok = not result.errors
    except ToolError as error:
        result.errors.append(str(error))
        logger.error(str(error))
    except Exception as error:  # noqa
        result.errors.append("%s: %s" % (type(error).__name__, error))
        logger.error("unexpected failure importing %s\n%s" % (asset.display_name, traceback.format_exc()))
    finally:
        if settings.get("keep_work_files"):
            logger.info("work files kept in " + work_dir)
        else:
            shutil.rmtree(work_dir, ignore_errors=True)
    result.seconds = time.time() - started
    return result


def _import(asset, settings, assets_root, result, work_dir, progress):
    kind = _kind_for(asset)
    sub = (settings.get("output_subdir") or "Objects/Megascans").strip("/\\")
    base = _unique_base(asset, assets_root, sub)
    folder = ensure_dir(os.path.join(assets_root, sub, TYPE_FOLDERS.get(asset.type, asset.type or "misc"), base))
    result.folder = folder

    # Build in a staging folder first; publish only the final files at the end
    # so half-written assets never appear inside the project.
    stage = ensure_dir(os.path.join(work_dir, "stage")) if settings.get("stage_imports", True) else None
    out_dir = stage or folder

    def publish():
        annotate_cryassets(out_dir, asset)
        if out_dir == folder:
            return
        keep_tif = not settings.get("texture.generate_dds", True) or not rc
        moved, failures = publish_stage(out_dir, folder, keep_tif=keep_tif)
        logger.info("  published %d file(s) into the project (%s)" % (moved, os.path.basename(folder)))
        for name, why in failures:
            result.errors.append("could not move %s into the asset folder (close Sandbox's asset "
                                 "browser or free the file and re-import): %s" % (name, why))

    logger.info("=== %s -> %s%s" % (asset.summary(), folder,
                                 " (staged)" if stage else ""))

    rc = None
    rc_exe = settings.get("_runtime.rc_exe")
    if rc_exe:
        rc = ResourceCompiler(rc_exe, settings.get("texture.rc_parallel", 0))
    elif asset.is_3d:
        raise ToolError("rc.exe is required to build CGF meshes; set rc_exe in config.json")
    else:
        result.warnings.append("rc.exe not found: textures stay as TIF (Sandbox compiles them on demand)")

    # --------------------------------------------------------------- textures
    # Meshes never use _displ (Heightmap is dropped for non-POM materials),
    # so don't waste an 8K RC compile on it.
    def maps_for_kind(textures):
        if kind in ("3d", "plant") and "normal" in textures:
            return {k: v for k, v in textures.items() if k not in ("displacement", "bump")}
        return textures

    extra_files = getattr(asset, "extra_files", None) or {}
    if extra_files.get("native"):
        result.warnings.append("%d native file(s) skipped (only FBX meshes are supported): %s"
                              % (len(extra_files["native"]), ", ".join(
                                  os.path.basename(p) for p in extra_files["native"][:5])))
    if extra_files.get("textures"):
        result.warnings.append("%d additional texture(s) skipped" % len(extra_files["textures"]))

    progress("%s: textures" % asset.display_name)
    main_set = process_texture_set(maps_for_kind(asset.textures), asset.workflow, base, out_dir, work_dir, settings,
                                   is_plant=asset.is_plant, rc=rc, alpha_test=True,
                                   flip_green=getattr(asset, "normal_flip_green", None))
    result.warnings.extend(main_set.errors)

    # Fab payloads can carry several materials: one per sub-material
    extra_sets = []
    for index, mat in enumerate(getattr(asset, "extra_materials", None) or []):
        sub_base = "%s_m%d" % (base, index + 2)
        progress("%s: material %s" % (asset.display_name, mat.get("name") or sub_base))
        mat_set = process_texture_set(maps_for_kind(mat.get("textures") or {}), asset.workflow, sub_base,
                                       out_dir, work_dir, settings, is_plant=asset.is_plant, rc=rc,
                                       alpha_test=True, flip_green=mat.get("flip"))
        result.warnings.extend(mat_set.errors)
        extra_sets.append((mat, mat_set))

    billboard_set = None
    variations = asset.variations(include_lods=bool(settings.get("geometry.import_lods", True))) if asset.is_3d else {}
    needs_billboard = asset.is_plant and asset.billboard_textures and any(
        m.is_billboard for meshes in variations.values() for m in meshes)
    if needs_billboard:
        progress("%s: billboard textures" % asset.display_name)
        billboard_set = process_texture_set(asset.billboard_textures, asset.workflow, base + "_billboard",
                                            out_dir, work_dir, settings, is_plant=True, rc=rc, alpha_test=True)
        result.warnings.extend(billboard_set.errors)

    # --------------------------------------------------------------- material
    pom = kind == "surface" and bool(settings.get("material.surface_pom", False))
    materials = [build_material(base, main_set, out_dir, settings, kind=kind, has_displacement_pom=pom)]
    for index, (mat, mat_set) in enumerate(extra_sets):
        materials.append(build_material("%s_m%d" % (base, index + 2), mat_set, out_dir, settings,
                                        kind=kind, has_displacement_pom=pom))
    if billboard_set is not None and billboard_set.files:
        materials.append(build_material(base + "_billboard", billboard_set, out_dir, settings, kind="billboard"))
    write_mtl(os.path.join(out_dir, base + ".mtl"), materials, force_multi=asset.is_3d)
    result.material_game_path = os.path.splitext(game_relative(os.path.join(folder, base + ".mtl"), assets_root))[0]
    logger.info("  MTL  %s (%d sub material(s))" % (base + ".mtl", len(materials)))

    if not asset.is_3d:
        publish()
        return

    # --------------------------------------------------------------- geometry
    if not variations:
        unsupported = asset.unsupported_meshes()
        if unsupported:
            raise ToolError("unsupported mesh format(s): %s. Export FBX from Bridge / Fab."
                            % ", ".join(sorted(set(m.format for m in unsupported))))
        if extra_files.get("native"):
            raise ToolError("no FBX meshes in the payload, only native app files (%s)"
                            % ", ".join(sorted(set(os.path.splitext(p)[1] for p in extra_files["native"]))))
        raise ToolError("no meshes in the export (choose the FBX format in the Bridge/Fab export settings)")

    physicalize = settings.get("geometry.physicalize", "default")
    if asset.is_plant and physicalize == "default":
        physicalize = "no_collide"
    multi_var = len(variations) > 1
    n_mesh_subs = 1 + len(extra_sets)
    slot_materials = None
    if extra_sets:
        # map FBX material slot names to sub materials (Fab names usually match)
        slot_materials = [(getattr(asset, "main_material_name", "") or "", 0)]
        slot_materials += [(mat.get("name") or "", index + 1) for index, (mat, _set) in enumerate(extra_sets)]
    for var_index, meshes in variations.items():
        stem = base if not multi_var else "%s_var%d" % (base, var_index)
        progress("%s: mesh %s" % (asset.display_name, stem))
        lod_number = 0
        for mesh in meshes:
            cgf_name = stem + (".cgf" if lod_number == 0 else "_lod%d.cgf" % lod_number)
            if mesh.is_billboard and billboard_set is not None and billboard_set.files:
                sub_index = len(materials) - 1
            else:
                sub_index = _mesh_sub_index(mesh, n_mesh_subs)
            try:
                compile_mesh(mesh, os.path.join(out_dir, cgf_name), base, sub_index,
                             physicalize if lod_number == 0 else "no_collide", work_dir, settings, rc,
                             slot_materials=slot_materials)
            except ToolError as error:
                if lod_number == 0:
                    raise
                result.warnings.append(str(error))
                logger.warning("LOD skipped: %s" % error)
                break
            if lod_number == 0:
                label = var_index if multi_var else ("" if is_uuid(asset.id) else asset.id)
                result.objects.append(("%s_%s" % (asset.display_name.replace(" ", "_"), label) if label != ""
                                       else asset.display_name.replace(" ", "_"),
                                       game_relative(os.path.join(folder, cgf_name), assets_root)))
            lod_number += 1
            if lod_number >= 6:
                break   # CRYENGINE supports LOD0..LOD5 by default

    publish()

