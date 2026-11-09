# -*- coding: utf-8 -*-
"""Main-thread Sandbox operations. Only call these from the editor thread."""
import math
import os

from . import logger
from .sandbox_api import group

try:
    import sandbox  # noqa
except ImportError:  # running outside Sandbox (tests / tools)
    sandbox = None


def _s(value):
    """CE 5.7 sometimes hands back bytes."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _sl(values):
    return [_s(v) for v in (values or [])]


def available():
    return sandbox is not None


def _cvar(general, name):
    """general.get_cvar() raises when the CVar is missing - return "" then."""
    try:
        return _s(general.get_cvar(name)) or ""
    except Exception:  # noqa
        return ""


def _corrected_game_folder(general, game):
    """Fix the engine-relative path returned by general.get_game_folder().

    PyGetGameFolder() (CryEdit.cpp:57) builds PathUtil::Make(GetEnginePath(),
    GetGameFolder()), so the project's assetDirectory is always glued to the
    ENGINE root: with the engine in C:\\cryengine and the project in
    C:\\project1 it returns C:\\cryengine/GameAssets instead of the real
    C:\\project1\\GameAssets.

    The real pieces are available at runtime:
      * sys_game_folder CVar = the .cryproject's assetDirectory, usually a
        relative path ("GameAssets")
      * the engine sets the process working directory to the project root
        while parsing the .cryproject (ProjectManager.cpp:214
        CrySetCurrentWorkingDirectory(m_project.rootDirectory)), so
        os.getcwd() inside Sandbox IS the project root
    """
    rel = _cvar(general, "sys_game_folder")
    if not rel:
        return game
    if os.path.isabs(rel):
        # Some projects fully path their asset directory - trust it as is.
        return rel if os.path.isdir(rel) else game
    # Normal case: relative assetDirectory + cwd (= project root).
    candidate = os.path.abspath(os.path.join(os.getcwd(), rel))
    if os.path.isdir(candidate):
        return candidate
    # Fallback: derive the project root from sys_project (.cryproject path,
    # possibly relative to the engine root) when cwd is not trustworthy.
    proj = _cvar(general, "sys_project")
    if proj:
        if not os.path.isabs(proj) and game.lower().endswith(rel.lower()):
            engine_root = game[: len(game) - len(rel)].rstrip("/\\")
            proj = os.path.join(engine_root, proj)
        candidate = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(proj)), rel))
        if os.path.isdir(candidate):
            return candidate
    return game


def game_folder():
    general = group("general")
    if general is None:
        logger.warning("sandbox.general is unavailable")
        return ""
    try:
        game = _s(general.get_game_folder()) or ""
    except Exception as error:  # noqa
        logger.warning("get_game_folder failed: %s" % error)
        return ""
    if game:
        corrected = _corrected_game_folder(general, game)
        if corrected != game:
            logger.info("assets root %s (project path, engine-reported was %s)" % (corrected, game))
        return corrected
    return ""


def spawn_point(distance):
    """Point `distance` metres in front of the editor camera.

    get_current_view_rotation() returns Ang3 degrees (rotX=pitch, rotY=roll,
    rotZ=yaw). CRYENGINE's SetRotationXYZ matrix maps local forward (0,1,0)
    to (sin yaw*cos pitch, cos yaw*cos pitch, -sin pitch).
    """
    general = group("general")
    pos = general.get_current_view_position()
    rot = general.get_current_view_rotation()
    pitch, yaw = math.radians(rot[0]), math.radians(rot[2])
    forward = (math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), -math.sin(pitch))
    return [pos[i] + forward[i] * distance for i in range(3)]


def _create_brush(cgf, name, position):
    obj = group("general").create_object("Brush", cgf, name,
                                         float(position[0]), float(position[1]), float(position[2]))
    created = _s(getattr(obj, "name", None)) if obj is not None else None
    if created:
        return created
    # Fallback: newest brush using that geometry
    objects = group("object")
    for candidate in reversed(_sl(objects.get_all_objects("Brush", ""))):
        if candidate == name or candidate.startswith(name):
            return candidate
    return None


def apply_result(result, settings):
    """Place the imported asset / assign its material. Returns created names."""
    if sandbox is None or not result.ok:
        return []
    asset = result.asset
    created = []
    material = result.material_game_path

    if asset.is_3d:
        if not settings.get("placement.place_in_level", True):
            return []
        try:
            origin = spawn_point(float(settings.get("placement.spawn_distance", 3.0)))
        except Exception as error:  # noqa
            logger.warning("cannot compute spawn point: %s" % error)
            origin = [0.0, 0.0, 0.0]
        objects = group("object")
        spacing = float(settings.get("placement.variation_spacing", 1.5))
        count = len(result.objects)
        for index, (display, cgf) in enumerate(result.objects):
            offset = (index - (count - 1) / 2.0) * spacing
            position = (origin[0] + offset, origin[1], origin[2])
            try:
                name = _create_brush(cgf, display, position)
            except Exception as error:  # noqa
                logger.error("create_object failed for %s: %s" % (cgf, error))
                continue
            if not name:
                logger.error("could not create brush for %s" % cgf)
                continue
            try:
                objects.set_custom_material(name, material)
            except Exception as error:  # noqa
                logger.warning("set_custom_material(%s) failed: %s" % (name, error))
            created.append(name)
            logger.info("placed %s (%s)" % (name, cgf))
    else:
        apply_sel = settings.get("placement.apply_surface_to_selection", True) or asset.apply_to_selection
        if apply_sel:
            selection = group("selection")
            if selection is None:
                logger.warning("sandbox.selection is unavailable; skipping selection handling")
                selection = []
            else:
                selection = _sl(selection.get_object_names())
            objects = group("object")
            for name in selection:
                try:
                    objects.set_custom_material(name, material)
                    created.append(name)
                except Exception as error:  # noqa
                    logger.warning("cannot assign material to %s: %s" % (name, error))
            if created:
                logger.info("material %s assigned to %d selected object(s)" % (material, len(created)))
        if not created:
            logger.info("material ready: %s.mtl (assign it in the Material Editor or select objects first)" % material)
        return created

    if created and settings.get("placement.select_new_objects", True):
        selection = group("selection")
        if selection is not None:
            try:
                selection.clear()
                selection.select_objects(created)
            except Exception:  # noqa
                pass
    return created


def message(text):
    general = group("general")
    if general is not None:
        try:
            general.message_box_ok(text)
            return
        except Exception:  # noqa
            pass
    logger.info(text)
