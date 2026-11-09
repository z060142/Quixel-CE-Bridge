# -*- coding: utf-8 -*-
"""CRYENGINE .mtl / .mtl.cryasset writer for Megascans materials.

The converter's .mtl is a generic synthesized multi-material; for Megascans we
know exactly which maps exist and which shader features they need, so the
final material is written here (same attribute conventions as converter /
CRYENGINE's own MaterialHelpers: StringGenMask wins over GenMask on load).
"""
import os
import time
import uuid


def escape(data):
    """Local xml.sax.saxutils.escape equivalent.

    We cannot import xml.sax.saxutils here: its module chain pulls in
    urllib.request -> http.client, and on some engine installs the bundled
    python-future 'common.zip' (Tools/python/packages) sits at sys.path[0],
    whose py2-compat 'http' package raises ImportError on Python 3 and kills
    the whole plugin during startup.
    """
    return data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def quoteattr(data):
    """Local xml.sax.saxutils.quoteattr equivalent (always double-quoted)."""
    return '"%s"' % (escape(data)
                     .replace('"', "&quot;")
                     .replace("\r", "&#13;")
                     .replace("\n", "&#10;")
                     .replace("\t", "&#9;"))

ROOT_MTL_FLAGS = 524544        # MTL_FLAG_MULTI_SUBMTL | MTL_64BIT_SHADERGENMASK
SUB_MTL_FLAGS = 524416         # MTL_FLAG_PURE_CHILD   | MTL_64BIT_SHADERGENMASK
SINGLE_MTL_FLAGS = 524288      # MTL_64BIT_SHADERGENMASK
MTL_FLAG_2SIDED = 0x0002

DEFAULT_TEXMOD = 'TexMod_RotateType="0" TexMod_TexGenType="0" TexMod_bTexGenProjected="0"'

# Texture slot order used by the Material Editor
SLOT_ORDER = ("Diffuse", "Bumpmap", "Specular", "Heightmap", "SubSurface", "Emittance", "Opacity")


class MaterialDef(object):
    """One (sub-)material definition."""

    def __init__(self, name, textures, shader="Illum", surface_type="", alpha_test=0.0,
                 two_sided=False, gen_tokens=None, public_params=None, opacity=1.0,
                 emittance=None):
        self.name = name
        self.textures = dict(textures)        # CE map -> path relative to the .mtl ("./x.dds")
        self.shader = shader
        self.surface_type = surface_type
        self.alpha_test = alpha_test
        self.two_sided = two_sided
        self.gen_tokens = list(gen_tokens or [])
        self.public_params = dict(public_params or {})
        self.opacity = opacity
        self.emittance = emittance or "1,1,1,0"


def _attrs(pairs):
    return " ".join("%s=%s" % (k, quoteattr(str(v))) for k, v in pairs)


def _fmt(value):
    if isinstance(value, float):
        text = ("%.6f" % value).rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def material_xml(mat, flags, indent="  "):
    flags = flags | (MTL_FLAG_2SIDED if mat.two_sided else 0)
    attrs = [
        ("Name", mat.name),
        ("MtlFlags", flags),
        ("Shader", mat.shader),
        ("GenMask", "0"),
        ("StringGenMask", "".join(mat.gen_tokens)),
        ("SurfaceType", mat.surface_type),
        ("MatTemplate", ""),
        ("Diffuse", "1,1,1"),
        ("Specular", "1,1,1"),
        ("Emittance", mat.emittance),
        ("Opacity", _fmt(mat.opacity)),
        ("Shininess", "255"),
        ("vertModifType", "0"),
        ("LayerAct", "1"),
    ]
    if mat.alpha_test:
        attrs.insert(9, ("AlphaTest", _fmt(mat.alpha_test)))
    lines = ["%s<Material %s>" % (indent, _attrs(attrs)), "%s <Textures>" % indent]
    for slot in SLOT_ORDER:
        path = mat.textures.get(slot)
        if not path:
            continue
        lines.append('%s  <Texture Map="%s" File=%s>' % (indent, slot, quoteattr(path)))
        lines.append("%s   <TexMod %s/>" % (indent, DEFAULT_TEXMOD))
        lines.append("%s  </Texture>" % indent)
    lines.append("%s </Textures>" % indent)
    params = {"EmittanceMapGamma": "1", "SSSIndex": "0"}
    params.update({k: _fmt(v) for k, v in mat.public_params.items()})
    lines.append("%s <PublicParams %s/>" % (indent, _attrs(sorted(params.items()))))
    lines.append("%s</Material>" % indent)
    return lines


