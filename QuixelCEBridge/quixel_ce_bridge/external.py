# -*- coding: utf-8 -*-
"""Subprocess wrappers for texproc.exe, converter.exe and rc.exe.

Everything here runs on the worker thread and never touches `sandbox`.
"""
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

from . import logger

CREATE_NO_WINDOW = 0x08000000


class ToolError(RuntimeError):
    pass


class ToolResult(object):
    def __init__(self, args, code, stdout, stderr):
        self.args = args
        self.code = code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self):
        return self.code == 0

    def tail(self, lines=15):
        text = (self.stderr or "") + ("\n" + self.stdout if self.stdout else "")
        return "\n".join(text.strip().splitlines()[-lines:])


def run(args, cwd=None, timeout=None):
    args = [str(a) for a in args]
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            startupinfo=startupinfo,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError:
        raise ToolError("executable not found: %s" % args[0])
    except subprocess.TimeoutExpired:
        raise ToolError("timed out after %ss: %s" % (timeout, " ".join(args)))
    decode = lambda b: (b or b"").decode("utf-8", errors="replace")
    return ToolResult(args, proc.returncode, decode(proc.stdout), decode(proc.stderr))


# --------------------------------------------------------------------- texproc
class Texproc(object):
    """texproc.exe process --groups <json> --settings <json> --out <dir>

    Exit codes: 0 ok, 1 runtime/partial, 2 config, 3 grouping gate.
    """

    def __init__(self, exe):
        if not exe or not os.path.isfile(exe):
            raise ToolError("texproc.exe not found (%s)" % exe)
        self.exe = exe

    def process(self, groups_json, settings_json, out_dir):
        result = run([self.exe, "process", "--groups", groups_json,
                      "--settings", settings_json, "--out", out_dir, "--allow-unknown"],
                     timeout=1800)
        for line in result.stderr.splitlines():
            if line.startswith(("PARTIAL", "FAILED", "warning", "error")):
                logger.warning("texproc: " + line)
        if result.code not in (0, 1):
            raise ToolError("texproc failed (exit %s):\n%s" % (result.code, result.tail()))
        return result


# ------------------------------------------------------------------- converter
class Converter(object):
    """converter.exe convert <fbx> --out-dir <dir> [--manifest m.json]"""

    def __init__(self, exe):
        if not exe or not os.path.isfile(exe):
            raise ToolError("converter.exe not found (%s)" % exe)
        self.exe = exe

    def convert(self, fbx, out_dir, manifest=None, texture_dir=None):
        args = [self.exe, "convert", fbx, "--out-dir", out_dir]
        if manifest:
            args += ["--manifest", manifest]
        if texture_dir:
            args += ["--texture-dir", texture_dir]
        result = run(args, timeout=600)
        if not result.ok:
            raise ToolError("converter failed (exit %s):\n%s" % (result.code, result.tail()))
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise ToolError("converter returned invalid JSON:\n" + result.stdout[:500])

    def dump(self, fbx, out_json):
        result = run([self.exe, "dump", fbx, "--out", out_json], timeout=600)
        if not result.ok:
            raise ToolError("converter dump failed (exit %s):\n%s" % (result.code, result.tail()))
        with open(out_json, "r", encoding="utf-8") as handle:
            return json.load(handle)


# -------------------------------------------------------------------------- rc
# RC only honours the per-file "preset" (stored inside the TIF), so we stamp it
# with /savepreset first and compile afterwards.
PRESET_BY_SUFFIX = (
    ("_ddna", "NormalsWithSmoothness"),
    ("_ddn", "Normals"),
    ("_spec", "Reflectance"),
    ("_displ", "Displacement"),
    ("_sss", "Opacity"),
    ("_trans", "Opacity"),
    ("_opacity", "Opacity"),
    ("_em", "Albedo"),
    ("_emissive", "Albedo"),
)


def preset_for(tif_path, diff_has_alpha=False, alpha_test=True):
    stem = os.path.splitext(os.path.basename(tif_path))[0].lower()
    for suffix, preset in PRESET_BY_SUFFIX:
        if stem.endswith(suffix):
            return preset
    if stem.endswith("_diff"):
        if diff_has_alpha:
            return "AlbedoWithCoverage" if alpha_test else "AlbedoWithOpacity"
        return "Albedo"
    return None


class ResourceCompiler(object):
    def __init__(self, exe, parallel=0):
        if not exe or not os.path.isfile(exe):
            raise ToolError("rc.exe not found (%s). Set rc_exe in config.json." % exe)
        self.exe = exe
        cpu = os.cpu_count() or 4
        self.parallel = parallel if parallel and parallel > 0 else max(1, min(4, cpu // 6 or 1))
        self._lock = threading.Lock()

    def _base_args(self):
        return ["/refresh", "/userdialog=0", "/skipmissing=0"]

    def stamp_preset(self, tif, preset):
        """Embed `preset` into the TIF (in place) so RC uses it on compile."""
        folder = os.path.dirname(tif)
        result = run([self.exe, tif, "/savepreset=%s" % preset, "/userdialog=0"], cwd=folder, timeout=600)
        if not result.ok:
            logger.warning("rc /savepreset=%s failed for %s:\n%s" % (preset, os.path.basename(tif), result.tail(6)))
        return result.ok

    def compile_texture(self, tif, preset=None):
        if preset:
            self.stamp_preset(tif, preset)
        folder = os.path.dirname(tif)
        result = run([self.exe, tif] + self._base_args(), cwd=folder, timeout=1800)
        dds = os.path.splitext(tif)[0] + ".dds"
        if not result.ok or not os.path.isfile(dds):
            raise ToolError("rc failed for %s (exit %s):\n%s" % (os.path.basename(tif), result.code, result.tail()))
        return dds

    def compile_textures(self, jobs):
        """jobs: [(tif, preset)] -> ([dds], [errors])"""
        done, errors = [], []
        if not jobs:
            return done, errors
        with ThreadPoolExecutor(max_workers=self.parallel) as pool:
            futures = [(job, pool.submit(self.compile_texture, job[0], job[1])) for job in jobs]
            for (tif, _), future in futures:
                try:
                    done.append(future.result())
                    logger.info("  DDS  %s" % os.path.basename(tif))
                except Exception as error:  # noqa
                    errors.append(str(error))
                    logger.error(str(error))
        return done, errors

    def compile_fbx_request(self, request_json, source_fbx, cgf_name):
        """RC FBX import: rc <request.json> /overwriteextension=fbx ..."""
        folder = os.path.dirname(request_json)
        args = [self.exe, request_json,
                "/overwriteextension=fbx",
                "/overwritesourcefile=%s" % source_fbx,
                "/overwritefilename=%s" % cgf_name] + self._base_args()
        result = run(args, cwd=folder, timeout=3600)
        cgf = os.path.join(folder, cgf_name)
        if not result.ok or not os.path.isfile(cgf):
            raise ToolError("rc FBX import failed (exit %s) for %s:\n%s" % (result.code, cgf_name, result.tail(25)))
        return cgf
