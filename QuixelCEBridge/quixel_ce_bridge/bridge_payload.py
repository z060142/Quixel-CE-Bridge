# -*- coding: utf-8 -*-
"""Parse Quixel Bridge exports into MegascansAsset objects.

Two payload shapes are understood:

1. Bridge "Custom Socket Export" (MSPlugin style): a JSON array, one object
   per asset, with `components` (texture maps with absolute `path`s),
   `components-billboard`, `meshList` and `lodList`.

2. A Megascans library metadata JSON (version 2, e.g. `ybmjefm.json` next to
   a "raw" export folder): `maps` / `models` with library-relative `uri`s,
   while the actually exported files (e.g. `<Asset>_Raw_8K_BaseColor.jpg`,
   `<Asset>_Raw.fbx`) sit next to the JSON. Maps and meshes are resolved
   from `uri` when the file exists, otherwise by scanning the folder.
"""
import json
import os
import re

from .paths import safe_name

MESH_FORMATS = ("fbx",)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".tga", ".bmp", ".psd")

# metadata `maps[].type` / filename keyword -> internal map key
METADATA_TYPE_ALIASES = {
    "basecolor": "albedo", "base_color": "albedo", "albedo": "albedo", "diffuse": "albedo",
    "normal": "normal", "bump": "bump",
    "roughness": "roughness", "rough": "roughness", "gloss": "gloss", "glossiness": "gloss",
    "specular": "specular", "spec": "specular",
    "metalness": "metalness", "metallic": "metalness", "metal": "metalness",
    "ao": "ao", "cavity": "cavity",
    "displacement": "displacement", "height": "displacement", "heightmap": "displacement",
    "opacity": "opacity", "alpha": "opacity", "mask": "opacity",
    "translucency": "translucency", "transmission": "translucency", "transmittance": "translucency",
    "sss": "translucency", "subsurface": "translucency",
    "emissive": "emissive", "emission": "emissive",
    "fuzz": "fuzz", "shell": "shellmap", "shellmap": "shellmap",
}

TYPE_BY_ASSET_TYPE = {
    "3d asset": "3d", "3d": "3d", "assembly": "3d",
    "plant": "3dplant", "3d plant": "3dplant", "3dplant": "3dplant",
    "surface": "surface", "surface scan": "surface",
    "atlas": "atlas", "decal": "decal", "brush": "brush", "displacement": "displacement",
}


class TextureMap(object):
    __slots__ = ("type", "path", "format", "name")

    def __init__(self, type_, path, format_, name):
        self.type = type_
        self.path = path
        self.format = format_
        self.name = name

    def __repr__(self):
        return "TextureMap(%s, %s)" % (self.type, os.path.basename(self.path))


class MeshEntry(object):
    __slots__ = ("path", "format", "lod", "variation", "is_billboard")

    def __init__(self, path, format_, lod, variation, is_billboard=False):
        self.path = path
        self.format = format_
        self.lod = lod                # int (0..n) or None
        self.variation = variation    # int >= 1
        self.is_billboard = is_billboard

    def __repr__(self):
        return "MeshEntry(var=%s, lod=%s, %s)" % (self.variation, self.lod, os.path.basename(self.path))


