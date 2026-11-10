# -*- coding: utf-8 -*-
"""Glue between socket thread, worker thread and the editor main thread.

    Bridge --TCP--> BridgeServer thread --payload--> _incoming queue
    main thread pump (QTimer) : resolve runtime paths, parse, enqueue jobs
    worker thread             : importer.import_asset() (texproc/converter/rc)
    main thread pump          : scene.apply_result() (create brushes, materials)

`sandbox.*` is only ever touched from pump(), i.e. the main thread.
"""
import json
import os
import queue
import shutil
import socket
import tempfile
import threading
import traceback
import zipfile

from . import VERSION, logger, scene
from .bridge_payload import parse_payload
from .importer import import_asset, stage_base, sweep_work_dirs
from .paths import find_bundled, find_rc
from .server import BridgeServer, split_json_documents
from .settings import PLUGIN_DIR, Settings


def _s_str(path):
    """Sandbox may hand back bytes paths."""
    if isinstance(path, bytes):
        return path.decode("utf-8", errors="replace")
    return path


class Controller(object):
    def __init__(self):
        self.settings = Settings()
        self.server = None
        self._incoming = queue.Queue()
        self._jobs = queue.Queue()
        self._results = queue.Queue()
        self._worker = None
        self._timer = None
        self._busy = threading.Event()
        self.status = "idle"
        self.history = []          # [ImportResult]
        self.listeners = []        # callables(event, data) for the UI (main thread)
        self._zip_refs = {}        # temp zip dir -> assets still importing
        self._swept = False         # leftover work folders swept once

    # ----------------------------------------------------------------- runtime
    def runtime_settings(self):
        """Snapshot settings + resolved tool paths (main thread)."""
        snap = self.settings.snapshot()
        snap.set("_runtime.rc_exe", find_rc(snap.get("rc_exe")))
        snap.set("_runtime.texproc_exe", find_bundled(snap.get("texproc_exe"), "texproc.exe"))
        snap.set("_runtime.converter_exe", find_bundled(snap.get("converter_exe"), "converter.exe"))
        root = snap.get("assets_root") or scene.game_folder()
        snap.set("_runtime.assets_root", os.path.abspath(root) if root else "")
        if not self._swept:
            self._swept = True
            sweep_work_dirs(snap, snap.get("_runtime.assets_root"))
        return snap

    def diagnostics(self):
        snap = self.runtime_settings()
        return {
            "rc.exe": snap.get("_runtime.rc_exe") or "NOT FOUND",
            "texproc.exe": snap.get("_runtime.texproc_exe") or "NOT FOUND",
            "converter.exe": snap.get("_runtime.converter_exe") or "NOT FOUND",
            "assets root": snap.get("_runtime.assets_root") or "NOT FOUND",
            "output": os.path.join(snap.get("_runtime.assets_root") or "?", snap.get("output_subdir")),
            "staging": stage_base(snap, snap.get("_runtime.assets_root")) or "(system temp)",
            "listening": ("%s:%s" % (snap.get("host"), snap.get("port")) if self.listening else "no") +
                         ((" (+ %s for Fab)" % snap.get("fab_port")) if self.listening and snap.get("fab_port") else ""),
        }

    # ------------------------------------------------------------------ server
    @property
    def listening(self):
        return bool(self.server and self.server.running)

    def start_server(self):
        self.stop_server()
        self.server = BridgeServer(self.settings.get("host"), self.settings.get("port"),
                                   self._incoming.put, plugin_version=VERSION,
                                   fab_port=self.settings.get("fab_port"))
        ok = self.server.start()
        self._notify("server", ok)
        return ok

    def stop_server(self):
        if self.server:
            self.server.stop()
            self.server = None
            logger.info("listener stopped")
        self._notify("server", False)

    # ------------------------------------------------------------------ worker
    def _ensure_worker(self):
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_loop, name="qceb-worker", daemon=True)
        self._worker.start()

    def _worker_loop(self):
        while True:
            job = self._jobs.get()
            if job is None:
                break
            asset, snap = job
            self._busy.set()
            self.status = "importing %s" % asset.display_name
            try:
                result = import_asset(asset, snap, snap.get("_runtime.assets_root"),
                                      progress=lambda text: setattr(self, "status", text))
            except Exception:  # noqa  (import_asset already guards; belt and braces)
                logger.error(traceback.format_exc())
                self._release_zip(asset)
                continue
            finally:
                self._busy.clear()
            self._results.put((result, snap))
            self.status = "idle" if self._jobs.empty() else "queued: %d" % self._jobs.qsize()

    @property
    def pending(self):
        return self._jobs.qsize() + (1 if self._busy.is_set() else 0)

    # -------------------------------------------------------------- submission
    def submit_payload(self, payload, base_folder=None):
        """Main thread: parse and queue a Bridge payload (bytes/str/list)."""
        try:
            raw = payload
            if isinstance(payload, (bytes, bytearray)):
                text = payload.decode("utf-8-sig", errors="replace")
            elif isinstance(payload, str):
                text = payload
            else:
                raw = text = None
            if text is not None:
                self._dump_payload(raw if isinstance(raw, (bytes, bytearray)) else text.encode("utf-8"))
                docs = split_json_documents(text)
                assets = []
                for doc in docs:
                    assets.extend(parse_payload(doc, base_folder))
            else:
                assets = parse_payload(payload, base_folder)
        except Exception as error:  # noqa
            logger.error("invalid Bridge payload: %s" % error)
            return 0
        for asset in assets:
            if not asset.textures and not asset.meshes and not asset.billboard_textures:
                keys = ", ".join(sorted(asset.raw.keys()))[:200] if isinstance(asset.raw, dict) else "?"
                logger.warning("asset %s carries no maps and no meshes; payload keys: %s" % (asset.id, keys))
        if not assets:
            logger.warning("Bridge payload contained no assets")
            return 0
        return self._queue_assets(assets)

    def _queue_assets(self, assets):
        """Main thread: enqueue parsed assets (shared by payloads, files and zips)."""
        snap = self.runtime_settings()
        if not snap.get("_runtime.assets_root"):
            logger.error("cannot resolve the project's assets folder; set assets_root in config.json")
            return 0
        if not snap.get("_runtime.texproc_exe"):
            logger.error("texproc.exe missing from %s" % os.path.join("QuixelCEBridge", "bin"))
            return 0
        self._ensure_worker()
        for asset in assets:
            logger.info("queued %s" % asset.summary())
            self._jobs.put((asset, snap))
        self._notify("queued", len(assets))
        return len(assets)

    @staticmethod
    def _dump_payload(raw):
        """Keep the last raw payload for diagnosis."""
        try:
            with open(os.path.join(PLUGIN_DIR, "last_payload.json"), "wb") as handle:
                handle.write(raw)
        except OSError:
            pass

    def submit_file(self, path):
        """Main thread: import a Bridge export JSON, or a Quixel .zip download."""
        path = _s_str(path)
        if path.lower().endswith(".zip"):
            return self._submit_zip(path)
        with open(path, "rb") as handle:
            return self.submit_payload(handle.read(), os.path.dirname(os.path.abspath(path)))

    def _submit_zip(self, zip_path):
        """Main thread: extract a Quixel .zip download and queue what it contains.

        Quixel zips (as downloaded from bridge / web) are flat: one .fbx, the
        map .jpg/.png files and a metadata <id>.json right next to them - so
        we extract to a temp folder and submit the JSON(s) found inside with
        that folder as base. The temp folder is removed once every asset that
        came from it has finished (unless keep_work_files is set).
        """
        if not os.path.isfile(zip_path):
            logger.error("zip not found: %s" % zip_path)
            return 0
        try:
            archive = zipfile.ZipFile(zip_path)
        except (zipfile.BadZipFile, OSError) as error:
            logger.error("cannot open zip %s: %s" % (zip_path, error))
            return 0
        out_dir = tempfile.mkdtemp(prefix="qceb_zip_")
        try:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                # zip-slip guard: members must resolve inside out_dir
                target = os.path.normpath(os.path.join(out_dir, info.filename))
                if not target.startswith(out_dir + os.sep):
                    logger.warning("skipping unsafe zip entry %r" % info.filename)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        except Exception as error:  # noqa
            logger.error("extracting %s failed: %s" % (zip_path, error))
            shutil.rmtree(out_dir, ignore_errors=True)
            return 0
        finally:
            archive.close()
        assets = []
        for root, _dirs, files in os.walk(out_dir):
            for name in sorted(files):
                if not name.lower().endswith(".json"):
                    continue
                json_path = os.path.join(root, name)
                try:
                    with open(json_path, "rb") as handle:
                        docs = split_json_documents(handle.read().decode("utf-8-sig", errors="replace"))
                    for doc in docs:
                        assets.extend(parse_payload(doc, base_folder=root))
                except Exception as error:  # noqa
                    logger.warning("skipping %s inside zip (%s)" % (name, error))
        if not assets:
            logger.error("no Bridge asset JSON found inside %s" % zip_path)
            shutil.rmtree(out_dir, ignore_errors=True)
            return 0
        for asset in assets:
            asset._zip_tmp = out_dir
        self._zip_refs[out_dir] = len(assets)
        logger.info("unpacked %s (%d assets)" % (os.path.basename(zip_path), len(assets)))
        return self._queue_assets(assets)

    def _release_zip(self, asset):
        """Main/worker thread: drop one asset's reference to its zip temp dir."""
        out_dir = getattr(asset, "_zip_tmp", None)
        if not out_dir or out_dir not in self._zip_refs:
            return
        self._zip_refs[out_dir] -= 1
        if self._zip_refs[out_dir] > 0:
            return
        del self._zip_refs[out_dir]
        if not self.settings.get("keep_work_files"):
            shutil.rmtree(out_dir, ignore_errors=True)
            logger.info("removed temp %s" % out_dir)

    # ---------------------------------------------------------- main-thread pump
    def pump(self):
        """Called periodically on the main thread (QTimer) or manually."""
        try:
            while True:
                try:
                    payload = self._incoming.get_nowait()
                except queue.Empty:
                    break
                logger.info("received %d bytes from Bridge" % len(payload))
                self.submit_payload(payload)
            while True:
                try:
                    result, snap = self._results.get_nowait()
                except queue.Empty:
                    break
                self._finish(result, snap)
        except Exception:  # noqa
            logger.error("pump failed:\n" + traceback.format_exc())

    def _finish(self, result, snap):
        self.history.append(result)
        self._release_zip(result.asset)
        del self.history[:-50]
        for warning in result.warnings:
            logger.warning("%s: %s" % (result.asset.display_name, warning))
        if not result.ok:
            logger.error("FAILED %s (%.1fs): %s" % (result.asset.display_name, result.seconds, "; ".join(result.errors)))
            self._fab_report(result)
            self._notify("result", result)
            return
        try:
            created = scene.apply_result(result, snap)
        except Exception:  # noqa
            logger.error("placing %s failed:\n%s" % (result.asset.display_name, traceback.format_exc()))
            created = []
        logger.info("DONE %s in %.1fs -> %s%s" % (
            result.asset.display_name, result.seconds, result.material_game_path,
            (" | objects: " + ", ".join(created)) if created else ""))
        self._fab_report(result)
        self._notify("result", result)

    # -------------------------------------------------------------- Fab reports
    def _fab_report(self, result):
        """Best-effort status report back to the Fab launcher.

        Fab payloads carry metadata.launcher.listening_port; Epic's own DCC
        plugins post {status, message, id, path, app_name, ...} + NUL there so
        the launcher can show import feedback. Errors are sent as "critical"
        (the launcher's historical convention). Nothing happens when the
        launcher is not listening (e.g. plain Bridge / file imports).
        """
        callback = getattr(result.asset, "fab_callback", None)
        if not callback or not self.settings.get("fab.status_callback", True):
            return
        if result.ok:
            status = "warning" if result.warnings else "success"
            if result.objects:
                message = "imported %d object(s), material %s" % (
                    len(result.objects), os.path.basename(result.material_game_path or "") or "n/a")
            else:
                message = "imported material %s" % (os.path.basename(result.material_game_path or "") or "n/a")
        else:
            status = "critical"
            message = ("; ".join(result.errors) or "import failed")[:400]
        try:
            data = json.dumps({
                "status": status,
                "message": message,
                "id": callback.get("id", ""),
                "path": callback.get("path", ""),
                "app_name": "cryengine",
                "app_version": "5.7",
                "plugin_version": VERSION,
                "renderer": "Sandbox",
            }) + "\0"
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                sock.connect(("127.0.0.1", int(callback.get("port") or 24563)))
                sock.sendall(data.encode("utf-8"))
        except (OSError, ValueError):
            pass   # launcher not listening: fine outside the Fab app

    def start_pump(self):
        """Install a QTimer on the main thread. Returns True on success."""
        try:
            from PySide2.QtCore import QTimer
        except ImportError:
            logger.warning("PySide2 unavailable: run 'QuixelCEBridge: Process pending' to finish imports")
            return False
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setInterval(250)
            self._timer.timeout.connect(self.pump)
        self._timer.start()
        return True

    # --------------------------------------------------------------- listeners
    def _notify(self, event, data):
        for callback in list(self.listeners):
            try:
                callback(event, data)
            except Exception:  # noqa
                pass


_instance = None


def get():
    global _instance
    if _instance is None:
        _instance = Controller()
    return _instance
