# -*- coding: utf-8 -*-
import os, sys
HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
sys.path.insert(0, os.path.join(HERE, "..", "QuixelCEBridge"))
from quixel_ce_bridge.bridge_payload import parse_payload
src = r"E:\Modeling\interior_classic_sofa_chaise_velvet_red_ornate_ybmjefm_raw\ybmjefm.json"
assets = parse_payload(open(src, "rb").read(), os.path.dirname(src))
for a in assets:
    print(a.summary())
    print("safe_base:", a.safe_base, "| workflow:", a.workflow, "| billboard:", a.billboard_textures)
    for k, m in sorted(a.textures.items()):
        print("  %-11s %s" % (k, os.path.basename(m.path)))
    for m in a.meshes:
        print("  mesh", m)
    print("  variations:", a.variations())