def _lod_index(value):
    """'lod3' / 'LOD3' / 3 / 'high' -> 3 / None."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"(\d+)", str(value))
    return int(match.group(1)) if match else None


def _variation_from_name(path):
    match = re.search(r"var(?:iation)?[ _-]?(\d+)", os.path.basename(path), re.I)
    return int(match.group(1)) if match else None


def _lod_from_name(path):
    match = re.search(r"lod[ _-]?(\d+)", os.path.basename(path), re.I)
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------------
# filename helpers (new-style raw export folders: <Asset>_Raw[_<N>K]_<Map>.jpg)
# --------------------------------------------------------------------------

def _tokens(filename):
    stem = os.path.splitext(os.path.basename(filename))[0]
    return [t for t in re.split(r"[\s_\-]+", stem.lower()) if t]


def _resolution_from_tokens(tokens):
    for token in tokens:
        if re.fullmatch(r"\d+k", token):
            return int(token[:-1]) * 1024
        if re.fullmatch(r"\d{3,5}", token) and 128 <= int(token) <= 16384:
            return int(token)
    return 0


def _classify_image(filename):
    """(map key, resolution) for a raw-export texture filename, or None."""
    tokens = _tokens(filename)
    for token in reversed(tokens[-4:]):        # map keyword is near the end of the name
        if token in ("lod", "k", "raw"):
            continue
        key = METADATA_TYPE_ALIASES.get(token)
        if key:
            return key, _resolution_from_tokens(tokens)
    return None


def _classify_mesh(filename):
    """(lod or None, variation or None, is_billboard) for a mesh filename."""
    low = os.path.basename(filename).lower()
    return _lod_from_name(filename), _variation_from_name(filename), "billboard" in low


# --------------------------------------------------------------------------
# asset
# --------------------------------------------------------------------------

class MegascansAsset(object):
    """One asset from a Bridge payload or metadata JSON."""

    def __init__(self, data):
        self.raw = data
        self.id = str(data.get("id", "")).strip() or "noid"
        self.type = str(data.get("type", "")).lower()
        self.path = data.get("path", "")
        self.category = data.get("category", "")
        self.categories = [str(c).lower() for c in data.get("categories", []) or []]
        self.tags = [str(t).lower() for t in data.get("tags", []) or []]
        self.active_lod_raw = str(data.get("activeLOD", "") or "")
        self.min_lod_raw = str(data.get("minLOD", "") or "")
        self.is_high_poly = self.active_lod_raw.lower() == "high"
        self.active_lod = _lod_index(self.active_lod_raw)
        self.min_lod = _lod_index(self.min_lod_raw)
        self.workflow = str(data.get("workflow", data.get("pbrWorkflow", "specular")) or "specular").lower()
        self.is_metal = str(data.get("category", "")).lower() == "metal"
        self.apply_to_selection = bool(data.get("applyToSelection", False))
        self.meta = {m.get("key"): m.get("value") for m in data.get("meta", []) or [] if isinstance(m, dict)}

        name = data.get("name") or os.path.basename(self.path or "") or self.id
        self.display_name = name
        name = name.replace(" ", "_")
        if len(name.split("_")) > 2:
            name = "_".join(name.split("_")[:-1])
        self.safe_base = safe_name("%s_%s" % (name, self.id))

        self.textures = self._parse_textures(data.get("components", []) or [])
        self.billboard_textures = self._parse_textures(data.get("components-billboard", []) or [])
        self.meshes = self._parse_meshes(data)

    # ------------------------------------------------------------------ textures
    def _parse_textures(self, components):
        by_type = {}
        for comp in components:
            if not isinstance(comp, dict):
                continue
            ttype = str(comp.get("type", "")).lower()
            path = comp.get("path", "")
            if not ttype or not path:
                continue
            fmt = str(comp.get("format", os.path.splitext(path)[1].lstrip("."))).lower()
            by_type.setdefault(ttype, []).append(TextureMap(ttype, path, fmt, comp.get("name", "")))

        textures = {}
        for ttype, items in by_type.items():
            textures[ttype] = self._pick_for_lod(items)
        if "albedo" not in textures and "diffuse" in textures:
            textures["albedo"] = textures.pop("diffuse")
        return textures

    def _pick_for_lod(self, items):
        """Per-LOD maps (e.g. Normal_LOD2): prefer the one for the active LOD."""
        if len(items) == 1 or self.active_lod is None:
            return items[0]
        for item in items:
            if _lod_from_name(item.path) == self.active_lod:
                return item
        plain = [i for i in items if _lod_from_name(i.path) is None]
        return plain[0] if plain else items[0]

    # -------------------------------------------------------------------- meshes
    def _parse_meshes(self, data):
        meshes = []
        lod_list = data.get("lodList", []) or []
        mesh_list = data.get("meshList", []) or []

        for item in mesh_list:
            path = item.get("path", "")
            fmt = str(item.get("format", os.path.splitext(path)[1].lstrip("."))).lower()
            if not path:
                continue
            variation = _lod_index(item.get("variation")) or _variation_from_name(path)
            lod = None if self.is_high_poly else (_lod_from_name(path) if _lod_from_name(path) is not None else self.active_lod)
            meshes.append(MeshEntry(path, fmt, lod, variation))

        for item in lod_list:
            path = item.get("path", "")
            if not path:
                continue
            fmt = str(item.get("format", os.path.splitext(path)[1].lstrip("."))).lower()
            lod = _lod_index(item.get("lod"))
            if lod is None:
                lod = _lod_from_name(path)
            variation = _lod_index(item.get("variation")) or _variation_from_name(path)
            meshes.append(MeshEntry(path, fmt, lod, variation))

        seen, unique = set(), []
        for mesh in meshes:
            key = os.path.normcase(os.path.abspath(mesh.path))
            if key not in seen:
                seen.add(key)
                unique.append(mesh)

        unknown = [m for m in unique if m.variation is None]
        if unknown:
            lods = set(m.lod for m in unknown)
            if len(unknown) > 1 and len(lods) == 1:
                for index, mesh in enumerate(unknown, 1):
                    mesh.variation = index
            else:
                for mesh in unknown:
                    mesh.variation = 1

        if self.is_plant and self.min_lod is not None:
            for mesh in unique:
                mesh.is_billboard = mesh.lod is not None and mesh.lod >= self.min_lod and bool(self.billboard_textures)
        return unique

    # ------------------------------------------------------------------- queries
    @property
    def is_plant(self):
        return self.type == "3dplant"

    @property
    def is_3d(self):
        return self.type in ("3d", "3dplant")

    @property
    def is_surface_like(self):
        return not self.is_3d

    @property
    def is_scatter(self):
        keys = set(self.categories) | set(self.tags)
        return bool(keys & {"scatter", "cmb_asset"})

    @property
    def has_opacity(self):
        return "opacity" in self.textures

    def variations(self, include_lods=True):
        """{variation: [MeshEntry sorted by LOD]} limited to supported formats."""
        result = {}
        for mesh in self.meshes:
            if mesh.format not in MESH_FORMATS:
                continue
            result.setdefault(mesh.variation, []).append(mesh)
        for variation, items in list(result.items()):
            if self.is_high_poly:
                items = [m for m in items if m.lod is None] or items[:1]
            else:
                base = self.active_lod if self.active_lod is not None else 0
                items = [m for m in items if m.lod is None or m.lod >= base]
                items.sort(key=lambda m: (m.lod is None, m.lod if m.lod is not None else 0))
                if not include_lods:
                    items = items[:1]
            result[variation] = items
        return dict(sorted(result.items()))

    def unsupported_meshes(self):
        return [m for m in self.meshes if m.format not in MESH_FORMATS]

    def summary(self):
        return "%s [%s] id=%s maps=%s meshes=%d" % (
            self.display_name, self.type, self.id, ",".join(sorted(self.textures)), len(self.meshes))


# --------------------------------------------------------------------------
# metadata (version 2) assets
# --------------------------------------------------------------------------

def _is_metadata(item):
    return isinstance(item.get("maps"), list) and "id" in item and not item.get("components")


def _keep_best(store, key, tmap, resolution, lod_variant=False):
    previous = store.get(key)
    rank = resolution - (1000000 if lod_variant else 0)
    if previous is None or rank >= previous[0]:
        store[key] = (rank, tmap)


def _metadata_asset_type(item, tags_info):
    atype = str(tags_info.get("asset_type", "")).lower().strip()
    if atype in TYPE_BY_ASSET_TYPE:
        return TYPE_BY_ASSET_TYPE[atype]
    categories = [str(c).lower() for c in item.get("categories", []) or []]
    for cat in categories:
        if cat in ("3d", "3dplant", "surface", "atlas", "decal", "brush", "displacement"):
            return cat
    asset_cats = " ".join(str(k).lower() for k in (item.get("assetCategories") or {}))
    if "plant" in asset_cats:
        return "3dplant"
    if "3d" in asset_cats:
        return "3d"
    if "surface" in asset_cats:
        return "surface"
    return "3d" if item.get("models") else "surface"


def _textures_from_maps(maps, base_folder, store):
    """Resolve metadata `maps[].uri` against the export folder."""
    for entry in maps:
        if not isinstance(entry, dict):
            continue
        key = METADATA_TYPE_ALIASES.get(str(entry.get("type", "")).lower())
        uri = str(entry.get("uri", "")).replace("\\", "/")
        path = os.path.join(base_folder, uri) if (uri and base_folder) else ""
        if not key or not path or not os.path.isfile(path):
            continue
        match = re.match(r"(\d+)\s*x", str(entry.get("resolution", "")))
        resolution = int(match.group(1)) if match else 0
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        tmap = TextureMap(key, path, ext, os.path.basename(path))
        _keep_best(store, key, tmap, resolution, lod_variant=str(entry.get("lodType", "")).lower() == "lod")


def _scan_export_folder(base_folder, textures, billboards, meshes):
    """Collect the exported files that sit next to the JSON."""
    folders = [base_folder]
    for sub in ("textures", "maps"):
        candidate = os.path.join(base_folder, sub)
        if os.path.isdir(candidate):
            folders.append(candidate)
    for folder in folders:
        try:
            entries = os.listdir(folder)
        except OSError:
            continue
        for entry in entries:
            path = os.path.join(folder, entry)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(entry)[1].lower()
            low = entry.lower()
            if ext.lstrip(".") in MESH_FORMATS:
                if "layout" in low or "preview" in low:
                    continue
                lod, variation, is_bb = _classify_mesh(entry)
                meshes.append(MeshEntry(path, ext.lstrip("."), lod, variation or 1, is_bb))
            elif ext in IMAGE_EXTS and "preview" not in low and "thumb" not in low:
                info = _classify_image(entry)
                if not info:
                    continue
                key, resolution = info
                tmap = TextureMap(key, path, ext.lstrip("."), entry)
                _keep_best(billboards if "billboard" in low else textures, key, tmap, resolution,
                           lod_variant=_lod_from_name(entry) is not None)


def _meshes_from_models(models, base_folder):
    out = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("type", "")).lower() in ("layout", "preview"):
            continue
        uri = str(entry.get("uri", "")).replace("\\", "/")
        path = os.path.join(base_folder, uri) if (uri and base_folder) else ""
        if not path or not os.path.isfile(path):
            continue
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if ext not in MESH_FORMATS:
            continue
        tier = entry.get("tier")
        lod = tier if isinstance(tier, int) else _lod_from_name(path)
        low = path.lower()
        out.append(MeshEntry(path, ext, lod, _variation_from_name(path) or 1, "billboard" in low))
    return out


def _asset_from_metadata(item, base_folder):
    asset = MegascansAsset.__new__(MegascansAsset)
    asset.raw = item
    tags_info = item.get("semanticTags") or {}
    name_formats = tags_info.get("name_formats") or {}

    asset.id = str(item.get("id", "")).strip() or "noid"
    name = tags_info.get("name") or name_formats.get("title") or name_formats.get("file") or asset.id
    asset.display_name = name
    token = name.replace(" ", "_")
    if len(token.split("_")) > 2:
        token = "_".join(token.split("_")[:-1])
    asset.safe_base = safe_name("%s_%s" % (token, asset.id))

    asset.type = _metadata_asset_type(item, tags_info)
    asset.path = base_folder or ""
    categories = [str(c).lower() for c in item.get("categories", []) or []]
    asset.category = categories[0] if categories else ""
    asset.categories = categories
    asset.tags = [str(t).lower() for t in item.get("tags", []) or []]
    asset.active_lod_raw = asset.min_lod_raw = ""
    asset.active_lod = asset.min_lod = None
    asset.is_high_poly = False
    asset.is_metal = "metal" in categories
    asset.apply_to_selection = False
    asset.meta = {m.get("key"): m.get("value") for m in item.get("meta", []) or [] if isinstance(m, dict)}

    textures, billboards, meshes = {}, {}, []
    if base_folder and os.path.isdir(base_folder):
        _scan_export_folder(base_folder, textures, billboards, meshes)
        _textures_from_maps(item.get("maps", []) or [], base_folder, textures)
        meshes = _meshes_from_models(item.get("models", []) or [], base_folder) + meshes

    seen, unique = set(), []
    for mesh in meshes:
        key = os.path.normcase(os.path.abspath(mesh.path))
        if key not in seen:
            seen.add(key)
            unique.append(mesh)
    asset.meshes = unique
    asset.textures = {key: value[1] for key, value in textures.items()}
    asset.billboard_textures = {key: value[1] for key, value in billboards.items()}
    asset.workflow = "metalness" if "metalness" in asset.textures else "specular"
    return asset


def parse_payload(payload, base_folder=None):
    """bytes/str/list/dict -> [MegascansAsset].

    `base_folder` enables file resolution for metadata-style JSONs (the folder
    that contains the JSON and the exported files).
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8-sig", errors="replace")
    if isinstance(payload, str):
        payload = payload.strip().lstrip("﻿")
        if not payload:
            return []
        payload = json.loads(payload)
    if isinstance(payload, dict):
        for key in ("assets", "items", "data"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    assets = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if _is_metadata(item):
            assets.append(_asset_from_metadata(item, base_folder))
        else:
            assets.append(MegascansAsset(item))
    return assets
