# -*- coding: utf-8 -*-
"""Plugin settings (config.json) with deep-merged defaults."""
import copy
import json
import os
import threading

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PLUGIN_DIR, "config.json")

DEFAULTS = {
    # --- Bridge socket (Quixel Bridge > Export Settings > Custom Socket Export) ---
    "host": "127.0.0.1",
    "port": 24981,
    "auto_start": True,

    # --- Paths (empty = auto-detect) ---
    # Absolute path of the project's asset folder (the folder that contains
    # Objects/, Textures/ ...). Empty -> sandbox.general.get_game_folder().
    "assets_root": "",
    # Sub folder (relative to assets_root) where imported assets are written.
    "output_subdir": "Objects/Megascans",
    "rc_exe": "",          # empty -> <engine>/Tools/rc/rc.exe
    "texproc_exe": "",     # empty -> <plugin>/bin/texproc.exe
    "converter_exe": "",   # empty -> <plugin>/bin/converter.exe

    "texture": {
        # "original" or max edge in px, e.g. "2048"
        "output_resolution": "original",
        # Megascans normal maps are OpenGL (Y+); CRYENGINE expects DirectX (Y-).
        "normal_is_opengl": True,
        # Multiply AO into _diff (CRYENGINE normally relies on SSDO instead).
        "bake_ao_into_diffuse": False,
        # Use the .exr displacement when Bridge exported one next to the jpg.
        "prefer_exr_displacement": False,
        # Compile TIF -> DDS with RC right away (with explicit presets).
        "generate_dds": True,
        "delete_tif_after_dds": False,
        # Parallel RC processes for DDS (0 = auto).
        "rc_parallel": 0,
        # Extra keys merged into the texproc settings JSON (advanced).
        "texproc_settings": {}
    },

    "geometry": {
        # Also convert LOD1..n meshes found in Bridge's lodList as <name>_lodN.cgf
        "import_lods": True,
        # RC physicalize for every sub material: no / default / obstruct / no_collide / proxy_only
        # "no" = no collision but the FULL-resolution mesh survives (RC's 65535
        # vertex cap only applies when physicalizing); "default" = collision,
        # large Raw meshes get truncated to geometry.max_cgf_verts.
        "physicalize": "no",
        # Quixel "Raw" FBX repair: raw vertices above this are truncated to whole
        # polygons (RC caps CGF vertices at 65535 after welding and silently
        # writes an empty mesh when exceeded). 0 disables the repair entirely.
        "max_cgf_verts": 100000,
        # Optional RC request overrides ("" / null = keep converter's values)
        "forward_up_axes": "",
        "unit_size": "",
        "scale": None,
        "merge_all_nodes": False
    },

    "material": {
        "shader": "Illum",
        "plant_shader": "Illum",
        "surface_type": "",
        # Enable POM on surface materials when a displacement map exists.
        "surface_pom": False,
        "pom_displacement": 0.025,
        "alpha_test": 0.5
    },

    "placement": {
        "place_in_level": False,
        # Spawn in front of the camera at this distance (metres).
        "spawn_distance": 3.0,
        # Offset between plant variations.
        "variation_spacing": 1.5,
        # Surfaces: assign the new material to the selected objects.
        "apply_surface_to_selection": True,
        "select_new_objects": True
    },

    # Fab live link: post import status back to the Fab launcher
    # (the payload's metadata.launcher.listening_port, default 24563).
    "fab": {
        "status_callback": True
    },

    # Keep texproc/converter intermediates (groups/settings/request JSON).
    "keep_work_files": False
}

_lock = threading.RLock()


def _deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class Settings(object):
    """Thread-safe settings container. Access with settings.get('a.b')."""

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        with _lock:
            self.data = copy.deepcopy(DEFAULTS)
            if os.path.isfile(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as handle:
                        _deep_merge(self.data, json.load(handle))
                except Exception as error:  # noqa
                    import sys
                    sys.stderr.write("[QuixelCEBridge] failed to read config.json: %s\n" % error)
        return self

    def save(self):
        with _lock:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=4, ensure_ascii=False)

    def get(self, dotted, default=None):
        with _lock:
            node = self.data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def set(self, dotted, value):
        with _lock:
            parts = dotted.split(".")
            node = self.data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value

    def snapshot(self):
        """Deep copy, so a worker thread sees consistent values for one job."""
        with _lock:
            return Settings.from_dict(self.data, self.path)

    @staticmethod
    def from_dict(data, path=CONFIG_PATH):
        settings = Settings.__new__(Settings)
        settings.path = path
        settings.data = _deep_merge(copy.deepcopy(DEFAULTS), copy.deepcopy(data))
        return settings
