# -*- coding: utf-8 -*-
"""
Kavram Animasyon Stüdyosu — ana pencere (MainWindow)

Mimari (orijinalle aynı):  Project/Obj modeli  ->  Canvas (ortak paint_scene)  ->  MainWindow
Yeni modüller:  kanim_math (saf matematik) • kanim_frames (kare okuma) • kanim_video (arka plan
kaynakları) • kanim_core (nesne modeli) • kanim_canvas • kanim_widgets • kanim_help (2 sn ipuçları,
kılavuz) • kanim_export • kanim_guard (çökme koruması)
"""

import sys
import os
import json
import copy
import time
import shutil
import tempfile

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QToolButton, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QSlider, QLineEdit, QFileDialog, QMessageBox,
    QAction, QActionGroup, QToolBar, QScrollArea, QGroupBox, QListWidget, QListWidgetItem, QShortcut,
    QProgressDialog, QInputDialog, QFrame, QStyleFactory, QAbstractItemView, QDockWidget,
)
from PyQt5.QtGui import QPainter, QColor, QKeySequence, QPalette, QImage
from PyQt5.QtCore import Qt, QPointF, QTimer, QElapsedTimer

import kanim_guard
from kanim_math import (APP_NAME, FILE_EXT, EASES, MIN_CANVAS, MAX_CANVAS, min_grid_for, clamp_grid, MAX_GRID)
from kanim_frames import HAS_CV2
from kanim_core import Obj, Project, KIND_NAMES, build_path
from kanim_video import ImageBG, FolderBG, VideoBG, FfmpegExtractThread, IMAGE_EXT
from kanim_canvas import Canvas
from kanim_widgets import (ProjectDialog, MathObjectDialog, ExportDialog, BackgroundDialog, Timeline, ColorPanel,
                           ParamForm)
from kanim_help import tip, TooltipManager, GuideDialog, guide_seen
from kanim_export import Exporter

