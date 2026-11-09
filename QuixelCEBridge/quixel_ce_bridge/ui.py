# -*- coding: utf-8 -*-
"""PySide2 tool panel (Tools > Megascans > Quixel CE Bridge)."""
import os

from PySide2 import QtCore, QtWidgets

from . import PLUGIN_NAME, VERSION, logger
from . import controller as controller_module

RESOLUTIONS = ["original", "8192", "4096", "2048", "1024", "512"]
PHYSICALIZE = ["default", "no_collide", "obstruct", "no", "proxy_only"]
SHADERS = ["Illum", "Vegetation"]


class BridgePanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(BridgePanel, self).__init__(parent)
        self.ctrl = controller_module.get()
        self._log_seq = 0
        self.setWindowTitle("%s %s" % (PLUGIN_NAME, VERSION))
        self._build()
        self._load()
        self.ctrl.listeners.append(self._on_event)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(300)
        self._refresh_diag()

    # ----------------------------------------------------------------- layout
    def _build(self):
        root = QtWidgets.QVBoxLayout(self)

        # status row
        row = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel()
        self.btn_listen = QtWidgets.QPushButton()
        self.btn_listen.clicked.connect(self._toggle_listen)
        row.addWidget(self.status, 1)
        row.addWidget(self.btn_listen)
        root.addLayout(row)

        # settings
        box = QtWidgets.QGroupBox("Settings")
        form = QtWidgets.QFormLayout(box)
        self.port = QtWidgets.QSpinBox()
        self.port.setRange(1024, 65535)
        self.assets_root = QtWidgets.QLineEdit()
        self.assets_root.setPlaceholderText("auto: sandbox.general.get_game_folder()")
        browse = QtWidgets.QPushButton("...")
        browse.setFixedWidth(28)
        browse.clicked.connect(self._browse_root)
        root_row = QtWidgets.QHBoxLayout()
        root_row.addWidget(self.assets_root)
        root_row.addWidget(browse)
        self.subdir = QtWidgets.QLineEdit()
        self.rc_exe = QtWidgets.QLineEdit()
        self.rc_exe.setPlaceholderText("auto: <engine>/Tools/rc/rc.exe")
        self.resolution = QtWidgets.QComboBox()
        self.resolution.addItems(RESOLUTIONS)
        self.physicalize = QtWidgets.QComboBox()
        self.physicalize.addItems(PHYSICALIZE)
        self.plant_shader = QtWidgets.QComboBox()
        self.plant_shader.addItems(SHADERS)
        self.chk_dds = QtWidgets.QCheckBox("Compile DDS with RC")
        self.chk_gl = QtWidgets.QCheckBox("Normal maps are OpenGL (flip green)")
        self.chk_ao = QtWidgets.QCheckBox("Bake AO into diffuse")
        self.chk_lods = QtWidgets.QCheckBox("Import LODs (_lodN.cgf)")
        self.chk_place = QtWidgets.QCheckBox("Place meshes in front of camera")
        self.chk_sel = QtWidgets.QCheckBox("Surfaces: assign to selection")
        self.chk_pom = QtWidgets.QCheckBox("Surfaces: parallax occlusion mapping")
        self.chk_keep = QtWidgets.QCheckBox("Keep work files (debug)")
        form.addRow("Port", self.port)
        form.addRow("Assets root", root_row)
        form.addRow("Output folder", self.subdir)
        form.addRow("rc.exe", self.rc_exe)
        form.addRow("Max texture size", self.resolution)
        form.addRow("Physicalize", self.physicalize)
        form.addRow("Plant shader", self.plant_shader)
        for chk in (self.chk_dds, self.chk_gl, self.chk_ao, self.chk_lods, self.chk_place,
                    self.chk_sel, self.chk_pom, self.chk_keep):
            form.addRow(chk)
        save = QtWidgets.QPushButton("Save settings")
        save.clicked.connect(self._save)
        form.addRow(save)
        root.addWidget(box)

        # diagnostics
        self.diag = QtWidgets.QLabel()
        self.diag.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.diag.setWordWrap(True)
        root.addWidget(self.diag)

        # actions
        row = QtWidgets.QHBoxLayout()
        btn_json = QtWidgets.QPushButton("Import Bridge JSON / Quixel zip...")
        btn_json.clicked.connect(self._import_json)
        btn_open = QtWidgets.QPushButton("Open output folder")
        btn_open.clicked.connect(self._open_output)
        row.addWidget(btn_json)
        row.addWidget(btn_open)
        root.addLayout(row)

        # log
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1500)
        root.addWidget(self.log, 1)

    # ---------------------------------------------------------------- settings
    def _load(self):
        s = self.ctrl.settings
        self.port.setValue(int(s.get("port")))
        self.assets_root.setText(s.get("assets_root") or "")
        self.subdir.setText(s.get("output_subdir") or "")
        self.rc_exe.setText(s.get("rc_exe") or "")
        self._set_combo(self.resolution, str(s.get("texture.output_resolution")))
        self._set_combo(self.physicalize, s.get("geometry.physicalize"))
        self._set_combo(self.plant_shader, s.get("material.plant_shader"))
        self.chk_dds.setChecked(bool(s.get("texture.generate_dds")))
        self.chk_gl.setChecked(bool(s.get("texture.normal_is_opengl")))
        self.chk_ao.setChecked(bool(s.get("texture.bake_ao_into_diffuse")))
        self.chk_lods.setChecked(bool(s.get("geometry.import_lods")))
        self.chk_place.setChecked(bool(s.get("placement.place_in_level")))
        self.chk_sel.setChecked(bool(s.get("placement.apply_surface_to_selection")))
        self.chk_pom.setChecked(bool(s.get("material.surface_pom")))
        self.chk_keep.setChecked(bool(s.get("keep_work_files")))

    @staticmethod
    def _set_combo(combo, value):
        index = combo.findText(str(value))
        if index >= 0:
            combo.setCurrentIndex(index)

    def _save(self):
        s = self.ctrl.settings
        port_changed = int(s.get("port")) != self.port.value()
        s.set("port", self.port.value())
        s.set("assets_root", self.assets_root.text().strip())
        s.set("output_subdir", self.subdir.text().strip() or "Objects/Megascans")
        s.set("rc_exe", self.rc_exe.text().strip())
        s.set("texture.output_resolution", self.resolution.currentText())
        s.set("geometry.physicalize", self.physicalize.currentText())
        s.set("material.plant_shader", self.plant_shader.currentText())
        s.set("texture.generate_dds", self.chk_dds.isChecked())
        s.set("texture.normal_is_opengl", self.chk_gl.isChecked())
        s.set("texture.bake_ao_into_diffuse", self.chk_ao.isChecked())
        s.set("geometry.import_lods", self.chk_lods.isChecked())
        s.set("placement.place_in_level", self.chk_place.isChecked())
        s.set("placement.apply_surface_to_selection", self.chk_sel.isChecked())
        s.set("material.surface_pom", self.chk_pom.isChecked())
        s.set("keep_work_files", self.chk_keep.isChecked())
        s.save()
        logger.info("settings saved to " + s.path)
        if port_changed and self.ctrl.listening:
            self.ctrl.start_server()
        self._refresh_diag()

    # ----------------------------------------------------------------- actions
    def _toggle_listen(self):
        if self.ctrl.listening:
            self.ctrl.stop_server()
        else:
            self.ctrl.start_server()
        self._refresh_diag()

    def _browse_root(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Project assets folder", self.assets_root.text())
        if path:
            self.assets_root.setText(path)

    def _import_json(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Bridge export JSON or Quixel download", "",
            "Bridge export / Quixel zip (*.json *.zip)")
        if path:
            self.ctrl.submit_file(path)

    def _open_output(self):
        snap = self.ctrl.runtime_settings()
        folder = os.path.join(snap.get("_runtime.assets_root") or "", snap.get("output_subdir") or "")
        if os.path.isdir(folder):
            os.startfile(folder)
        else:
            logger.warning("output folder does not exist yet: " + folder)

    # ------------------------------------------------------------------ status
    def _refresh_diag(self):
        diag = self.ctrl.diagnostics()
        self.diag.setText("\n".join("%s: %s" % item for item in diag.items()))
        self.btn_listen.setText("Stop listening" if self.ctrl.listening else "Start listening")

    def _tick(self):
        listening = "listening on %s" % self.ctrl.settings.get("port") if self.ctrl.listening else "not listening"
        pending = self.ctrl.pending
        self.status.setText("%s | %s%s" % (listening, self.ctrl.status, (" | pending %d" % pending) if pending else ""))
        for seq, level, text in logger.lines_since(self._log_seq):
            self._log_seq = seq
            self.log.appendPlainText(text)

    def _on_event(self, event, data):
        if event == "server":
            self._refresh_diag()

    def closeEvent(self, event):  # noqa
        try:
            self.ctrl.listeners.remove(self._on_event)
        except ValueError:
            pass
        super(BridgePanel, self).closeEvent(event)


def register():
    import SandboxBridge
    SandboxBridge.register_window(BridgePanel, "Quixel CE Bridge", category="Megascans",
                                  needs_menu_item=True, menu_path="Megascans", unique=True)
