# -*- coding: utf-8 -*-
"""Megascans maps -> CRYENGINE textures through CryEngineTextureProcessor.

Instead of letting texproc guess map types from file names, we build the
`scan --out` grouping JSON ourselves from Bridge's explicit component types
and run `texproc process --groups`. texproc then performs the PBR conversion
(metal/rough -> spec/gloss, gloss into _ddna alpha, opacity into _diff alpha,
displacement into _displ alpha ...) and writes TIF/LZW files that RC turns
into DDS with explicit presets.
"""
import json
import os

from . import logger
from .external import ResourceCompiler, Texproc, preset_for

# Bridge component type -> texproc source type
BRIDGE_TO_TEXPROC = {
    "albedo": "diffuse",
    "normal": "normal",
    "gloss": "glossiness",
    "roughness": "roughness",
    "specular": "specular",
    "metalness": "metallic",
    "ao": "ao",
    "opacity": "alpha",
    "displacement": "displacement",
    "translucency": "sss",
    "emission": "emissive",
    "emissive": "emissive",
}

# CRYENGINE texture slots by output suffix (Illum / Vegetation)
SUFFIX_TO_MAP = (
    ("_diff", "Diffuse"),
    ("_ddna", "Bumpmap"),
    ("_ddn", "Bumpmap"),
    ("_spec", "Specular"),
    ("_displ", "Heightmap"),
    ("_em", "Emittance"),
    ("_emissive", "Emittance"),
    ("_sss", "SubSurface"),
)


class TextureSet(object):
    """Result of processing one texture group."""

    def __init__(self, base_name, folder):
        self.base_name = base_name
        self.folder = folder
        self.files = {}            # CE map -> absolute path (tif or dds)
        self.diff_has_alpha = False
        self.has_translucency = False
        self.errors = []

    def map_path(self, ce_map):
        return self.files.get(ce_map)

    def __repr__(self):
        return "TextureSet(%s, %s)" % (self.base_name, sorted(self.files))


def select_sources(asset_textures, workflow, settings):
    """Pick which Bridge maps feed texproc. Returns {texproc_type: TextureMap}."""
    tex = dict(asset_textures)
    chosen = {}

    if "albedo" in tex:
        chosen["diffuse"] = tex["albedo"]
    if "normal" in tex:
        chosen["normal"] = tex["normal"]
    elif "displacement" not in tex and "bump" in tex:
        chosen["displacement"] = tex["bump"]          # texproc builds a normal from height

    if "gloss" in tex:
        chosen["glossiness"] = tex["gloss"]
    elif "roughness" in tex:
        chosen["roughness"] = tex["roughness"]

    use_metal = workflow.startswith("metal") and "metalness" in tex
    if "specular" in tex and not use_metal:
        chosen["specular"] = tex["specular"]
    elif "metalness" in tex:
        chosen["metallic"] = tex["metalness"]

    if "opacity" in tex:
        chosen["alpha"] = tex["opacity"]

    if "displacement" in tex:
        disp = tex["displacement"]
        if settings.get("texture.prefer_exr_displacement") and disp.format != "exr":
            exr = os.path.splitext(disp.path)[0] + ".exr"
            if os.path.isfile(exr):
                disp = type(disp)(disp.type, exr, "exr", os.path.basename(exr))
        chosen["displacement"] = disp

    if settings.get("texture.bake_ao_into_diffuse") and "ao" in tex:
        chosen["ao"] = tex["ao"]
    if "translucency" in tex:
        chosen["sss"] = tex["translucency"]
    for key in ("emission", "emissive"):
        if key in tex:
            chosen["emissive"] = tex[key]
            break

    missing = [m for m in chosen.values() if not os.path.isfile(m.path)]
    for item in missing:
        logger.warning("map not found on disk, skipped: %s" % item.path)
    return {k: v for k, v in chosen.items() if os.path.isfile(v.path)}


def build_group(base_name, sources):
    """texproc ScanGroup JSON built from explicit types (no filename guessing)."""
    slots = {}
    for source_type, tmap in sorted(sources.items()):
        ext = os.path.splitext(tmap.path)[1].lower()
        slots[source_type] = {
            "path": os.path.abspath(tmap.path),
            # Neutral filename: texproc infers the normal convention from it,
            # so we keep it free of "_gl"/"opengl" tokens and flip explicitly.
            "filename": "%s_%s%s" % (base_name, source_type, ext),
            "source_type": source_type,
            "base_name": base_name,
            "header": None,
        }
    return {"key": base_name.lower(), "base_name": base_name, "slots": slots,
            "unknown": [], "diagnostics": []}