UNDO_MAX_STEPS = 100
UNDO_MAX_BYTES = 64 * 1024 * 1024
AUTOSAVE_MS = 90 * 1000


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.proj = Project()
        self.frame = 0
        self.last_dir = 1
        self.sel = []
        self.tool = 'select'
        self.snap = True
        self.show_grid = True
        self.onion = False
        self.onion_n = 1
        self.autokey = False
        self.playing = False
        self.exporting = False
        self.loop = True
        self.sides = 5
        self.cur_stroke = QColor("#ffffff")
        self.cur_fill = QColor("#3a7bd5")
        self.cur_fill_on = False
        self.cur_width = 3.0
        self.scope = 'all'          # 'frame' | 'from' | 'all'
        self.bg = None
        self.bg_offset = 0
        self.bg_opacity = 0.6
        self.bg_fit = 'fit'
        self.bg_above = False
        self.tmpdirs = []
        self.undo_stack, self.redo_stack = [], []
        self._undo_tag, self._undo_time = None, 0.0
        self.clipboard = []
        self.filepath = None
        self.dirty = False
        self._sync = False
        self._param_for = None
        self._exporter = None
        self._ff = None
        self._ff_dlg = None
        self._ff_ctx = None
        self.play_start_frame = 0
        self.play_timer = QTimer(self)
        self.play_timer.setInterval(16)
        self.play_timer.setTimerType(Qt.PreciseTimer)
        self.play_timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(AUTOSAVE_MS)
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start()

        self.canvas = Canvas(self)
        self.setCentralWidget(self.canvas)
        self.timeline = Timeline(self)
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_right_panel()
        self._build_bottom()
        self._build_shortcuts()
        self.coord_label = QLabel("")
        self.statusBar().addPermanentWidget(self.coord_label)
        self._attach_tips()
        self.tipmgr = TooltipManager(self)
        for b in self.findChildren(QToolButton):
            self.tipmgr.suppress_native(b)
        kanim_guard.set_notifier(self._on_guard_error)
        self.set_tool('select')
        self.refresh_all()
        self.resize(1500, 900)
        self._update_title()
        QTimer.singleShot(50, self._startup)

    # --- başlangıç --------------------------------------------------------------------
    def _startup(self):
        if os.path.exists(kanim_guard.AUTOSAVE_PATH):
            r = QMessageBox.question(self, "Kurtarma", "Önceki oturumdan kaydedilmemiş bir kurtarma kopyası bulundu.\n"
                                     "Geri getirilsin mi?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if r == QMessageBox.Yes:
                if self.open_project(kanim_guard.AUTOSAVE_PATH, recovery=True):
                    return
            else:
                self._rm(kanim_guard.AUTOSAVE_PATH)
        dlg = ProjectDialog(self.proj, self, first=True)
        if dlg.exec_():
            dlg.apply(self.proj)
        self.apply_project_to_ui()
        self.canvas.fit_view()
        self.statusBar().showMessage("Hazır. ← → kare değiştir • Boşluk: oynat • K: anahtar kare • F1: kılavuz • "
                                     "Bir düğmenin üstünde 2 sn bekle: açıklaması çıkar", 12000)
        if not guide_seen():
            QTimer.singleShot(300, self.show_guide)

    def show_guide(self):
        GuideDialog(self).exec_()

    def _on_guard_error(self, short):
        self.statusBar().showMessage("Beklenmeyen hata engellendi, çalışmaya devam edebilirsin (%s). "
                                     "Ayrıntı: %s" % (short[:80], kanim_guard.ERROR_LOG), 10000)

    @staticmethod
    def _rm(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def apply_project_to_ui(self):
        self.proj.fix_grid()
        self.grid_spin.blockSignals(True)
        self.grid_spin.setRange(min_grid_for(self.proj.width, self.proj.height), MAX_GRID)
        self.grid_spin.setValue(self.proj.grid)
        self.grid_spin.blockSignals(False)
        self._sync = True
        self.fps_spin.setValue(self.proj.fps)
        self.total_spin.setValue(self.proj.frames)
        self._sync = False
        self.set_frame(min(self.frame, self.proj.frames - 1))
        self.canvas.update()
        self.timeline.update()

    # --- eylemler / menüler --------------------------------------------------------------
    def _act(self, text, slot=None, shortcut=None, checkable=False, checked=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        if checkable:
            a.setChecked(checked)
        if slot:
            (a.toggled if checkable else a.triggered).connect(slot)
        return a

    def _build_actions(self):
        self.a_new = self._act("Yeni proje...", self.new_project, "Ctrl+N")
        self.a_open = self._act("Aç...", self.open_project, "Ctrl+O")
        self.a_save = self._act("Kaydet", self.save_project, "Ctrl+S")
        self.a_saveas = self._act("Farklı kaydet...", lambda: self.save_project(True), "Ctrl+Shift+S")
        self.a_export = self._act("Dışa aktar (PNG dizisi / video)...", self.export_dialog, "Ctrl+E")
        self.a_png = self._act("Bu kareyi PNG kaydet...", self.export_current)
        self.a_quit = self._act("Çıkış", self.close, "Ctrl+Q")
        self.a_undo = self._act("Geri al", self.undo, "Ctrl+Z")
        self.a_redo = self._act("İleri al", self.redo, "Ctrl+Y")
        self.a_copy = self._act("Kopyala", self.copy_sel, "Ctrl+C")
        self.a_paste = self._act("Yapıştır", self.paste, "Ctrl+V")
        self.a_dup = self._act("Çoğalt", self.duplicate, "Ctrl+D")
        self.a_del = self._act("Sil", self.delete_selected, "Del")
        self.a_all = self._act("Tümünü seç", self.select_all, "Ctrl+A")
        self.a_projset = self._act("Proje ayarları (çözünürlük, grid, FPS)...", self.project_settings)
        self.a_fit = self._act("Tuvale sığdır", lambda: self.canvas.fit_view(), "Ctrl+0")
        self.a_z100 = self._act("%100 yakınlaştır", self.zoom100, "Ctrl+1")
        self.a_grid = self._act("Gridi göster", self.set_show_grid, "Ctrl+G", True, True)
        self.a_snap = self._act("Izgaraya yapış", self.set_snap, "Ctrl+Shift+G", True, True)
        self.a_onion = self._act("Soğan kabuğu (önceki/sonraki kare)", self.set_onion, "O", True, False)
        self.a_autokey = self._act("Otomatik anahtar kare", self.set_autokey, None, True, False)
        self.a_key = self._act("Anahtar kare ekle", self.add_key, "K")
        self.a_delkey = self._act("Anahtar kareyi sil", self.del_key, "Shift+K")
        self.a_clearkeys = self._act("Tüm hareketi temizle", self.clear_keys)
        self.a_math = self._act("Matematiksel nesne ekle...", self.math_dialog, "M")
        self.a_front = self._act("Öne getir", lambda: self.reorder(1), "Ctrl+]")
        self.a_back = self._act("Arkaya gönder", lambda: self.reorder(-1), "Ctrl+[")
        self.a_bg_video = self._act("Arka plan: video / görüntü yükle...", self.load_background, "Ctrl+B")
        self.a_bg_folder = self._act("Arka plan: kare klasörü yükle...", self.load_bg_folder)
        self.a_bg_set = self._act("Arka plan ayarları...", self.bg_dialog)
        self.a_bg_clear = self._act("Arka planı kaldır", self.clear_bg)
        self.a_bg_off = self._act("Video başlangıç kayması...", self.set_bg_offset)
        self.a_play = self._act("Oynat / Durdur", self.toggle_play)
        self.a_loop = self._act("Döngü", self.set_loop, None, True, True)
        self.a_help = self._act("Hızlı başlangıç kılavuzu", self.show_guide, "F1")

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("Dosya")
        for a in (self.a_new, self.a_open, self.a_save, self.a_saveas, None, self.a_export, self.a_png, None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("Düzen")
        for a in (self.a_undo, self.a_redo, None, self.a_copy, self.a_paste, self.a_dup, self.a_del, self.a_all, None,
                  self.a_front, self.a_back):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("Proje")
        m.addAction(self.a_projset)
        m.addAction(self.a_math)
        m = mb.addMenu("Görünüm")
        for a in (self.a_fit, self.a_z100, None, self.a_grid, self.a_snap, self.a_onion):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("Animasyon")
        for a in (self.a_key, self.a_delkey, self.a_clearkeys, self.a_autokey, None, self.a_play, self.a_loop):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("Arka plan")
        for a in (self.a_bg_video, self.a_bg_folder, self.a_bg_set, self.a_bg_off, self.a_bg_clear):
            m.addAction(a)
        sub = m.addMenu("Sığdırma")
        grp = QActionGroup(self)
        for key, name in (('fit', 'Sığdır (oranı koru)'), ('fill', 'Doldur (kırp)'), ('stretch', 'Esnet')):
            a = QAction(name, self, checkable=True)
            a.setChecked(key == self.bg_fit)
            a.triggered.connect(lambda _, k=key: self.set_bg_fit(k))
            tip(a, 'b_fit')
            grp.addAction(a)
            sub.addAction(a)
        m = mb.addMenu("Yardım")
        m.addAction(self.a_help)

    def _build_toolbars(self):
        tb = QToolBar("Araçlar")
        tb.setOrientation(Qt.Vertical)
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.LeftToolBarArea, tb)
        self.tool_actions = {}
        grp = QActionGroup(self)
        defs = [('select', "↖  Seç / Taşı  (V)", "V"), ('pen', "✎  Kalem  (P)", "P"), ('line', "╱  Çizgi  (L)", "L"),
                ('rect', "▭  Dikdörtgen  (R)", "R"), ('ellipse', "◯  Elips  (E)", "E"), ('polygon', "⬠  Çokgen  (G)", "G"),
                ('star', "★  Yıldız  (S)", "S"), ('spline', "∿  Eğri  (B)", "B"), ('eraser', "⌫  Silgi  (X)", "X"),
                ('pan', "✋  Kaydır  (H)", "H"), ('eyedrop', "◉  Damlalık  (I)", "I")]
        for key, text, sc in defs:
            a = QAction(text, self, checkable=True)
            a.setShortcut(QKeySequence(sc))
            a.triggered.connect(lambda _, k=key: self.set_tool(k))
            tip(a, key)
            grp.addAction(a)
            tb.addAction(a)
            self.tool_actions[key] = a
        tb.addSeparator()
        tb.addAction(self.a_math)
        for w in tb.findChildren(QToolButton):
            w.setFocusPolicy(Qt.NoFocus)
            w.setMinimumWidth(165)
            w.setStyleSheet("text-align:left;padding:4px 6px;")

        ob = QToolBar("Seçenekler")
        ob.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, ob)
        self._lbl_grid = QLabel(" Grid: ")
        ob.addWidget(self._lbl_grid)
        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(min_grid_for(self.proj.width, self.proj.height), MAX_GRID)
        self.grid_spin.setValue(self.proj.grid)
        self.grid_spin.setSuffix(" px")
        self.grid_spin.setKeyboardTracking(False)
        self.grid_spin.valueChanged.connect(self.set_grid)
        ob.addWidget(self.grid_spin)
        self.c_grid = QCheckBox("Göster")
        self.c_grid.setChecked(True)
        self.c_grid.toggled.connect(self.a_grid.setChecked)
        self.c_snap = QCheckBox("Yapış")
        self.c_snap.setChecked(True)
        self.c_snap.toggled.connect(self.a_snap.setChecked)
        self.a_grid.toggled.connect(self.c_grid.setChecked)
        self.a_snap.toggled.connect(self.c_snap.setChecked)
        ob.addWidget(self.c_grid)
        ob.addWidget(self.c_snap)
        ob.addSeparator()
        self._lbl_w = QLabel(" Kalınlık: ")
        ob.addWidget(self._lbl_w)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0, 200)
        self.width_spin.setValue(self.cur_width)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setKeyboardTracking(False)
        self.width_spin.valueChanged.connect(self.set_width)
        ob.addWidget(self.width_spin)
        self._lbl_sides = QLabel(" Kenar: ")
        ob.addWidget(self._lbl_sides)
        self.sides_spin = QSpinBox()
        self.sides_spin.setRange(3, 60)
        self.sides_spin.setValue(self.sides)
        self.sides_spin.valueChanged.connect(lambda v: setattr(self, 'sides', v))
        ob.addWidget(self.sides_spin)
        ob.addSeparator()
        self._lbl_scope = QLabel(" Çizim kapsamı: ")
        ob.addWidget(self._lbl_scope)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Tüm karelerde", 'all')
        self.scope_combo.addItem("Bu kareden sonuna", 'from')
        self.scope_combo.addItem("Sadece bu karede", 'frame')
        self.scope_combo.currentIndexChanged.connect(lambda: setattr(self, 'scope', self.scope_combo.currentData()))
        ob.addWidget(self.scope_combo)
        ob.addSeparator()
        self.c_autokey = QCheckBox("Oto-anahtar")
        self.c_autokey.toggled.connect(self.a_autokey.setChecked)
        self.a_autokey.toggled.connect(self.c_autokey.setChecked)
        ob.addWidget(self.c_autokey)
        self.c_onion = QCheckBox("Soğan")
        self.c_onion.toggled.connect(self.a_onion.setChecked)
        self.a_onion.toggled.connect(self.c_onion.setChecked)
        ob.addWidget(self.c_onion)
        self.onion_spin = QSpinBox()
        self.onion_spin.setRange(1, 6)
        self.onion_spin.setValue(1)
        self.onion_spin.valueChanged.connect(self.set_onion_n)
        ob.addWidget(self.onion_spin)
        ob.addSeparator()
        self._lbl_bg = QLabel(" Arka plan: ")
        ob.addWidget(self._lbl_bg)
        self.bg_slider = QSlider(Qt.Horizontal)
        self.bg_slider.setRange(0, 100)
        self.bg_slider.setValue(int(self.bg_opacity * 100))
        self.bg_slider.setFixedWidth(110)
        self.bg_slider.valueChanged.connect(self.set_bg_opacity)
        ob.addWidget(self.bg_slider)

    def _build_right_panel(self):
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 4, 4, 4)
        self.color_panel = ColorPanel(self)
        lay.addWidget(self.color_panel)
        gb = QGroupBox("Nesne özellikleri")
        v = QVBoxLayout(gb)
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._name_edited)
        v.addWidget(self.name_edit)
        self.kind_label = QLabel("")
        self.kind_label.setStyleSheet("color:#888;")
        v.addWidget(self.kind_label)
        tf = QFormLayout()
        self.tr = {}
        for key, label, rng, step in (('x', 'X', (-1e6, 1e6), 1), ('y', 'Y', (-1e6, 1e6), 1),
                                      ('rot', 'Döndürme °', (-36000, 36000), 1),
                                      ('sx', 'Ölçek X', (-1000, 1000), 0.05), ('sy', 'Ölçek Y', (-1000, 1000), 0.05)):
            s = QDoubleSpinBox()
            s.setRange(*rng)
            s.setDecimals(3)
            s.setSingleStep(step)
            s.setKeyboardTracking(False)
            s.valueChanged.connect(lambda val, k=key: self._tr_edited(k, val))
            self.tr[key] = s
            tf.addRow(label, s)
        v.addLayout(tf)
        self.key_label = QLabel("")
        v.addWidget(self.key_label)
        kr = QHBoxLayout()
        self.b_key = QPushButton("◆ Anahtar (K)")
        self.b_key.clicked.connect(self.add_key)
        self.b_key.setFocusPolicy(Qt.NoFocus)
        self.b_keydel = QPushButton("Sil")
        self.b_keydel.clicked.connect(self.del_key)
        self.b_keydel.setFocusPolicy(Qt.NoFocus)
        kr.addWidget(self.b_key)
        kr.addWidget(self.b_keydel)
        v.addLayout(kr)
        self.ease_combo = QComboBox()
        for k, n in EASES:
            self.ease_combo.addItem("Geçiş: " + n, k)
        self.ease_combo.activated.connect(self._ease_edited)
        v.addWidget(self.ease_combo)
        lf = QFormLayout()
        self.ls_spin = QSpinBox()
        self.ls_spin.setRange(1, 200000)
        self.ls_spin.setKeyboardTracking(False)
        self.le_spin = QSpinBox()
        self.le_spin.setRange(0, 200000)
        self.le_spin.setKeyboardTracking(False)
        self.le_spin.setSpecialValueText("son kare")
        self.ls_spin.valueChanged.connect(self._life_edited)
        self.le_spin.valueChanged.connect(self._life_edited)
        lf.addRow("Görünür: ilk kare", self.ls_spin)
        lf.addRow("Görünür: son kare", self.le_spin)
        v.addLayout(lf)
        self.param_holder = QVBoxLayout()
        self.param_box = QGroupBox("Matematiksel parametreler")
        self.param_box.setLayout(self.param_holder)
        v.addWidget(self.param_box)
        self.param_form = None
        lay.addWidget(gb)
        self.props_box = gb
        lb = QGroupBox("Nesneler (üstteki üstte)")
        lv = QVBoxLayout(lb)
        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.layer_list.setMinimumHeight(150)
        self.layer_list.itemSelectionChanged.connect(self._layer_selected)
        self.layer_list.itemChanged.connect(self._layer_item_changed)
        lv.addWidget(self.layer_list)
        lay.addWidget(lb)
        lay.addStretch(1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(host)
        sa.setFixedWidth(300)
        sa.setFrameShape(QFrame.NoFrame)
        dock = QDockWidget("Paneller", self)
        dock.setWidget(sa)
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_bottom(self):
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(4, 2, 4, 2)
        v.setSpacing(2)
        row = QHBoxLayout()
        self.tbtn = {}

        def btn(text, slot, key):
            b = QPushButton(text)
            b.setFixedWidth(34)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            row.addWidget(b)
            self.tbtn[key] = b
            return b
        btn("⏮", lambda: self.set_frame(0), 't_first')
        btn("◀", lambda: self.step(-1), 't_prev')
        self.play_btn = btn("▶", self.toggle_play, 't_play')
        btn("▶|", lambda: self.step(1), 't_next')
        btn("⏭", lambda: self.set_frame(self.proj.frames - 1), 't_last')
        row.addSpacing(10)
        row.addWidget(QLabel("Kare:"))
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(1, self.proj.frames)
        self.frame_spin.setKeyboardTracking(False)
        self.frame_spin.valueChanged.connect(lambda v_: None if self._sync else self.set_frame(v_ - 1))
        row.addWidget(self.frame_spin)
        row.addWidget(QLabel("/"))
        self.total_spin = QSpinBox()
        self.total_spin.setRange(1, 200000)
        self.total_spin.setValue(self.proj.frames)
        self.total_spin.setKeyboardTracking(False)
        self.total_spin.valueChanged.connect(self.set_total_frames)
        row.addWidget(self.total_spin)
        row.addSpacing(10)
        row.addWidget(QLabel("FPS:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(self.proj.fps)
        self.fps_spin.valueChanged.connect(self.set_fps)
        row.addWidget(self.fps_spin)
        self.c_loop = QCheckBox("Döngü")
        self.c_loop.setChecked(True)
        self.c_loop.toggled.connect(self.a_loop.setChecked)
        self.a_loop.toggled.connect(self.c_loop.setChecked)
        row.addWidget(self.c_loop)
        row.addStretch(1)
        hint = QLabel("← → kare değiştir • Shift+← → 10 kare • Ctrl+tekerlek: zaman çizelgesi yakınlaştır")
        hint.setStyleSheet("color:#777;")
        row.addWidget(hint)
        v.addLayout(row)
        v.addWidget(self.timeline)
        dock = QDockWidget("Zaman çizelgesi", self)
        dock.setWidget(host)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock.setTitleBarWidget(QWidget())
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

    def _build_shortcuts(self):
        def sc(key, fn):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.WindowShortcut)
            s.activated.connect(fn)
        sc(Qt.Key_Left, lambda: self.step(-1))
        sc(Qt.Key_Right, lambda: self.step(1))
        sc("Shift+Left", lambda: self.step(-10))
        sc("Shift+Right", lambda: self.step(10))
        sc(Qt.Key_Home, lambda: self.set_frame(0))
        sc(Qt.Key_End, lambda: self.set_frame(self.proj.frames - 1))
        sc(Qt.Key_Space, self.toggle_play)
        sc("Ctrl+Left", lambda: self.jump_key(-1))
        sc("Ctrl+Right", lambda: self.jump_key(1))

    def _attach_tips(self):
        """Her düğme / ayara Türkçe açıklama bağlar (TooltipManager 2 sn bekleyince gösterir)."""
        amap = {'a_new': 'a_new', 'a_open': 'a_open', 'a_save': 'a_save', 'a_saveas': 'a_saveas',
                'a_export': 'a_export', 'a_png': 'a_png', 'a_quit': 'a_quit', 'a_undo': 'a_undo', 'a_redo': 'a_redo',
                'a_copy': 'a_copy', 'a_paste': 'a_paste', 'a_dup': 'a_dup', 'a_del': 'a_del', 'a_all': 'a_all',
                'a_projset': 'a_projset', 'a_fit': 'a_fit', 'a_z100': 'a_z100', 'a_grid': 'grid_show',
                'a_snap': 'snap', 'a_onion': 'onion', 'a_autokey': 'autokey', 'a_key': 'key_add',
                'a_delkey': 'key_del', 'a_clearkeys': 'a_clearkeys', 'a_math': 'math', 'a_front': 'a_front',
                'a_back': 'a_back', 'a_bg_video': 'a_bg_video', 'a_bg_folder': 'a_bg_folder', 'a_bg_set': 'a_bg_set',
                'a_bg_clear': 'a_bg_clear', 'a_bg_off': 'a_bg_off', 'a_play': 't_play', 'a_loop': 't_loop',
                'a_help': 'a_help'}
        for attr, key in amap.items():
            tip(getattr(self, attr), key)
        pairs = [(self.grid_spin, 'grid_spin'), (self._lbl_grid, 'grid_spin'), (self.c_grid, 'grid_show'),
                 (self.c_snap, 'snap'), (self.width_spin, 'width'), (self._lbl_w, 'width'),
                 (self.sides_spin, 'sides'), (self._lbl_sides, 'sides'), (self.scope_combo, 'scope'),
                 (self._lbl_scope, 'scope'), (self.c_autokey, 'autokey'), (self.c_onion, 'onion'),
                 (self.onion_spin, 'onion_n'), (self.bg_slider, 'bg_slider'), (self._lbl_bg, 'bg_slider'),
                 (self.frame_spin, 't_frame'), (self.total_spin, 't_total'), (self.fps_spin, 't_fps'),
                 (self.c_loop, 't_loop'), (self.name_edit, 'name'), (self.b_key, 'key_add'),
                 (self.b_keydel, 'key_del'), (self.ease_combo, 'ease'), (self.ls_spin, 'life_start'),
                 (self.le_spin, 'life_end'), (self.param_box, 'params'), (self.layer_list, 'layers')]
        for w, k in pairs:
            tip(w, k)
        for k, key in (('x', 'tr_x'), ('y', 'tr_y'), ('rot', 'tr_rot'), ('sx', 'tr_sx'), ('sy', 'tr_sy')):
            tip(self.tr[k], key)
        for key, b in self.tbtn.items():
            tip(b, key)

    # --- araçlar ve durum ---------------------------------------------------------------
    def tool_cursor(self):
        return {'pan': Qt.OpenHandCursor, 'select': Qt.ArrowCursor, 'eyedrop': Qt.PointingHandCursor}.get(self.tool, Qt.CrossCursor)

    def set_tool(self, t):
        self.tool = t
        self.tool_actions[t].setChecked(True)
        self.canvas.spline_pts = []
        self.canvas.setCursor(self.tool_cursor())
        self.canvas.update()

    def show_cursor_info(self, pp):
        g = self.proj.grid
        self.coord_label.setText("x: %.1f  y: %.1f px   |   hücre: %.2f , %.2f   " % (pp.x(), pp.y(), pp.x() / g, pp.y() / g))

    def set_grid(self, v):
        """Grid alt sınırın altına inemez (sistemi yormasın)."""
        v2 = clamp_grid(v, self.proj.width, self.proj.height)
        if v2 != v:
            self.grid_spin.blockSignals(True)
            self.grid_spin.setValue(v2)
            self.grid_spin.blockSignals(False)
        if v2 == self.grid_spin.minimum():
            self.statusBar().showMessage("En küçük grid: %d px (performans için tuval boyutuna göre sınırlanır)" % v2, 3500)
        self.proj.grid = v2
        self.mark_dirty()
        self.canvas.update()

    def set_show_grid(self, v):
        self.show_grid = v
        self.canvas.update()

    def set_snap(self, v):
        self.snap = v

    def set_onion(self, v):
        self.onion = v
        self.canvas.update()

    def set_onion_n(self, v):
        self.onion_n = v
        self.canvas.update()

    def set_autokey(self, v):
        self.autokey = v

    def set_loop(self, v):
        self.loop = v

    def set_bg_opacity(self, v):
        self.bg_opacity = v / 100.0
        if int(self.bg_slider.value()) != int(v):
            self.bg_slider.blockSignals(True)
            self.bg_slider.setValue(int(v))
            self.bg_slider.blockSignals(False)
        self.mark_dirty()
        self.canvas.update()

    def set_bg_fit(self, k):
        self.bg_fit = k
        self.mark_dirty()
        self.canvas.update()

    def set_bg_above(self, v):
        self.bg_above = bool(v)
        self.mark_dirty()
        self.canvas.update()

    def set_bg_offset_value(self, v):
        self.bg_offset = max(0, int(v))
        self.mark_dirty()
        self.canvas.update()
        self.timeline.update()

    def set_canvas_color(self, c):
        self.proj.bg_color = QColor(c)
        self.mark_dirty()
        self.canvas.update()

    def zoom100(self):
        c = self.canvas
        center = c.to_proj(QPointF(c.width() / 2, c.height() / 2))
        c.zoom = 1.0
        c.offset = QPointF(c.width() / 2 - center.x(), c.height() / 2 - center.y())
        c.update()

    def mark_dirty(self):
        if not self.dirty:
            self.dirty = True
            self._update_title()

    def _update_title(self):
        n = os.path.basename(self.filepath) if self.filepath else "Adsız"
        self.setWindowTitle("%s%s — %s" % (n, " *" if self.dirty else "", APP_NAME))

    # --- kare gezinme ------------------------------------------------------------------
    def set_frame(self, f, light=False):
        f = max(0, min(self.proj.frames - 1, int(f)))
        self.last_dir = 1 if f >= self.frame else -1
        self.frame = f
        self._sync = True
        self.frame_spin.setRange(1, self.proj.frames)
        self.frame_spin.setValue(f + 1)
        self._sync = False
        self.timeline.ensure_visible(f)
        if not (light or self.playing):
            self.refresh_props()
        self.canvas.update()
        self.timeline.update()

    def step(self, d):
        self.set_frame(self.frame + d)

    def jump_key(self, d):
        o = self.primary()
        if not o or not o.keys:
            return
        ks = sorted(o.keys)
        if d > 0:
            nxt = [k for k in ks if k > self.frame]
            if nxt:
                self.set_frame(nxt[0])
        else:
            prv = [k for k in ks if k < self.frame]
            if prv:
                self.set_frame(prv[-1])

    def toggle_play(self):
        if self.exporting:
            return
        if self.playing:
            self.playing = False
            self.play_timer.stop()
            self.play_btn.setText("▶")
            self.refresh_props()
        else:
            self.playing = True
            self.last_dir = 1
            self.play_start_frame = 0 if self.frame >= self.proj.frames - 1 else self.frame
            self.clock.start()
            self.play_timer.start()
            self.play_btn.setText("⏸")
        self.canvas.update()

    def _tick(self):
        n = int(self.clock.elapsed() * self.proj.fps / 1000.0)
        f = self.play_start_frame + n
        if f >= self.proj.frames:
            if self.loop:
                self.play_start_frame = 0
                self.clock.restart()
                f = 0
            else:
                self.toggle_play()
                return
        if f != self.frame:
            self.set_frame(f)

    def set_total_frames(self, v):
        self.proj.frames = v
        self.frame_spin.setRange(1, v)
        if self.frame >= v:
            self.set_frame(v - 1)
        self.timeline.update()
        self.mark_dirty()

    def set_fps(self, v):
        self.proj.fps = v
        self.mark_dirty()

    # --- seçim -------------------------------------------------------------------------
    def selected_objs(self):
        m = {o.id: o for o in self.proj.objects}
        return [m[i] for i in self.sel if i in m]

    def primary(self):
        s = self.selected_objs()
        return s[0] if s else None

    def set_selection(self, ids):
        self.sel = list(ids)
        o = self.primary()
        if o:
            self.cur_stroke = QColor(o.stroke)
            self.cur_fill = QColor(o.fill)
            self.cur_fill_on = o.fill_on
            self.cur_width = o.width
            self.width_spin.blockSignals(True)
            self.width_spin.setValue(o.width)
            self.width_spin.blockSignals(False)
            self.color_panel.refresh()
        self.refresh_layers()
        self.refresh_props()
        self.canvas.update()
        self.timeline.update()

    def select_all(self):
        self.set_selection([o.id for o in self.proj.objects if o.alive(self.frame)])

    # --- nesne işlemleri -------------------------------------------------------------------
    def style_new(self, o):
        o.stroke = QColor(self.cur_stroke)
        o.fill = QColor(self.cur_fill)
        o.fill_on = self.cur_fill_on
        o.width = self.cur_width
        f = self.frame
        if self.scope == 'frame':
            o.ls = o.le = f
        elif self.scope == 'from':
            o.ls, o.le = f, -1
        else:
            o.ls, o.le = 0, -1

    def add_object(self, o, push=True):
        if push:
            self.push_undo()
        self.style_new(o)
        self.proj.objects.append(o)
        self.sel = [o.id]
        self.structure_changed()
        self.set_selection([o.id])

    def delete_selected(self):
        if not self.sel:
            return
        self.push_undo()
        ids = set(self.sel)
        self.proj.objects = [o for o in self.proj.objects if o.id not in ids]
        self.sel = []
        self.structure_changed()

    def duplicate(self):
        objs = self.selected_objs()
        if not objs:
            return
        self.push_undo()
        new = []
        g = self.proj.grid
        for o in objs:
            c = o.clone()
            if c.keys:
                for k in c.keys.values():
                    k['x'] += g
                    k['y'] += g
            else:
                c.base['x'] += g
                c.base['y'] += g
            self.proj.objects.append(c)
            new.append(c.id)
        self.structure_changed()
        self.set_selection(new)

    def copy_sel(self):
        self.clipboard = [o.to_dict() for o in self.selected_objs()]

    def paste(self):
        if not self.clipboard:
            return
        self.push_undo()
        new = []
        g = self.proj.grid
        for d in self.clipboard:
            o = Obj.from_dict(d)
            o.id = Obj._next_id
            Obj._next_id += 1
            if o.keys:
                for k in o.keys.values():
                    k['x'] += g
                    k['y'] += g
            else:
                o.base['x'] += g
                o.base['y'] += g
            self.proj.objects.append(o)
            new.append(o.id)
        self.structure_changed()
        self.set_selection(new)

    def reorder(self, d):
        objs = self.proj.objects
        sel = self.selected_objs()
        if not sel:
            return
        self.push_undo()
        idxs = sorted(objs.index(o) for o in sel)
        if d > 0:
            for i in reversed(idxs):
                if i + 1 < len(objs) and objs[i + 1] not in sel:
                    objs[i], objs[i + 1] = objs[i + 1], objs[i]
        else:
            for i in idxs:
                if i - 1 >= 0 and objs[i - 1] not in sel:
                    objs[i], objs[i - 1] = objs[i - 1], objs[i]
        self.structure_changed()

    def structure_changed(self):
        self.mark_dirty()
        self.refresh_layers()
        self.refresh_props()
        self.canvas.update()
        self.timeline.update()

    def create_math(self, kind, params, x, y, rot):
        o = Obj(kind, params)
        o.base.update(x=x, y=y, rot=rot)
        self.add_object(o)

    def math_dialog(self):
        dlg = MathObjectDialog(self, self)
        if dlg.exec_() and dlg.result_data:
            self.create_math(*dlg.result_data)

    # --- durum düzenleme + anahtar kareler -----------------------------------------------------
    def edit_state(self, o, **ch):
        f = self.frame
        if o.keys or self.autokey:
            if not o.keys:
                start = max(0, o.ls)
                if f != start:
                    o.keys[start] = dict(o.base, ease='linear')
            st = o.state(f)
            k = o.keys.get(f)
            if k is None:
                k = dict(st, ease='linear')
            k.update(ch)
            o.keys[f] = k
        else:
            o.base.update(ch)

    def state_edited(self, final=False):
        """Sürüklerken yalnız dönüşüm kutularını günceller (hafif); bırakınca tüm panel yenilenir."""
        self.mark_dirty()
        if final:
            self.refresh_props()
        else:
            o = self.primary()
            if o is not None:
                s = o.state(self.frame)
                self._sync = True
                for k, w in self.tr.items():
                    w.setValue(s[k])
                self._sync = False
        self.canvas.update()
        self.timeline.update()

    def add_key(self):
        objs = self.selected_objs()
        if not objs:
            return
        self.push_undo()
        for o in objs:
            st = o.state(self.frame)
            old = o.keys.get(self.frame, {})
            st['ease'] = old.get('ease', 'linear')
            o.keys[self.frame] = st
        self.mark_dirty()
        self.refresh_props()
        self.timeline.update()
        self.statusBar().showMessage("Anahtar kare eklendi: kare %d" % (self.frame + 1), 2500)

    def del_key(self):
        objs = [o for o in self.selected_objs() if self.frame in o.keys]
        if not objs:
            return
        self.push_undo()
        for o in objs:
            st = o.state(self.frame)
            del o.keys[self.frame]
            if not o.keys:
                o.base = dict(st)
        self.mark_dirty()
        self.refresh_props()
        self.canvas.update()
        self.timeline.update()

    def clear_keys(self):
        objs = [o for o in self.selected_objs() if o.keys]
        if not objs:
            return
        self.push_undo()
        for o in objs:
            o.base = o.state(self.frame)
            o.keys = {}
        self.mark_dirty()
        self.refresh_props()
        self.canvas.update()
        self.timeline.update()

    # --- renk / stil --------------------------------------------------------------------------
    def set_color(self, target, c, tag=None):
        if target == 'stroke':
            self.cur_stroke = QColor(c)
        else:
            self.cur_fill = QColor(c)
        sel = self.selected_objs()
        if sel:
            self.push_undo(tag or ('color', target))
            for o in sel:
                if target == 'stroke':
                    o.stroke = QColor(c)
                else:
                    o.fill = QColor(c)
                    o.fill_on = True
            if target == 'fill':
                self.cur_fill_on = True
            self.mark_dirty()
        self.canvas.update()

    def set_fill_on(self, v):
        self.cur_fill_on = bool(v)
        sel = self.selected_objs()
        if sel:
            self.push_undo(('fillon',))
            for o in sel:
                o.fill_on = bool(v)
            self.mark_dirty()
        self.canvas.update()

    def set_width(self, v):
        self.cur_width = v
        sel = self.selected_objs()
        if sel:
            self.push_undo(('width',))
            for o in sel:
                o.width = v
            self.mark_dirty()
        self.canvas.update()

    def pick_color_at(self, pp, vp):
        pr = self.proj
        scale = min(1.0, 1600.0 / max(pr.width, pr.height))
        img = self.render_frame(self.frame, with_grid=False, with_bg=True, scale=scale)
        x, y = int(pp.x() * scale), int(pp.y() * scale)
        if 0 <= x < img.width() and 0 <= y < img.height():
            c = img.pixelColor(x, y)
            c.setAlpha(255)
            self.set_color(self.color_panel.target, c)
            self.color_panel.add_history(c)
            self.color_panel.refresh()

    # --- özellik paneli ------------------------------------------------------------------------
    def refresh_props(self):
        o = self.primary()
        self.props_box.setEnabled(o is not None)
        self._sync = True
        try:
            if o is None:
                self.name_edit.setText("")
                self.kind_label.setText("Nesne seçilmedi")
                self.key_label.setText("")
                self._clear_param_form()
                return
            s = o.state(self.frame)
            for k, w in self.tr.items():
                w.setValue(s[k])
            if not self.name_edit.hasFocus():
                self.name_edit.setText(o.name)
            n = len(self.sel)
            self.kind_label.setText("%s%s" % (KIND_NAMES[o.kind], ("  (+%d seçili)" % (n - 1)) if n > 1 else ""))
            has = self.frame in o.keys
            if o.keys:
                self.key_label.setText(("◆ Bu karede anahtar var" if has else "Hareketli nesne — %d anahtar" % len(o.keys)))
                self.key_label.setStyleSheet("color:#ffd24a;" if has else "color:#aaa;")
            else:
                self.key_label.setText("Hareket yok (K ile anahtar ekle)")
                self.key_label.setStyleSheet("color:#888;")
            if has:
                self.ease_combo.setCurrentIndex(max(0, self.ease_combo.findData(o.keys[self.frame].get('ease', 'linear'))))
            self.ease_combo.setEnabled(has)
            self.ls_spin.setValue(o.ls + 1)
            self.le_spin.setValue(0 if o.le < 0 else o.le + 1)
            if self._param_for != (o.id, o.kind) or self.param_form is None:
                self._clear_param_form()
                self.param_form = ParamForm(o.kind, o.params)
                self.param_form.changed.connect(self._params_edited)
                self.param_holder.addWidget(self.param_form)
                self._param_for = (o.id, o.kind)
        finally:
            self._sync = False

    def _clear_param_form(self):
        if self.param_form is not None:
            self.param_holder.removeWidget(self.param_form)
            self.param_form.deleteLater()
            self.param_form = None
        self._param_for = None

    def _tr_edited(self, key, val):
        if self._sync:
            return
        o = self.primary()
        if not o:
            return
        self.push_undo(('tr', o.id, key))
        self.edit_state(o, **{key: val})
        self.mark_dirty()
        self.canvas.update()
        self.timeline.update()

    def _name_edited(self):
        o = self.primary()
        if o and o.name != self.name_edit.text():
            self.push_undo()
            o.name = self.name_edit.text() or o.name
            self.refresh_layers()

    def _ease_edited(self):
        o = self.primary()
        if o and self.frame in o.keys:
            self.push_undo(('ease',))
            for x in self.selected_objs():
                if self.frame in x.keys:
                    x.keys[self.frame]['ease'] = self.ease_combo.currentData()
            self.mark_dirty()
            self.canvas.update()

    def _life_edited(self):
        if self._sync:
            return
        o = self.primary()
        if not o:
            return
        self.push_undo(('life', o.id))
        o.ls = self.ls_spin.value() - 1
        o.le = -1 if self.le_spin.value() == 0 else max(o.ls, self.le_spin.value() - 1)
        self.mark_dirty()
        self.canvas.update()
        self.timeline.update()
        self.refresh_layers()

    def _params_edited(self):
        o = self.primary()
        if not o or self._sync or self.param_form is None:
            return
        new = self.param_form.read()
        path, err = build_path(o.kind, new)
        if err:
            self.statusBar().showMessage("İfade hatası: " + err, 4000)
            return
        self.push_undo(('params', o.id))
        o.params = copy.deepcopy(new)
        o.touch()
        self.mark_dirty()
        self.canvas.update()

    # --- katman listesi ---------------------------------------------------------------------------
    def refresh_layers(self):
        lw = self.layer_list
        lw.blockSignals(True)
        lw.clear()
        for o in reversed(self.proj.objects):
            life = ("%d" % (o.ls + 1)) if o.ls == o.le else ("%d–%s" % (o.ls + 1, "∞" if o.le < 0 else o.le + 1))
            it = QListWidgetItem("%s   [%s]" % (o.name, life))
            it.setData(Qt.UserRole, o.id)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if o.visible else Qt.Unchecked)
            lw.addItem(it)
            if o.id in self.sel:
                it.setSelected(True)
        lw.blockSignals(False)

    def _layer_selected(self):
        ids = [it.data(Qt.UserRole) for it in self.layer_list.selectedItems()]
        if set(ids) != set(self.sel):
            self.sel = ids
            o = self.primary()
            if o:
                self.cur_stroke, self.cur_fill, self.cur_fill_on, self.cur_width = QColor(o.stroke), QColor(o.fill), o.fill_on, o.width
                self.color_panel.refresh()
            self.refresh_props()
            self.canvas.update()
            self.timeline.update()

    def _layer_item_changed(self, it):
        oid = it.data(Qt.UserRole)
        for o in self.proj.objects:
            if o.id == oid:
                o.visible = it.checkState() == Qt.Checked
        self.canvas.update()
        self.mark_dirty()

    def refresh_all(self):
        self.refresh_layers()
        self.refresh_props()
        self.canvas.update()
        self.timeline.update()

    # --- geri al / ileri al (bellek bütçeli) -----------------------------------------------------
    def snapshot(self):
        return json.dumps({'objs': [o.to_dict() for o in self.proj.objects], 'sel': list(self.sel)})

    def _trim_stack(self, st):
        total = sum(len(s) for s in st)
        while st and (len(st) > UNDO_MAX_STEPS or total > UNDO_MAX_BYTES):
            total -= len(st.pop(0))

    def push_undo(self, tag=None):
        now = time.time()
        if tag is not None and tag == self._undo_tag and now - self._undo_time < 1.2:
            self._undo_time = now
            return
        self.undo_stack.append(self.snapshot())
        self._trim_stack(self.undo_stack)
        self.redo_stack.clear()
        self._undo_tag, self._undo_time = tag, now

    def restore(self, snap):
        d = json.loads(snap)
        self.proj.objects = [Obj.from_dict(x) for x in d['objs']]
        self.sel = [i for i in d['sel'] if any(o.id == i for o in self.proj.objects)]
        self._param_for = None
        self._undo_tag = None
        self.mark_dirty()
        self.refresh_layers()
        self.refresh_props()
        self.canvas.update()
        self.timeline.update()

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.snapshot())
        self._trim_stack(self.redo_stack)
        self.restore(self.undo_stack.pop())

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.snapshot())
        self._trim_stack(self.undo_stack)
        self.restore(self.redo_stack.pop())

    # --- arka plan (BLOKLAMAYAN) ------------------------------------------------------------------
    def bg_image_for(self, f):
        bg = self.bg
        if bg is None or bg.closed:
            return None
        idx = max(0, min(bg.count - 1, f - self.bg_offset))
        return bg.get(idx, 8 if self.playing else 3, self.last_dir)

    def _bg_frame_ready(self, idx):
        bg = self.bg
        if bg is not None and idx == max(0, min(bg.count - 1, self.frame - self.bg_offset)):
            self.canvas.update()

    def _bg_failed(self, msg):
        self.statusBar().showMessage("Video karesi okunamadı: %s" % msg, 6000)

    def _set_bg(self, src, ask=True, offset=0):
        old, self.bg = self.bg, None
        if old is not None:
            old.close()
        self.bg = src
        self.bg_offset = offset
        if src is None:
            self.canvas.update()
            self.timeline.update()
            return
        src.frameReady.connect(self._bg_frame_ready)
        src.failed.connect(self._bg_failed)
        if ask and src.kind in ("video", "folder"):
            self.scope_combo.setCurrentIndex(self.scope_combo.findData('frame'))
            self.scope = 'frame'
        msg = "%s yüklendi: %d x %d" % (src.kind, src.w, src.h)
        if src.count > 1:
            msg += ", %d kare" % src.count
        if src.note:
            msg += " — " + src.note
        self.statusBar().showMessage(msg, 9000)
        if ask:
            todo = []
            if (src.w, src.h) != (self.proj.width, self.proj.height) and \
                    MIN_CANVAS <= src.w <= MAX_CANVAS and MIN_CANVAS <= src.h <= MAX_CANVAS:
                todo.append("çözünürlüğü %d x %d yap" % (src.w, src.h))
            if src.count > 1 and src.count != self.proj.frames:
                todo.append("toplam kareyi %d yap" % src.count)
            if src.fps and abs(src.fps - self.proj.fps) > 0.5:
                todo.append("FPS'i %d yap" % round(src.fps))
            if todo:
                r = QMessageBox.question(self, "Proje ayarları", "Proje, arka planla eşleşsin mi?\n\n• " + "\n• ".join(todo) +
                                         ("\n\nÇizim kapsamı 'Sadece bu karede' olarak ayarlandı (kare kare çizim)."
                                          if self.scope == 'frame' else ""))
                if r == QMessageBox.Yes:
                    if (src.w, src.h) != (self.proj.width, self.proj.height) and \
                            MIN_CANVAS <= src.w <= MAX_CANVAS and MIN_CANVAS <= src.h <= MAX_CANVAS:
                        self.proj.width, self.proj.height = src.w, src.h
                    if src.count > 1:
                        self.proj.frames = src.count
                    if src.fps:
                        self.proj.fps = max(1, min(120, round(src.fps)))
                    self.apply_project_to_ui()
                    self.canvas.fit_view()
        self.canvas.update()
        self.timeline.update()
        self.mark_dirty()

    def load_background(self, path=None, ask=True, offset=0):
        if not isinstance(path, str) or not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Video veya görüntü seç", "",
                "Video / Görüntü (*.mp4 *.mov *.avi *.mkv *.webm *.gif *.png *.jpg *.jpeg *.bmp *.webp);;Tümü (*)")
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in IMAGE_EXT:
                self._set_bg(ImageBG(path), ask, offset)
                return
            if HAS_CV2 and ext != '.gif':
                try:
                    self._set_bg(VideoBG(path), ask, offset)
                    return
                except (ValueError, RuntimeError, OSError):
                    pass                      # codec açılamadı -> ffmpeg yedeği
            self._load_via_ffmpeg(path, ask, offset)
        except Exception as ex:
            QMessageBox.warning(self, "Hata", "Arka plan yüklenemedi:\n%s" % ex)

    def _load_via_ffmpeg(self, path, ask, offset):
        if self._ff is not None:
            return
        if not shutil.which("ffmpeg"):
            QMessageBox.warning(self, "Video açılamadı",
                                "Bu video opencv ile açılamadı ve sistemde ffmpeg yok.\n\n"
                                "• pip install opencv-python  (veya)\n• ffmpeg kur ve PATH'e ekle.")
            return
        d = tempfile.mkdtemp(prefix="kanim_")
        self.tmpdirs.append(d)
        self._ff = FfmpegExtractThread(path, d)
        self._ff_ctx = (path, d, ask, offset)
        dlg = QProgressDialog("Video küçültülmüş karelere çevriliyor...\n(uzun videolarda zaman alabilir)", "İptal", 0, 0, self)
        dlg.setWindowTitle("Lütfen bekleyin")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.canceled.connect(self._ff_cancel)
        self._ff_dlg = dlg
        self._ff.finished.connect(self._ff_done)
        self._ff.start()

    def _ff_cancel(self):
        if self._ff is not None:
            self._ff.requestInterruption()

    def _ff_done(self):
        th, ctx, dlg = self._ff, self._ff_ctx, self._ff_dlg
        self._ff = self._ff_ctx = self._ff_dlg = None
        if dlg is not None:
            try:
                dlg.canceled.disconnect(self._ff_cancel)
            except TypeError:
                pass
            dlg.close()
            dlg.deleteLater()
        if th is None or ctx is None:
            return
        path, d, ask, offset = ctx
        ok, err = th.ok, th.error
        th.deleteLater()
        if not ok:
            if err != "İptal edildi":
                QMessageBox.warning(self, "Video açılamadı", "ffmpeg dönüştürme hatası:\n%s" % err)
            shutil.rmtree(d, ignore_errors=True)
            return
        try:
            src = FolderBG(d, None, proxy_only=True)
            src.origin = path
            self._set_bg(src, ask, offset)
        except Exception as ex:
            QMessageBox.warning(self, "Hata", str(ex))

    def load_bg_folder(self, path=None, ask=True, offset=0):
        d = path if isinstance(path, str) and path else QFileDialog.getExistingDirectory(self, "Kare klasörünü seç")
        if d:
            try:
                self._set_bg(FolderBG(d), ask, offset)
            except Exception as ex:
                QMessageBox.warning(self, "Hata", str(ex))

    def clear_bg(self):
        self._set_bg(None)
        self.mark_dirty()

    def set_bg_offset(self):
        v, ok = QInputDialog.getInt(self, "Video kayması", "Videonun başladığı kare (1 = ilk kare):",
                                    self.bg_offset + 1, 1, 100000)
        if ok:
            self.set_bg_offset_value(v - 1)

    def bg_dialog(self):
        BackgroundDialog(self, self).exec_()

    # --- proje dosyası -----------------------------------------------------------------------------
    def new_project(self):
        if not self.confirm_discard():
            return
        p = Project()
        dlg = ProjectDialog(p, self, first=True)
        if not dlg.exec_():
            return
        dlg.apply(p)
        self.proj = p
        Obj._next_id = 1
        self.sel = []
        self.undo_stack, self.redo_stack = [], []
        self._set_bg(None)
        self.filepath = None
        self.dirty = False
        self.apply_project_to_ui()
        self.refresh_all()
        self.canvas.fit_view()
        self._update_title()

    def project_settings(self):
        dlg = ProjectDialog(self.proj, self)
        if dlg.exec_():
            dlg.apply(self.proj)
            self.apply_project_to_ui()
            self.mark_dirty()

    def project_data(self):
        bg = None
        if self.bg is not None:
            origin = getattr(self.bg, 'origin', None)
            bg = ({'path': origin, 'kind': 'video', 'offset': self.bg_offset} if origin else
                  {'path': self.bg.path, 'kind': self.bg.kind, 'offset': self.bg_offset})
        return {'version': 2, 'meta': self.proj.meta(), 'objects': [o.to_dict() for o in self.proj.objects],
                'bg': bg, 'bg_opacity': self.bg_opacity, 'bg_fit': self.bg_fit, 'bg_above': self.bg_above}

    @staticmethod
    def write_atomic(path, data):
        """Önce geçici dosyaya yaz, diske işle, sonra yerine koy: yarım kalan kayıt eski dosyayı bozmaz."""
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)

    def save_project(self, as_new=False):
        path = self.filepath
        if as_new is True or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Kaydet", "proje" + FILE_EXT, "Kavram Animasyon (*%s)" % FILE_EXT)
            if not path:
                return
            if not path.endswith(FILE_EXT):
                path += FILE_EXT
        try:
            self.write_atomic(path, self.project_data())
        except OSError as ex:
            QMessageBox.warning(self, "Kaydedilemedi", "Dosya yazılamadı:\n%s" % ex)
            return
        self.filepath = path
        self.dirty = False
        self._rm(kanim_guard.AUTOSAVE_PATH)
        self._update_title()
        self.statusBar().showMessage("Kaydedildi: " + path, 4000)

    def autosave(self):
        if not self.dirty or self.exporting or not kanim_guard.ensure_dir():
            return
        try:
            self.write_atomic(kanim_guard.AUTOSAVE_PATH, self.project_data())
        except Exception:
            pass

    def open_project(self, path=None, recovery=False):
        if not recovery and not self.confirm_discard():
            return False
        if not isinstance(path, str) or not path:
            path, _ = QFileDialog.getOpenFileName(self, "Aç", "", "Kavram Animasyon (*%s);;Tümü (*)" % FILE_EXT)
        if not path:
            return False
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
            m = d['meta']
            p = Project()
            p.width = max(MIN_CANVAS, min(MAX_CANVAS, int(m.get('width', 1100))))
            p.height = max(MIN_CANVAS, min(MAX_CANVAS, int(m.get('height', 600))))
            p.grid = int(m.get('grid', 20))
            p.fps = max(1, min(120, int(m.get('fps', 12))))
            p.frames = max(1, int(m.get('frames', 48)))
            p.bg_color = QColor(m.get('bg_color', '#000000'))
            p.grid_color = QColor(m.get('grid_color', '#3c3c3c'))
            p.fix_grid()
            objs = [Obj.from_dict(x) for x in d.get('objects', [])]
        except Exception as ex:
            QMessageBox.warning(self, "Hata", "Dosya açılamadı:\n%s" % ex)
            return False
        p.objects = objs
        self.proj = p
        self.sel = []
        self.undo_stack, self.redo_stack = [], []
        self._set_bg(None)
        self.bg_opacity = float(d.get('bg_opacity', 0.6))
        self.bg_fit = d.get('bg_fit', 'fit')
        self.bg_above = bool(d.get('bg_above', False))
        self.bg_slider.blockSignals(True)
        self.bg_slider.setValue(int(self.bg_opacity * 100))
        self.bg_slider.blockSignals(False)
        self.apply_project_to_ui()
        self.refresh_all()
        self.canvas.fit_view()
        b = d.get('bg')
        if b and os.path.exists(b.get('path', '')):
            off = int(b.get('offset', 0))
            kind = b.get('kind')
            if kind == 'folder':
                self.load_bg_folder(b['path'], ask=False, offset=off)
            elif kind == 'image':
                self.load_background(b['path'], ask=False, offset=off)
            else:
                self.load_background(b['path'], ask=False, offset=off)
        elif b:
            QMessageBox.information(self, "Arka plan", "Arka plan dosyası bulunamadı:\n%s" % b.get('path'))
        if recovery:
            self.filepath = None
            self.dirty = True
            self.statusBar().showMessage("Kurtarma kopyası açıldı. Lütfen Kaydet ile bir ada kaydet.", 10000)
        else:
            self.filepath = path
            self.dirty = False
        self._update_title()
        self.canvas.update()
        self.timeline.update()
        return True

    def confirm_discard(self):
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Kaydedilmemiş değişiklikler", "Değişiklikler kaydedilsin mi?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            self.save_project()
            return not self.dirty
        return r == QMessageBox.Discard

    def closeEvent(self, e):
        if self.exporting:
            QMessageBox.information(self, "Dışa aktarma sürüyor", "Önce dışa aktarma bitsin ya da iptal edilsin.")
            e.ignore()
            return
        if not self.confirm_discard():
            e.ignore()
            return
        self.play_timer.stop()
        self.autosave_timer.stop()
        self.tipmgr._timer.stop()
        if self._ff is not None:
            self._ff.requestInterruption()
            self._ff.wait(4000)
        if self.bg is not None:
            self.bg.close()
            self.bg = None
        for d in self.tmpdirs:
            shutil.rmtree(d, ignore_errors=True)
        self._rm(kanim_guard.AUTOSAVE_PATH)
        e.accept()

    # --- dışa aktarma -------------------------------------------------------------------------------
    def render_frame(self, f, with_grid=False, with_bg=False, scale=1.0):
        pr = self.proj
        img = QImage(max(1, int(pr.width * scale)), max(1, int(pr.height * scale)), QImage.Format_ARGB32)
        if img.isNull():
            raise MemoryError("Bellek yetersiz")
        img.fill(Qt.transparent)
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            p.scale(scale, scale)
            self.canvas.paint_scene(p, f, with_grid=with_grid, with_bg=with_bg, ghosts=False, zoom=scale)
        finally:
            p.end()
        return img

    def export_current(self):
        path, _ = QFileDialog.getSaveFileName(self, "PNG olarak kaydet", "kare_%04d.png" % (self.frame + 1), "PNG (*.png)")
        if not path:
            return
        try:
            ok = self.render_frame(self.frame, with_grid=False, with_bg=self.bg is not None).save(path)
        except MemoryError as ex:
            QMessageBox.warning(self, "Hata", str(ex))
            return
        if not ok:
            QMessageBox.warning(self, "Hata", "PNG yazılamadı:\n%s" % path)

    def export_dialog(self):
        if self.exporting or self._exporter is not None:
            return
        dlg = ExportDialog(self.proj, self.bg is not None, self)
        if not dlg.exec_():
            return
        a, b = dlg.a.value() - 1, dlg.b.value() - 1
        if b < a:
            a, b = b, a
        fmt = dlg.fmt.currentData()
        if self.playing:
            self.toggle_play()
        if fmt == 'png':
            target = QFileDialog.getExistingDirectory(self, "Kayıt klasörü")
        else:
            target, _ = QFileDialog.getSaveFileName(self, "Video kaydet", "animasyon.mp4", "MP4 (*.mp4)")
            if target and not target.lower().endswith(".mp4"):
                target += ".mp4"
        if not target:
            return
        self._exporter = Exporter(self, fmt, a, b, dlg.bg.isChecked(), dlg.grid.isChecked(), dlg.alpha.isChecked(), target)
        self._exporter.start()


