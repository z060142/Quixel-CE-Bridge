# -*- coding: utf-8 -*-
"""Binary FBX 7.x repair for Quixel Megascans "Raw" mesh exports.

RC silently writes an empty CGF (no MESH chunk) when the source FBX has
either of these two problems, both found while debugging a 500k-vertex
Raw sofa export:

1. A ``Layer`` whose ``LayerElement`` references point at
   ``LayerElementUserData``. Every Quixel Raw FBX carries two UserData
   layers (ByVertice/Direct and ByPolygon/Direct) and no
   ``LayerElementMaterial``; RC's FBX pipeline invalidates the mesh and
   ``BuildMesh`` produces 0 faces -> node saved as NODE_HELPER, exit 0,
   no error message. The fix is to drop the UserData layers, inject a
   ByPolygon ``LayerElementMaterial`` (all faces -> submaterial 0) and
   rebuild one ``Layer`` referencing Normal/Material/UV.

2. More than 65535 vertices after RC's welding. RC caps CGF vertices at
   65535 and above that again writes an empty mesh without complaining
   (the physicalizer only *warns*: "contains too many vertices ... max
   for the physicalizer is 65535"). The fix is to truncate the mesh
   first: only whole polygons whose vertex indices are all below the
   ceiling are kept (measured safe ceiling on the sofa: ~125k raw
   vertices; we default to 100k for margin).

The reader/writer keeps the FBX footer verbatim ("Unexpected file type"
otherwise), writes absolute endOffsets and 25-byte NULL records, and
never re-compresses arrays (encoding 0 is what RC's FBX SDK reads fine).
"""
import struct
import zlib

NULL_LEN = 25  # endOffset u64 + numProps u64 + propLen u64 + nameLen u8
ARR = {0x64: ("arrd", "d", 8), 0x69: ("arri", "i", 4), 0x66: ("arrf", "f", 4),
       0x6C: ("arrl", "q", 8), 0x62: ("arrb", "B", 1)}
ARR_BY_NAME = dict((v[0], (k, v[1], v[2])) for k, v in ARR.items())
SCALAR = {0x59: ("Y", "<h"), 0x43: ("C", None), 0x49: ("I", "<i"), 0x46: ("F", "<f"),
          0x44: ("D", "<d"), 0x4C: ("L", "<q")}


class FBXFormatError(Exception):
    pass