def write_mtl(path, materials, force_multi=False):
    """materials: [MaterialDef]. One entry -> plain material; several (or
    force_multi, used for meshes so sub-material ids stay stable) -> multi."""
    if len(materials) == 1 and not force_multi:
        lines = material_xml(materials[0], SINGLE_MTL_FLAGS, indent="")
        # A standalone material carries no Name attribute
        lines[0] = lines[0].replace('Name=%s ' % quoteattr(materials[0].name), "", 1)
    else:
        lines = ['<Material MtlFlags="%d" vertModifType="0">' % ROOT_MTL_FLAGS, " <SubMaterials>"]
        for mat in materials:
            lines.extend(material_xml(mat, SUB_MTL_FLAGS, indent="  "))
        lines += [" </SubMaterials>", ' <PublicParams EmittanceMapGamma="1" SSSIndex="0"/>', "</Material>"]
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    write_cryasset(path, materials)
    return path


def write_cryasset(mtl_path, materials):
    """Sidecar metadata the Asset Browser uses (same layout as converter's)."""
    textures = sorted({p for m in materials for p in m.textures.values() if p})
    deps = [p if p.startswith(("./", "../", "%")) else "./" + p for p in textures if p.lower().endswith(".dds")]
    lines = [
        '<AssetMetadata version="0" type="Material" guid="%s" timestamp="%d">' % (uuid.uuid4(), int(time.time())),
        " <Files>",
        "  <File path=%s/>" % quoteattr(os.path.basename(mtl_path)),
        " </Files>",
        " <Details>",
        '  <Detail name="subMaterialCount">%d</Detail>' % (len(materials) if len(materials) > 1 else 0),
        '  <Detail name="textureCount">%d</Detail>' % len(textures),
        " </Details>",
        " <Dependencies>",
    ]
    lines += ['  <Path usageCount="1">%s</Path>' % escape(dep) for dep in deps]
    lines += [" </Dependencies>", "</AssetMetadata>"]
    with open(mtl_path + ".cryasset", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


# ----------------------------------------------------------------------- policy
def build_material(name, texture_set, mtl_dir, settings, kind="3d", has_displacement_pom=False):
    """Turn a processed TextureSet into a MaterialDef.

    kind: 3d / plant / billboard / surface / decal
    """
    rel = {}
    for ce_map, path in texture_set.files.items():
        relative = os.path.relpath(path, mtl_dir).replace("\\", "/")
        if not relative.startswith("."):
            relative = "./" + relative
        # Material always references .dds (CE resolves .tif sources to .dds too)
        rel[ce_map] = os.path.splitext(relative)[0] + ".dds"

    is_plant = kind in ("plant", "billboard")
    shader = settings.get("material.plant_shader" if is_plant else "material.shader", "Illum") or "Illum"
    tokens = []
    if "Bumpmap" in rel:
        tokens.append("%NORMAL_MAP")
    if "Specular" in rel:
        tokens.append("%SPECULAR_MAP")

    params = {}
    alpha_test = 0.0
    two_sided = False
    if texture_set.diff_has_alpha:
        alpha_test = float(settings.get("material.alpha_test", 0.5))
        two_sided = is_plant or kind == "decal"

    if shader.lower() == "vegetation":
        if is_plant:
            tokens.append("%LEAVES")
            if "SubSurface" in rel:
                # Vegetation reads leaf transmittance from the Opacity slot
                rel["Opacity"] = rel.pop("SubSurface")
            params.update({"BackDiffuseMultiplier": 1.0, "TransmittanceColor": "0.5,0.6,0.2"})
    else:
        if "SubSurface" in rel and is_plant:
            tokens.append("%SUBSURFACE_SCATTERING")
        elif "SubSurface" in rel:
            rel.pop("SubSurface")
        if has_displacement_pom and "Heightmap" in rel:
            tokens.append("%PARALLAX_OCCLUSION_MAPPING")
            params["PomDisplacement"] = float(settings.get("material.pom_displacement", 0.025))
            params["HeightBias"] = 1.0
            params["SelfShadowStrength"] = 3.0
        elif "Heightmap" in rel and kind != "surface":
            # Height without POM/tessellation only bloats memory on meshes
            rel.pop("Heightmap")

    return MaterialDef(
        name=name,
        textures=rel,
        shader=shader,
        surface_type=settings.get("material.surface_type", "") or "",
        alpha_test=alpha_test,
        two_sided=two_sided,
        gen_tokens=tokens,
        public_params=params,
    )