# --------------------------------------------------------------------------------------
#  Siyah tema
# --------------------------------------------------------------------------------------
DARK_QSS = """
* { font-size: 12px; }
QMainWindow, QDialog, QWidget { background: #181818; color: #dddddd; }
QMenuBar, QMenu { background: #1d1d1d; color: #ddd; }
QMenu::item:selected, QMenuBar::item:selected { background: #333; }
QToolBar { background: #1d1d1d; border: 0; spacing: 4px; padding: 3px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; color: #ddd; }
QToolButton:hover { background: #2a2a2a; }
QToolButton:checked { background: #264a63; border: 1px solid #4fc3f7; }
QPushButton { background: #2a2a2a; border: 1px solid #444; border-radius: 4px; padding: 3px 8px; color: #ddd; }
QPushButton:hover { background: #343434; }
QPushButton:checked { border: 2px solid #4fc3f7; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget { min-height: 20px; background: #101010; border: 1px solid #3a3a3a; border-radius: 3px; padding: 2px; color: #eee; }
QComboBox QAbstractItemView { background: #181818; color: #eee; selection-background-color: #264a63; }
QGroupBox { border: 1px solid #333; border-radius: 6px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #9ab; }
QSlider::groove:horizontal { height: 5px; background: #333; border-radius: 2px; }
QSlider::handle:horizontal { background: #4fc3f7; width: 12px; margin: -4px 0; border-radius: 6px; }
QListWidget::item:selected { background: #264a63; }
QScrollBar:vertical { background: #151515; width: 10px; }
QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 4px; min-height: 20px; }
QStatusBar { background: #1d1d1d; color: #aaa; }
QToolTip { background: #222; color: #eee; border: 1px solid #555; }
QDockWidget { color: #aaa; }
QTextBrowser { background: #141414; color: #ddd; border: 1px solid #333; }
"""


def apply_dark(app):
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#181818"))
    pal.setColor(QPalette.WindowText, QColor("#dddddd"))
    pal.setColor(QPalette.Base, QColor("#101010"))
    pal.setColor(QPalette.AlternateBase, QColor("#181818"))
    pal.setColor(QPalette.Text, QColor("#eeeeee"))
    pal.setColor(QPalette.Button, QColor("#2a2a2a"))
    pal.setColor(QPalette.ButtonText, QColor("#dddddd"))
    pal.setColor(QPalette.Highlight, QColor("#264a63"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#222"))
    pal.setColor(QPalette.ToolTipText, QColor("#eee"))
    app.setPalette(pal)
    app.setStyleSheet(DARK_QSS)


def main():
    kanim_guard.install()                    # QApplication'dan ÖNCE: hata yakalayıcı + faulthandler
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_dark(app)
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) and sys.argv[1].endswith(FILE_EXT):
        QTimer.singleShot(200, lambda: w.open_project(sys.argv[1]))
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
