# -*- coding: utf-8 -*-
"""QuixelCEBridge - Quixel Bridge -> CRYENGINE 5.7 Sandbox live link.

Package layout
    settings / logger       config + thread-safe logging
    paths                   tool discovery, safe names, game-relative paths
    bridge_payload          Bridge / Fab JSON -> MegascansAsset (mirrors MSPlugin's
                           and Epic's Fab receiver parsers)
    external                subprocess wrappers: texproc.exe, converter.exe, rc.exe
    texture_pipeline        Bridge maps -> texproc groups -> TIF -> RC -> DDS
    geometry_pipeline       FBX -> converter request -> RC -> CGF (+ LODs)
    mtl_writer              CRYENGINE .mtl / .mtl.cryasset writer
    importer                one asset import job (runs on the worker thread)
    scene                   main-thread Sandbox operations (place, assign material)
    server                  Bridge "Custom Socket Export" + Fab live link listener
    controller              queues, worker thread, main-thread pump
    ui                      PySide2 tool panel
"""
VERSION = "1.1.1"
PLUGIN_NAME = "QuixelCEBridge"