def texproc_settings(settings, sources, is_plant):
    data = {
        "output_resolution": str(settings.get("texture.output_resolution", "original")),
        "diff_format": "diffuse_ao" if "ao" in sources else "albedo",
        "normal_flip_green": bool(settings.get("texture.normal_is_opengl", True)),
        "process_metallic": True,
        "generate_missing_spec": True,
        "generate_missing_emissive": False,
        "generate_missing_sss": False,
        "generate_sss_from_diffuse": False,
        "texture_types": {
            "diff": True, "spec": True, "ddna": True,
            "displ": "displacement" in sources,
            "emissive": "emissive" in sources,
            "sss": "sss" in sources and is_plant,
        },
    }
    extra = settings.get("texture.texproc_settings") or {}
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key].update(value)
        else:
            data[key] = value
    return data


def _classify_outputs(folder, base_name):
    found = {}
    lower_base = base_name.lower()
    for name in os.listdir(folder):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in (".tif", ".tiff") or not stem.lower().startswith(lower_base):
            continue
        suffix = stem[len(base_name):].lower()
        for suf, ce_map in SUFFIX_TO_MAP:
            if suffix == suf:
                # _ddna wins over _ddn for the same slot
                if ce_map in found and suffix == "_ddn":
                    break
                found[ce_map] = os.path.join(folder, name)
                break
    return found


def process_texture_set(asset_textures, workflow, base_name, out_dir, work_dir, settings,
                        is_plant=False, rc=None, alpha_test=True):
    """Run texproc (+RC) for one texture group. Returns TextureSet."""
    result = TextureSet(base_name, out_dir)
    sources = select_sources(asset_textures, workflow, settings)
    if "diffuse" not in sources and "normal" not in sources:
        result.errors.append("no albedo/normal map in Bridge export")
        logger.warning("%s: no usable maps (got: %s)" % (base_name, ", ".join(sorted(asset_textures)) or "none"))
        return result

    logger.info("texproc %s <- %s" % (base_name, ", ".join(
        "%s:%s" % (k, os.path.basename(v.path)) for k, v in sorted(sources.items()))))

    groups_path = os.path.join(work_dir, base_name + ".groups.json")
    settings_path = os.path.join(work_dir, base_name + ".texproc.json")
    with open(groups_path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "groups": [build_group(base_name, sources)], "diagnostics": []}, handle, indent=2)
    with open(settings_path, "w", encoding="utf-8") as handle:
        json.dump(texproc_settings(settings, sources, is_plant), handle, indent=2)

    texproc = Texproc(settings.get("_runtime.texproc_exe"))
    proc = texproc.process(groups_path, settings_path, out_dir)
    if proc.code != 0:
        result.errors.append("texproc reported partial failures (see log)")

    outputs = _classify_outputs(out_dir, base_name)
    if not outputs:
        raise RuntimeError("texproc produced no outputs for %s:\n%s" % (base_name, proc.tail()))
    result.diff_has_alpha = "alpha" in sources
    result.has_translucency = "SubSurface" in outputs
    for ce_map, path in sorted(outputs.items()):
        logger.info("  TIF  %-10s %s" % (ce_map, os.path.basename(path)))

    if rc is not None and settings.get("texture.generate_dds", True):
        jobs = [(tif, _preset_to_stamp(tif, result.diff_has_alpha, alpha_test)) for tif in outputs.values()]
        _, errors = rc.compile_textures(jobs)
        result.errors.extend(errors)
        for ce_map, tif in list(outputs.items()):
            dds = os.path.splitext(tif)[0] + ".dds"
            if os.path.isfile(dds):
                outputs[ce_map] = dds
                if settings.get("texture.delete_tif_after_dds"):
                    try:
                        os.remove(tif)
                    except OSError:
                        pass
    result.files = outputs
    return result


# RC auto-selects these from the file suffix; everything else gets stamped.
_AUTO_PRESET = {"_spec": "Reflectance", "_ddn": "Normals", "_ddna": "NormalsWithSmoothness"}


def _preset_to_stamp(tif, diff_has_alpha, alpha_test):
    preset = preset_for(tif, diff_has_alpha, alpha_test)
    stem = os.path.splitext(os.path.basename(tif))[0].lower()
    for suffix, auto in _AUTO_PRESET.items():
        if stem.endswith(suffix) and preset == auto:
            return None
    if stem.endswith("_diff") and preset == "Albedo":
        return None
    return preset
