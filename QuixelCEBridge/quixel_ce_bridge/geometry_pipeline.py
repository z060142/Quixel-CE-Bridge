# -*- coding: utf-8 -*-
"""FBX -> CGF through converter.exe (RC import request) + rc.exe.

converter.exe reads the FBX with ufbx and emits an RC import request
(materials, node tree, axes). We then patch the request for Megascans:
  * every FBX material -> one CE sub-material slot (0 = mesh, 1 = billboard)
  * material_filename -> the asset's shared .mtl
  * unit_size / physicalize from settings
and let RC compile it next to the .mtl. LODs are written as <name>_lodN.cgf,
which CRYENGINE picks up automatically.
"""
import json
import os
import shutil

from . import logger
from . import fbxfix
from .external import Converter, ResourceCompiler

VALID_PHYSICALIZE = ("no", "default", "obstruct", "no_collide", "proxy_only")
# RC caps CGF vertices (after welding) at 65535 and silently writes an empty
# mesh above it; a CGF smaller than this means the mesh never made it out.
MIN_GOOD_CGF_BYTES = 10 * 1024


def _patch_request(request, material_name, sub_index, physicalize, settings):
    request["material_filename"] = material_name
    unit = settings.get("geometry.unit_size") or "file"
    request["unit_size"] = unit
    if settings.get("geometry.forward_up_axes"):
        request["forward_up_axes"] = settings.get("geometry.forward_up_axes")
    if settings.get("geometry.scale") not in (None, "", 0):
        request["scale"] = float(settings.get("geometry.scale"))
    request["merge_all_nodes"] = bool(settings.get("geometry.merge_all_nodes", False))
    mats = request.get("materials") or []
    if not mats:
        logger.warning("FBX declares no materials; RC will use its default slot")
    for mat in mats:
        name = mat.get("name", "").lower()
        if any(token in name for token in ("proxy", "collision", "collider")):
            mat["physicalize"] = "proxy_only"
            mat["sub_index"] = sub_index
            continue
        mat["physicalize"] = physicalize
        mat["sub_index"] = sub_index
    return request


def compile_mesh(mesh, cgf_path, material_name, sub_index, physicalize, work_dir, settings, rc):
    """Convert one FBX/OBJ file to `cgf_path`. Returns the cgf path."""
    if mesh.format == "obj":
        logger.warning("OBJ export detected (%s). FBX is recommended for CRYENGINE; trying anyway."
                       % os.path.basename(mesh.path))
    if physicalize not in VALID_PHYSICALIZE:
        physicalize = "default"

    out_dir = os.path.dirname(cgf_path)
    cgf_name = os.path.basename(cgf_path)
    stem = os.path.splitext(cgf_name)[0]
    conv_dir = os.path.join(work_dir, "conv_" + stem)
    if os.path.isdir(conv_dir):
        shutil.rmtree(conv_dir, ignore_errors=True)

    # Quixel "Raw" FBX exports need repair before RC can see the mesh:
    # the UserData layers poison the FBX pipeline (mesh becomes a 0-face
    # helper -> empty CGF, exit 0, no errors) and RC's physics writer caps
    # vertices at 65535 after welding, silently writing an empty mesh above
    # it. The physics cap only applies when something gets physicalized -
    # with physicalize="no" RC skips MeshPhysicsData entirely and the full
    # mesh (500k+ verts) compiles fine (verified: 36.5MB CGF).
    source_path = mesh.path
    if mesh.format == "fbx":
        raw_max = settings.get("geometry.max_cgf_verts")
        max_verts = 100000 if raw_max in (None, "") else int(raw_max)
        if max_verts > 0 and physicalize == "no":
            # Physics cap doesn't apply when nothing gets physicalized:
            # keep the full-resolution mesh (layers still get repaired).
            max_verts = 10 ** 9
        report = None
        if max_verts != 0:
            try:
                fixed_path = os.path.join(work_dir, stem + "_fixed.fbx")
                report = fbxfix.fix_fbx(mesh.path, fixed_path, max_verts)
            except fbxfix.FBXFormatError as exc:
                logger.warning("  FBX repair skipped (%s); converting the original" % exc)
                report = None
        if report is not None:
            source_path = report["out"]
            logger.info("  FBX   repaired %s (vertices %d%s -> %d, %d polygons)" % (
                os.path.basename(mesh.path), report["original_verts"],
                ", truncated" if report["truncated"] else "",
                report["verts"], report["polys"]))

    converter = Converter(settings.get("_runtime.converter_exe"))
    outputs = converter.convert(source_path, conv_dir)
    with open(outputs["request"], "r", encoding="utf-8") as handle:
        request = json.load(handle)
    request = _patch_request(request, material_name, sub_index, physicalize, settings)

    # RC writes "<request stem>.<ext>" next to the request, so place it in the
    # destination folder and name it after the target CGF.
    request_path = os.path.join(out_dir, stem + ".json")
    with open(request_path, "w", encoding="utf-8") as handle:
        json.dump(request, handle, indent=2)

    if os.path.isfile(cgf_path):
        os.remove(cgf_path)
    try:
        rc.compile_fbx_request(request_path, os.path.abspath(source_path), cgf_name)
        if os.path.isfile(cgf_path) and os.path.getsize(cgf_path) < MIN_GOOD_CGF_BYTES:
            logger.error("  CGF %s is only %d bytes - RC dropped the mesh "
                         "(too many vertices or unsupported FBX layers?); "
                         "try a lower-res export" % (cgf_name, os.path.getsize(cgf_path)))
    finally:
        if not settings.get("keep_work_files"):
            try:
                os.remove(request_path)
            except OSError:
                pass
            if source_path != mesh.path and os.path.isfile(source_path):
                try:
                    os.remove(source_path)
                except OSError:
                    pass
    logger.info("  CGF  %s  (%s, %d material slot(s) -> sub %d)" % (
        cgf_name, os.path.basename(mesh.path), len(request.get("materials") or []), sub_index))
    return cgf_path