class Node(object):
    __slots__ = ("name", "props", "children")

    def __init__(self, name, props=None, children=None):
        self.name = name
        self.props = props or []      # ("arrd", values) | ("I", 5) | ("S", "x") | ("R", b"..")
        self.children = children or []

    def child(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None


def _decode(buf, p, t):
    if t in ARR:
        count, enc, clen = struct.unpack_from("<III", buf, p)
        p += 12
        tag, fmt, esz = ARR[t]
        if enc == 0:
            data = buf[p:p + count * esz]
            p += count * esz
        else:
            d = zlib.decompressobj()
            data = d.decompress(buf[p:p + clen])[:count * esz]
            p += clen
        return (tag, struct.unpack("<%d%s" % (count, fmt), data)), p
    if t == 0x52:
        n = struct.unpack_from("<I", buf, p)[0]
        return ("R", buf[p + 4:p + 4 + n]), p + 4 + n
    if t == 0x53:
        n = struct.unpack_from("<I", buf, p)[0]
        return ("S", buf[p + 4:p + 4 + n].decode("utf-8", "replace")), p + 4 + n
    tag, fmt = SCALAR[t]
    if fmt is None:
        return (tag, buf[p] != 0), p + 1
    return (tag, struct.unpack_from(fmt, buf, p)[0]), p + 4 + (t in (0x44, 0x4C)) * 4


def _read_node(buf, pos, end):
    eo, np, plen = struct.unpack_from("<QQQ", buf, pos)
    if eo == 0:
        return None, pos + NULL_LEN
    nlen = buf[pos + 24]
    name = buf[pos + 25:pos + 25 + nlen].decode("ascii", "replace")
    p = pos + 25 + nlen
    node = Node(name)
    try:
        for _ in range(np):
            t = buf[p]
            p += 1
            val, p = _decode(buf, p, t)
            node.props.append(val)
        while p < eo - NULL_LEN:
            child, p = _read_node(buf, p, eo - NULL_LEN)
            if child is None:
                break
            node.children.append(child)
    except (struct.error, IndexError, zlib.error):
        raise FBXFormatError("corrupt FBX record near offset %d (%s)" % (pos, name))
    return node, eo


def read_fbx(path):
    with open(path, "rb") as handle:
        buf = handle.read()
    if buf[:20] != b"Kaydara FBX Binary  ":
        raise FBXFormatError("not a binary FBX file: %s" % path)
    ver = struct.unpack_from("<I", buf, 23)[0]
    if ver < 7500:
        raise FBXFormatError("FBX %d is not a 7.x binary layout" % ver)
    root = Node("(root)")
    pos = 27
    footer = b""
    while pos < len(buf):
        if buf[pos:pos + 25] == bytes(25):
            footer = buf[pos + 25:]
            break
        node, pos = _read_node(buf, pos, len(buf))
        if node is None:
            footer = buf[pos:]
            break
        root.children.append(node)
    return root, ver, footer


def _encode(val):
    if isinstance(val, tuple) and len(val) == 2 and val[0] in ARR_BY_NAME:
        t, fmt, esz = ARR_BY_NAME[val[0]]
        data = struct.pack("<%d%s" % (len(val[1]), fmt), *val[1])
        return t, struct.pack("<III", len(val[1]), 0, len(data)) + data
    tag, v = val
    table = {"Y": (0x59, "<h", 2), "I": (0x49, "<i", 4), "F": (0x46, "<f", 4),
             "D": (0x44, "<d", 8), "L": (0x4C, "<q", 8), "C": (0x43, None, 1),
             "S": (0x53, None, None), "R": (0x52, None, None)}
    t, fmt, _ = table[tag]
    if fmt:
        return t, struct.pack(fmt, v)
    if tag == "C":
        return t, bytes([1 if v else 0])
    if tag == "S":
        b = v.encode("utf-8")
        return t, struct.pack("<I", len(b)) + b
    b = v
    return t, struct.pack("<I", len(b)) + b


def _write_node(node, start):
    """FBX endOffset is the absolute file position after this record."""
    name = node.name.encode("ascii", "replace")
    props = b"".join(bytes([t]) + payload for t, payload in (_encode(v) for v in node.props))
    header_len = 25 + len(name) + len(props)
    kids = b""
    pos = start + header_len
    for c in node.children:
        kid = _write_node(c, pos)
        pos += len(kid)
        kids += kid
    if node.children:
        kids += bytes(NULL_LEN)
        pos += NULL_LEN
    return struct.pack("<QQQ", pos, len(node.props), len(props)) + bytes([len(name)]) + name + props + kids


def write_fbx(path, root, footer=b"", version=7700):
    out = bytearray()
    out += b"Kaydara FBX Binary  \x00\x1a\x00"
    out += struct.pack("<I", version)
    pos = 27
    for c in root.children:
        chunk = _write_node(c, pos)
        pos += len(chunk)
        out += chunk
    out += bytes(NULL_LEN)
    out += footer
    with open(path, "wb") as handle:
        handle.write(bytes(out))
    return len(out)


# ---------------------------------------------------------------- geometry ops

def _split_polygons(indices):
    polys, cur = [], []
    for i in indices:
        if i < 0:
            cur.append(-i - 1)
            polys.append(cur)
            cur = []
        else:
            cur.append(i)
    return polys


def _rebuild_pvi(keep):
    pvi = []
    for p in keep:
        pvi.extend(p[:-1])
        pvi.append(-p[-1] - 1)
    return pvi


def _truncate_geom(geom, max_verts):
    """Whole-polygon truncation (all polygon vertices < max_verts are kept)."""
    verts_node = geom.child("Vertices")
    pvi_node = geom.child("PolygonVertexIndex")
    verts = verts_node.props[0][1]
    keep = [p for p in _split_polygons(pvi_node.props[0][1])
            if all(x < max_verts for x in p)]
    new_pvi = _rebuild_pvi(keep)
    verts_node.props[0] = ("arrd", verts[:max_verts * 3])
    pvi_node.props[0] = ("arri", new_pvi)
    n_kept = sum(len(p) for p in keep)
    ln = geom.child("LayerElementNormal")
    if ln is not None and ln.child("Normals") is not None:
        ln.child("Normals").props[0] = ("arrd", ln.child("Normals").props[0][1][:n_kept * 3])
    lu = geom.child("LayerElementUV")
    if lu is not None and lu.child("UVIndex") is not None:
        # keep the full UV table, only the per-polygon-vertex index follows the kept polygons
        lu.child("UVIndex").props[0] = ("arri", new_pvi)
    return max_verts, len(keep), n_kept


def _repair_geom(geom):
    """Drop UserData layers, inject ByPolygon LayerElementMaterial, rebuild Layer."""
    pvi_node = geom.child("PolygonVertexIndex")
    n_polys = sum(1 for i in pvi_node.props[0][1] if i < 0)
    lem = Node("LayerElementMaterial", [("I", 0)], [
        Node("Version", [("I", 101)]),
        Node("Name", [("S", "")]),
        Node("MappingInformationType", [("S", "ByPolygon")]),
        Node("ReferenceInformationType", [("S", "IndexToDirect")]),
        Node("Materials", [("arri", (0,) * n_polys)]),
    ])
    geom.children = [c for c in geom.children if c.name != "LayerElementMaterial"]
    layers = [c for c in geom.children if c.name == "Layer"]
    if layers:
        geom.children.insert(geom.children.index(layers[0]), lem)
    else:
        geom.children.append(lem)
    geom.children = [c for c in geom.children if c.name != "LayerElementUserData"]
    geom.children = [c for c in geom.children if c.name != "Layer"]
    layer = Node("Layer", [("I", 0)], [Node("Version", [("I", 101)])])
    for t in ("LayerElementNormal", "LayerElementMaterial", "LayerElementUV"):
        layer.children.append(Node("LayerElement", [], [
            Node("Type", [("S", t)]), Node("TypedIndex", [("I", 0)])]))
    geom.children.append(layer)
    ln = geom.child("LayerElementNormal")
    if ln is not None:
        # after truncation the per-vertex W array no longer matches; RC does not need it
        ln.children = [c for c in ln.children if c.name != "NormalsW"]


def inspect_geometries(path):
    """[(n_verts, n_polys, n_polyverts, has_userdata, has_material_layer)] per Geometry."""
    root, _ver, _footer = read_fbx(path)
    out = []
    for objs in root.children:
        if objs.name != "Objects":
            continue
        for geom in objs.children:
            if geom.name != "Geometry":
                continue
            verts_node = geom.child("Vertices")
            pvi_node = geom.child("PolygonVertexIndex")
            if verts_node is None or pvi_node is None:
                continue
            pvi = pvi_node.props[0][1]
            out.append((
                len(verts_node.props[0][1]) // 3,
                sum(1 for i in pvi if i < 0),
                len(pvi),
                any(c.name == "LayerElementUserData" for c in geom.children),
                any(c.name == "LayerElementMaterial" for c in geom.children),
            ))
    return out


def fix_fbx(src, dst, max_verts=100000):
    """Repair + truncate. Returns a dict describing what was done, or None
    when the file needed neither repair nor truncation (nothing is written)."""
    root, ver, footer = read_fbx(src)
    objs = None
    for c in root.children:
        if c.name == "Objects":
            objs = c
            break
    result = None
    if objs is None:
        return None
    for geom in objs.children:
        if geom.name != "Geometry":
            continue
        verts_node = geom.child("Vertices")
        pvi_node = geom.child("PolygonVertexIndex")
        if verts_node is None or pvi_node is None:
            continue
        n_verts = len(verts_node.props[0][1]) // 3
        pvi = pvi_node.props[0][1]
        n_polys = sum(1 for i in pvi if i < 0)
        has_userdata = any(c.name == "LayerElementUserData" for c in geom.children)
        has_lem = any(c.name == "LayerElementMaterial" for c in geom.children)
        truncated = False
        stats = (n_verts, n_polys, len(pvi))
        if n_verts > max_verts:
            stats = _truncate_geom(geom, max_verts)
            truncated = True
        if has_userdata or not has_lem or truncated:
            _repair_geom(geom)
            result = {
                "verts": stats[0], "polys": stats[1], "polyverts": stats[2],
                "original_verts": n_verts, "truncated": truncated,
                "dropped_userdata": has_userdata, "injected_material_layer": not has_lem,
            }
    if result is None:
        return None
    write_fbx(dst, root, footer, ver)
    result["out"] = dst
    return result
