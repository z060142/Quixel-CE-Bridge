# -*- coding: utf-8 -*-
"""Main-thread editor operations (CrythonNative). Only call these from the editor thread."""
from . import logger

try:
    import CrythonNative as cn
except ImportError:  # running outside Sandbox (tests / tools)
    cn = None


def available():
    return cn is not None


def game_folder():
    """Absolute asset directory of the current project ("" when unavailable)."""
    if cn is None:
        logger.warning("CrythonNative is unavailable")
        return ""
    try:
        return cn.system.asset_dir() or ""
    except Exception as error:  # noqa
        logger.warning("asset_dir failed: %s" % error)
        return ""


def spawn_point(distance):
    """Point `distance` metres in front of the editor camera."""
    p = cn.editor.get_point_in_front_of_camera(float(distance))
    return [p.x, p.y, p.z]


def _refresh_assets(result, material):
    """Make freshly written .cryasset files known to the asset browser right away."""
    paths = [material + ".mtl"] if material else []
    paths += [cgf for _display, cgf in result.objects]
    if not paths:
        return
    try:
        cn.asset.refresh(paths)
    except Exception as error:  # noqa
        logger.warning("asset refresh failed: %s" % error)


def apply_result(result, settings):
    """Place the imported asset / assign its material. Returns created names."""
    if cn is None or not result.ok:
        return []
    asset = result.asset
    created = []
    material = result.material_game_path

    _refresh_assets(result, material)

    # One undo step per imported asset.
    with cn.editor.undo_scope("QuixelCEBridge: import %s" % asset.display_name):
        if asset.is_3d:
            if not settings.get("placement.place_in_level", True):
                return []
            try:
                origin = spawn_point(float(settings.get("placement.spawn_distance", 3.0)))
            except Exception as error:  # noqa
                logger.warning("cannot compute spawn point: %s" % error)
                origin = [0.0, 0.0, 0.0]
            spacing = float(settings.get("placement.variation_spacing", 1.5))
            count = len(result.objects)
            objects = []
            for index, (display, cgf) in enumerate(result.objects):
                offset = (index - (count - 1) / 2.0) * spacing
                position = (origin[0] + offset, origin[1], origin[2])
                try:
                    obj = cn.editor.create_brush(cgf, name=display, position=position)
                except Exception as error:  # noqa
                    logger.error("create_brush failed for %s: %s" % (cgf, error))
                    continue
                try:
                    obj.material = material
                except Exception as error:  # noqa
                    logger.warning("set material(%s) failed: %s" % (obj.name, error))
                objects.append(obj)
                created.append(obj.name)
                logger.info("placed %s (%s)" % (obj.name, cgf))
            if objects and settings.get("placement.select_new_objects", True):
                try:
                    cn.editor.select(objects)
                except Exception:  # noqa
                    pass
        else:
            apply_sel = settings.get("placement.apply_surface_to_selection", True) or asset.apply_to_selection
            if apply_sel:
                for obj in cn.editor.get_selection():
                    try:
                        obj.material = material
                        created.append(obj.name)
                    except Exception as error:  # noqa
                        logger.warning("cannot assign material to %s: %s" % (obj.name, error))
                if created:
                    logger.info("material %s assigned to %d selected object(s)" % (material, len(created)))
            if not created:
                logger.info("material ready: %s.mtl (assign it in the Material Editor or select objects first)" % material)
    return created


def message(text):
    try:
        from PySide2.QtWidgets import QMessageBox
        QMessageBox.information(None, "QuixelCEBridge", text)
        return
    except Exception:  # noqa
        pass
    logger.info(text)
