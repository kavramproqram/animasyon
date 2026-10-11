# -*- coding: utf-8 -*-
"""
Kavram Animasyon — arayüz parçaları

Kavram Drawing_editor.py'den uyarlananlar:
  * ColorWheelDialog + ColorHistoryStrip   (renk çemberi, parlaklık, hex, son renkler)
  * AspectRatioPreview + ProjectDialog     (en-boy oranı grupları, hazır çözünürlükler, önizleme)
  * Arka plan rengi / video-görüntü seçimi (BackgroundDialog)
Ayrıca: ColorPanel, ParamForm, MathObjectDialog, ExportDialog, Timeline.
"""

import math
import copy

from PyQt5.QtCore import Qt, QRectF, QPointF, QRect, pyqtSignal, QSettings, QRegExp
from PyQt5.QtGui import (QPainter, QPen, QBrush, QColor, QImage, QConicalGradient, QRadialGradient, QPolygonF,
                         QFont, QRegExpValidator)
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox,
    QComboBox, QSlider, QLineEdit, QDialog, QDialogButtonBox, QMessageBox, QGroupBox, QSizePolicy, QFrame,
    QApplication,
)

from kanim_math import (RESOLUTION_GROUPS, find_preset, MIN_GRID, MAX_GRID, MIN_CANVAS, MAX_CANVAS,
                        min_grid_for, fmt_pts, parse_pts)
from kanim_core import PSCHEMA, DEFAULTS, KIND_NAMES, MATH_PRESETS, build_path, F, I, B, S, P
from kanim_help import tip, SETTINGS_ORG, SETTINGS_APP
from kanim_frames import HAS_CV2


# --------------------------------------------------------------------------------------
#  Renk çemberi  (Drawing_editor.py -> CircleBrightnessDialog'dan uyarlandı)
#  Fark: çember piksel piksel Python döngüsüyle değil, gradyanla BİR KEZ çizilip önbelleğe alınır.
# --------------------------------------------------------------------------------------
_WHEEL_CACHE = {}


def wheel_image(d):
    img = _WHEEL_CACHE.get(d)
    if img is None:
        img = QImage(d, d, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        c = d / 2.0
        cg = QConicalGradient(c, c, 0.0)
        for i in range(37):
            cg.setColorAt(i / 36.0, QColor.fromHsvF((i % 36) / 36.0, 1.0, 1.0))
        p.setBrush(QBrush(cg))
        p.drawEllipse(QRectF(0, 0, d, d))
        rg = QRadialGradient(c, c, c)
        rg.setColorAt(0.0, QColor(255, 255, 255, 255))
        rg.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(rg))
        p.drawEllipse(QRectF(0, 0, d, d))
        p.end()
        _WHEEL_CACHE[d] = img
    return img


def _hue_direction(d):
    """Gradyanın dönüş yönünü çizilmiş görüntüden ölçer (+1: saat yönünün tersi). Böylece seçim her zaman çizimle uyumlu olur."""
    img = wheel_image(d)
    c = d // 2
    h = img.pixelColor(c, int(c * 0.2)).hsvHueF() * 360.0   # ekranda tam üst nokta = 90 derece (ters yön)
    return 1 if 45.0 < h < 135.0 else -1


class _WheelWidget(QWidget):
    changed = pyqtSignal(float, float)      # ton (0-360), doygunluk (0-1)
    D = 164
    M = 6

    def __init__(self, hue, sat, parent=None):
        super().__init__(parent)
        self.h, self.s = hue, sat
        self.setFixedSize(self.D + 2 * self.M, self.D + 2 * self.M)
        self.dir = _hue_direction(self.D)
        self.setCursor(Qt.CrossCursor)

    def set_hs(self, h, s):
        self.h, self.s = h, s
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawImage(self.M, self.M, wheel_image(self.D))
        R = self.D / 2.0
        cx = cy = self.M + R
        ang = math.radians(self.dir * self.h)
        x = cx + R * self.s * math.cos(ang)
        y = cy - R * self.s * math.sin(ang)
        p.setPen(QPen(Qt.black, 2))
        p.setBrush(Qt.white)
        p.drawEllipse(QPointF(x, y), 5, 5)
        p.end()

    def _pick(self, pos):
        R = self.D / 2.0
        cx = cy = self.M + R
        dx, dy = pos.x() - cx, pos.y() - cy
        r = min(math.hypot(dx, dy), R)
        if r > 1.0:
            self.h = (self.dir * math.degrees(math.atan2(-dy, dx))) % 360.0
        self.s = r / R
        self.update()
        self.changed.emit(self.h, self.s)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pick(e.pos())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._pick(e.pos())


class ColorWheelDialog(QDialog):
    """Renk çemberi + parlaklık çubuğu + hex kodu. Alfa değeri korunur."""

    def __init__(self, initial=QColor("white"), parent=None, title="Renk çemberi"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        c = QColor(initial)
        self._alpha = c.alpha()
        h = c.hsvHueF()
        self.h = 0.0 if h < 0 else h * 360.0
        self.s = c.hsvSaturationF()
        self.v = c.valueF()

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.wheel = _WheelWidget(self.h, self.s)
        self.wheel.changed.connect(self._wheel_changed)
        top.addWidget(self.wheel)
        right = QVBoxLayout()
        self.v_label = QLabel()
        self.v_label.setAlignment(Qt.AlignCenter)
        right.addWidget(self.v_label)
        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(self.v * 100)))
        self.slider.setMinimumHeight(120)
        self.slider.valueChanged.connect(self._v_changed)
        right.addWidget(self.slider, 1, Qt.AlignHCenter)
        self.preview = QLabel()
        self.preview.setFixedSize(46, 46)
        right.addWidget(self.preview, 0, Qt.AlignHCenter)
        top.addLayout(right)
        lay.addLayout(top)

        row = QHBoxLayout()
        self.hex = QLineEdit()
        self.hex.setMaxLength(6)
        self.hex.setPlaceholderText("Hex kodu")
        self.hex.setValidator(QRegExpValidator(QRegExp("[0-9A-Fa-f]{0,6}")))
        self.hex.textEdited.connect(self._hex_edited)
        row.addWidget(QLabel("#"))
        row.addWidget(self.hex)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        tip(self.wheel, 'c_wheel')
        tip(self.hex, 'c_hex')
        self._refresh()

    def _color(self):
        c = QColor.fromHsvF(min(self.h / 360.0, 1.0), max(0.0, min(1.0, self.s)), max(0.0, min(1.0, self.v)))
        c.setAlpha(self._alpha)
        return c

    def _refresh(self, skip_hex=False):
        c = self._color()
        self.preview.setStyleSheet("background:%s;border:2px solid #fff;border-radius:4px;" % c.name())
        self.v_label.setText("%d%%" % round(self.v * 100))
        hue = QColor.fromHsvF(min(self.h / 360.0, 1.0), 1.0, 1.0).name()
        self.slider.setStyleSheet(
            "QSlider::groove:vertical{width:6px;border-radius:3px;background:qlineargradient("
            "x1:0,y1:1,x2:0,y2:0,stop:0 #000,stop:1 %s);}"
            "QSlider::handle:vertical{background:#fff;border:2px solid %s;height:12px;margin:0 -5px;border-radius:6px;}"
            % (hue, hue))
        if not skip_hex:
            self.hex.setText(c.name().upper()[1:])

    def _wheel_changed(self, h, s):
        self.h, self.s = h, s
        self._refresh()

    def _v_changed(self, val):
        self.v = val / 100.0
        self._refresh()

    def _hex_edited(self, text):
        if len(text) == 6:
            c = QColor("#" + text)
            if c.isValid():
                h = c.hsvHueF()
                self.h = self.h if h < 0 else h * 360.0
                self.s, self.v = c.hsvSaturationF(), c.valueF()
                self.wheel.set_hs(self.h, self.s)
                self.slider.blockSignals(True)
                self.slider.setValue(int(round(self.v * 100)))
                self.slider.blockSignals(False)
                self._refresh(skip_hex=True)

    def keyPressEvent(self, e):
        if e.modifiers() == Qt.ControlModifier and e.key() == Qt.Key_V and not self.hex.hasFocus():
            txt = "".join(ch for ch in QApplication.clipboard().text().upper() if ch in "0123456789ABCDEF")[:6]
            if len(txt) == 6:
                self.hex.setText(txt)
                self._hex_edited(txt)
            e.accept()
            return
        super().keyPressEvent(e)

    def getSelectedColor(self):
        return self._color()


class ColorButton(QPushButton):
    colorChanged = pyqtSignal(QColor)

    def __init__(self, color, alpha=False, parent=None):
        super().__init__(parent)
        self._c = QColor(color)
        self.alpha = alpha
        self.setFixedHeight(26)
        self.clicked.connect(self._pick)
        self._paint()

    def color(self):
        return QColor(self._c)

    def setColor(self, c):
        self._c = QColor(c)
        self._paint()

    def _paint(self):
        self.setStyleSheet("QPushButton{background:%s;border:1px solid #777;border-radius:3px;}" % self._c.name())

    def _pick(self):
        dlg = ColorWheelDialog(self._c, self, "Renk seç")
        if dlg.exec_():
            c = dlg.getSelectedColor()
            if not self.alpha:
                c.setAlpha(255)
            self.setColor(c)
            self.colorChanged.emit(c)


# --------------------------------------------------------------------------------------
#  Renk geçmişi şeridi (Drawing_editor.py -> ColorHistoryStrip'ten uyarlandı) ve palet
# --------------------------------------------------------------------------------------
class ColorHistoryStrip(QWidget):
    colorSelected = pyqtSignal(QColor)

    def __init__(self, cols=8, size=22, spacing=4, parent=None):
        super().__init__(parent)
        self.colors = []
        self.cols, self.size, self.sp = cols, size, spacing
        self.hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.set_colors([])

    def set_colors(self, colors):
        self.colors = list(colors)
        rows = max(1, (len(self.colors) + self.cols - 1) // self.cols)
        self.setFixedSize(self.cols * (self.size + self.sp) + self.sp, rows * (self.size + self.sp) + self.sp)
        self.update()

    def _index_at(self, pos):
        step = self.size + self.sp
        col, row = (pos.x() - self.sp) // step, (pos.y() - self.sp) // step
        if 0 <= col < self.cols and row >= 0:
            i = int(row * self.cols + col)
            if i < len(self.colors):
                return i
        return -1

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        step = self.size + self.sp
        for i, c in enumerate(self.colors):
            r = QRect(self.sp + (i % self.cols) * step, self.sp + (i // self.cols) * step, self.size, self.size)
            p.setBrush(QBrush(c))
            p.setPen(QPen(Qt.white, 2) if i == self.hover else QPen(Qt.gray, 1))
            p.drawRoundedRect(r, 4, 4)
        p.end()

    def mouseMoveEvent(self, e):
        i = self._index_at(e.pos())
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        i = self._index_at(e.pos())
        if i < 0:
            return
        if e.button() == Qt.LeftButton:
            self.colorSelected.emit(QColor(self.colors[i]))
        elif e.button() == Qt.RightButton:
            QApplication.clipboard().setText(self.colors[i].name().upper())


class SwatchGrid(QWidget):
    picked = pyqtSignal(QColor, bool)  # renk, dolgu mu?

    def __init__(self, colors, cols=12, size=18, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.cols = cols
        self.size = size
        rows = (len(colors) + cols - 1) // cols
        self.setFixedSize(cols * size, rows * size)

    def paintEvent(self, e):
        p = QPainter(self)
        for i, c in enumerate(self.colors):
            r = QRectF((i % self.cols) * self.size, (i // self.cols) * self.size, self.size - 1, self.size - 1)
            p.fillRect(r, c)
        p.end()

    def mousePressEvent(self, e):
        i = int(e.y() // self.size) * self.cols + int(e.x() // self.size)
        if 0 <= i < len(self.colors):
            self.picked.emit(QColor(self.colors[i]), e.button() == Qt.RightButton)


class ColorPanel(QGroupBox):
    def __init__(self, ed):
        super().__init__("Renk sistemi")
        self.ed = ed
        self._sync = False
        self.target = 'stroke'
        self.history = []
        lay = QVBoxLayout(self)
        lay.setSpacing(5)
        row = QHBoxLayout()
        self.b_stroke = QPushButton("Çizgi")
        self.b_fill = QPushButton("Dolgu")
        for b in (self.b_stroke, self.b_fill):
            b.setCheckable(True)
            b.setFixedHeight(34)
        self.b_stroke.setChecked(True)
        self.b_stroke.clicked.connect(lambda: self.set_target('stroke'))
        self.b_fill.clicked.connect(lambda: self.set_target('fill'))
        tip(self.b_stroke, 'c_stroke')
        tip(self.b_fill, 'c_fill')
        row.addWidget(self.b_stroke)
        row.addWidget(self.b_fill)
        lay.addLayout(row)
        self.fill_on = QCheckBox("Dolgu açık")
        self.fill_on.toggled.connect(self.ed.set_fill_on)
        tip(self.fill_on, 'fill_on')
        lay.addWidget(self.fill_on)
        self.sl = {}
        for key, label, mx, tk in (('h', 'Ton', 359, 'c_h'), ('s', 'Doygunluk', 255, 'c_s'),
                                   ('v', 'Parlaklık', 255, 'c_v'), ('a', 'Opaklık', 255, 'c_a')):
            r = QHBoxLayout()
            lb = QLabel(label)
            lb.setFixedWidth(64)
            s = QSlider(Qt.Horizontal)
            s.setRange(0, mx)
            s.valueChanged.connect(self._slider)
            s.sliderReleased.connect(self._commit)
            tip(s, tk)
            tip(lb, tk)
            r.addWidget(lb)
            r.addWidget(s)
            lay.addLayout(r)
            self.sl[key] = s
        hr = QHBoxLayout()
        self.hex = QLineEdit()
        self.hex.setPlaceholderText("#RRGGBB")
        self.hex.editingFinished.connect(self._hex)
        tip(self.hex, 'c_hex')
        self.wheel_btn = QPushButton("Çember…")
        self.wheel_btn.clicked.connect(self._wheel)
        self.wheel_btn.setFocusPolicy(Qt.NoFocus)
        tip(self.wheel_btn, 'c_wheel')
        hr.addWidget(self.hex, 1)
        hr.addWidget(self.wheel_btn)
        lay.addLayout(hr)
        pal = []
        for v in range(12):
            g = int(255 * v / 11)
            pal.append(QColor(g, g, g))
        for sat, val in ((255, 255), (150, 255), (255, 140)):
            for hdeg in range(0, 360, 30):
                pal.append(QColor.fromHsv(hdeg, sat, val))
        self.pal = SwatchGrid(pal)
        self.pal.picked.connect(self._palette)
        tip(self.pal, 'c_palette')
        lay.addWidget(self.pal)
        lay.addWidget(QLabel("Son kullanılanlar"))
        self.hist = ColorHistoryStrip()
        self.hist.colorSelected.connect(lambda c: self._palette(c, self.target == 'fill'))
        tip(self.hist, 'c_history')
        lay.addWidget(self.hist)
        hint = QLabel("Palette sol tık: çizgi, sağ tık: dolgu")
        hint.setStyleSheet("color:#777;font-size:10px;")
        lay.addWidget(hint)
        self.refresh()

    def cur(self):
        return self.ed.cur_stroke if self.target == 'stroke' else self.ed.cur_fill

    def set_target(self, t):
        self.target = t
        self.b_stroke.setChecked(t == 'stroke')
        self.b_fill.setChecked(t == 'fill')
        self.refresh()

    @staticmethod
    def _contrast(c):
        return "#000" if c.lightness() > 128 else "#fff"

    def _paint_targets(self):
        for b, c, name in ((self.b_stroke, self.ed.cur_stroke, 'stroke'), (self.b_fill, self.ed.cur_fill, 'fill')):
            b.setStyleSheet("QPushButton{background:%s;color:%s;border:2px solid %s;}" % (
                c.name(), self._contrast(c), "#4fc3f7" if self.target == name else "#444"))

    def refresh(self):
        self._sync = True
        c = self.cur()
        self.sl['h'].setValue(max(0, c.hue()))
        self.sl['s'].setValue(c.saturation())
        self.sl['v'].setValue(c.value())
        self.sl['a'].setValue(c.alpha())
        self.hex.setText(c.name(QColor.HexRgb))
        self._paint_targets()
        self.fill_on.blockSignals(True)
        self.fill_on.setChecked(self.ed.cur_fill_on)
        self.fill_on.blockSignals(False)
        self.hist.set_colors(self.history)
        self._sync = False

    def _slider(self):
        if self._sync:
            return
        c = QColor.fromHsv(self.sl['h'].value(), self.sl['s'].value(), self.sl['v'].value(), self.sl['a'].value())
        self.ed.set_color(self.target, c, tag='color')
        self.hex.setText(c.name(QColor.HexRgb))
        self._paint_targets()

    def _commit(self):
        self.add_history(self.cur())

    def _hex(self):
        c = QColor(self.hex.text().strip())
        if c.isValid():
            c.setAlpha(self.cur().alpha())
            self.ed.set_color(self.target, c)
            self.add_history(c)
            self.refresh()

    def _wheel(self):
        dlg = ColorWheelDialog(self.cur(), self, "Renk çemberi — " + ("dolgu" if self.target == 'fill' else "çizgi"))
        if dlg.exec_():
            c = dlg.getSelectedColor()
            self.ed.set_color(self.target, c)
            self.add_history(c)
            self.refresh()

    def _palette(self, c, right):
        t = 'fill' if right else 'stroke'
        self.set_target(t)
        c = QColor(c)
        c.setAlpha(self.cur().alpha())
        self.ed.set_color(t, c)
        if right:
            self.ed.set_fill_on(True)
        self.add_history(c)
        self.refresh()

    def add_history(self, c):
        c = QColor(c)
        c.setAlpha(255)
        self.history = [x for x in self.history if x.name() != c.name()]
        self.history.insert(0, c)
        self.history = self.history[:16]
        self.hist.set_colors(self.history)


# --------------------------------------------------------------------------------------
#  Nesne parametre formu
# --------------------------------------------------------------------------------------
class ParamForm(QWidget):
    """Bir nesne türünün matematiksel parametrelerini düzenleyen dinamik form."""
    changed = pyqtSignal()

    def __init__(self, kind, params, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.params = copy.deepcopy(params)
        self.widgets = {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)
        for key, label, typ in PSCHEMA[kind]:
            val = self.params.get(key, DEFAULTS[kind].get(key))
            if typ == F:
                w = QDoubleSpinBox()
                w.setRange(-1e6, 1e6)
                w.setDecimals(3)
                w.setKeyboardTracking(False)
                w.setValue(float(val))
                w.valueChanged.connect(self._ch)
            elif typ == I:
                w = QSpinBox()
                w.setRange(2 if key == 'steps' else 3, 20000 if key == 'steps' else 500)
                w.setKeyboardTracking(False)
                w.setValue(int(val))
                w.valueChanged.connect(self._ch)
            elif typ == B:
                w = QCheckBox()
                w.setChecked(bool(val))
                w.toggled.connect(self._ch)
            elif typ == S:
                w = QLineEdit(str(val))
                w.editingFinished.connect(self._ch)
            elif typ == P:
                w = QLineEdit(fmt_pts(val))
                w.editingFinished.connect(self._ch)
            else:
                w = QLabel("%d nokta (fareyle çizildi)" % len(val))
            self.widgets[key] = (w, typ)
            form.addRow(label, w)

    def _ch(self):
        before = copy.deepcopy(self.params)
        self.read()
        if self.params != before:            # odak kaybında gereksiz yeniden çizimi önler
            self.changed.emit()

    def read(self):
        for key, (w, typ) in self.widgets.items():
            if typ in (F, I):
                self.params[key] = w.value()
            elif typ == B:
                self.params[key] = w.isChecked()
            elif typ == S:
                self.params[key] = w.text()
            elif typ == P:
                try:
                    self.params[key] = parse_pts(w.text())
                    w.setStyleSheet("")
                except ValueError:
                    w.setStyleSheet("border:1px solid #c33;")
        return self.params


# --------------------------------------------------------------------------------------
#  Çözünürlük önizlemesi (Drawing_editor.py -> AspectRatioPreviewWidget)
# --------------------------------------------------------------------------------------
class AspectRatioPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tw, self.th = 1920, 1080
        self.setMinimumSize(230, 200)

    def update_dimensions(self, w, h):
        self.tw, self.th = max(1, w), max(1, h)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor("#111111"))
        margin = 30
        avail_w, avail_h = r.width() - margin * 2, r.height() - margin * 2 - 20
        ratio = self.tw / float(self.th)
        if avail_w / ratio <= avail_h:
            pw, ph = avail_w, avail_w / ratio
        else:
            ph, pw = avail_h, avail_h * ratio
        pw, ph = max(10.0, pw), max(10.0, ph)
        box = QRectF((r.width() - pw) / 2, (r.height() - 20 - ph) / 2, pw, ph)
        p.setBrush(QBrush(QColor(255, 255, 255, 14)))
        p.setPen(QPen(QColor("#666"), 1.5))
        p.drawRoundedRect(box, 4, 4)
        info = QRectF(0, r.height() - 30, r.width(), 30)
        p.fillRect(info, QColor("#090909"))
        p.setPen(QColor("#aaaaaa"))
        p.setFont(QFont("Sans", 8, QFont.Bold))
        g = math.gcd(self.tw, self.th)
        p.drawText(info, Qt.AlignCenter, "%d x %d  •  (%d:%d)" % (self.tw, self.th, self.tw // g, self.th // g))
        p.end()


# --------------------------------------------------------------------------------------
#  Proje penceresi (çözünürlük + grid + FPS + renkler)
# --------------------------------------------------------------------------------------
class ProjectDialog(QDialog):
    def __init__(self, proj, parent=None, first=False):
        super().__init__(parent)
        self.first = first
        self.setWindowTitle("Yeni proje" if first else "Proje ayarları")
        self.setMinimumWidth(740)
        s = QSettings(SETTINGS_ORG, SETTINGS_APP)
        w0 = s.value("canvasWidth", proj.width, type=int) if first else proj.width
        h0 = s.value("canvasHeight", proj.height, type=int) if first else proj.height

        main = QHBoxLayout(self)
        left = QVBoxLayout()
        form = QFormLayout()
        self.ratio = QComboBox()
        self.ratio.addItems(list(RESOLUTION_GROUPS.keys()))
        self.preset = QComboBox()
        form.addRow("En-boy oranı", self.ratio)
        form.addRow("Hazır çözünürlük", self.preset)
        self.w = QSpinBox()
        self.w.setRange(MIN_CANVAS, MAX_CANVAS)
        self.w.setSuffix(" px")
        self.w.setKeyboardTracking(False)
        self.h = QSpinBox()
        self.h.setRange(MIN_CANVAS, MAX_CANVAS)
        self.h.setSuffix(" px")
        self.h.setKeyboardTracking(False)
        self.w.setValue(w0)
        self.h.setValue(h0)
        row = QHBoxLayout()
        row.addWidget(self.w)
        row.addWidget(QLabel("x"))
        row.addWidget(self.h)
        form.addRow("Genişlik x Yükseklik", row)
        self.info = QLabel()
        self.info.setStyleSheet("color:#888;")
        form.addRow("", self.info)

        self.grid = QSpinBox()
        self.grid.setRange(MIN_GRID, MAX_GRID)
        self.grid.setSuffix(" px")
        self.grid.setValue(proj.grid)
        form.addRow("Grid boyutu (hücre)", self.grid)
        self.quick = []
        qrow = QHBoxLayout()
        for g in (8, 10, 16, 20, 25, 32, 40, 50, 64, 100):
            b = QPushButton(str(g))
            b.setFixedWidth(34)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _, v=g: self.grid.setValue(v))
            qrow.addWidget(b)
            self.quick.append((g, b))
        form.addRow("Hızlı grid", qrow)
        self.grid_hint = QLabel()
        self.grid_hint.setStyleSheet("color:#888;")
        form.addRow("", self.grid_hint)

        self.fps = QSpinBox()
        self.fps.setRange(1, 120)
        self.fps.setValue(proj.fps)
        self.frames = QSpinBox()
        self.frames.setRange(1, 200000)
        self.frames.setValue(proj.frames)
        form.addRow("Saniyedeki kare (FPS)", self.fps)
        form.addRow("Toplam kare sayısı", self.frames)
        self.bgc = ColorButton(proj.bg_color)
        self.gc = ColorButton(proj.grid_color)
        form.addRow("Tuval rengi", self.bgc)
        form.addRow("Grid rengi", self.gc)
        left.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        left.addWidget(bb)

        side = QFrame()
        side.setFrameShape(QFrame.StyledPanel)
        sl = QVBoxLayout(side)
        t = QLabel("ÖNİZLEME")
        t.setAlignment(Qt.AlignCenter)
        sl.addWidget(t)
        self.preview = AspectRatioPreview()
        sl.addWidget(self.preview, 1)
        main.addLayout(left, 3)
        main.addWidget(side, 2)

        for widget, key in ((self.ratio, 'd_ratio'), (self.preset, 'd_preset'), (self.w, 'd_w'), (self.h, 'd_h'),
                            (self.grid, 'd_grid'), (self.fps, 'd_fps'), (self.frames, 'd_frames'),
                            (self.bgc, 'd_bgc'), (self.gc, 'd_gc')):
            tip(widget, key)
        for _, b in self.quick:
            tip(b, 'd_gridq')

        # ilk durum: boyuta uyan hazır ayarı bul
        m = find_preset(w0, h0)
        self.ratio.blockSignals(True)
        self.ratio.setCurrentText(m[0] if m else "Özel Boyut")
        self.ratio.blockSignals(False)
        self._fill_presets(self.ratio.currentText())
        if m:
            self.preset.blockSignals(True)
            self.preset.setCurrentIndex(m[1])
            self.preset.blockSignals(False)
        self.ratio.currentIndexChanged.connect(self._on_ratio)
        self.preset.currentIndexChanged.connect(self._on_preset)
        self.w.valueChanged.connect(self._on_dim)
        self.h.valueChanged.connect(self._on_dim)
        self._after_dims()

    # --- hazır ayar mantığı (Drawing_editor.py'deki gibi) ------------------------------------
    def _fill_presets(self, group):
        self.preset.blockSignals(True)
        self.preset.clear()
        items = RESOLUTION_GROUPS.get(group, [])
        if items:
            for name, w, h in items:
                self.preset.addItem(name, (w, h))
            self.preset.setEnabled(True)
        else:
            self.preset.addItem("Serbest giriş")
            self.preset.setEnabled(False)
        self.preset.blockSignals(False)

    def _on_ratio(self, _):
        group = self.ratio.currentText()
        self._fill_presets(group)
        if RESOLUTION_GROUPS.get(group):
            self._on_preset(0)

    def _on_preset(self, _):
        d = self.preset.currentData()
        if d:
            for sp, v in ((self.w, d[0]), (self.h, d[1])):
                sp.blockSignals(True)
                sp.setValue(v)
                sp.blockSignals(False)
            self._after_dims()

    def _on_dim(self, _):
        m = find_preset(self.w.value(), self.h.value())
        self.ratio.blockSignals(True)
        if m:
            self.ratio.setCurrentText(m[0])
            self._fill_presets(m[0])
            self.preset.blockSignals(True)
            self.preset.setCurrentIndex(m[1])
            self.preset.blockSignals(False)
        else:
            self.ratio.setCurrentText("Özel Boyut")
            self._fill_presets("Özel Boyut")
        self.ratio.blockSignals(False)
        self._after_dims()

    def _after_dims(self):
        w, h = self.w.value(), self.h.value()
        self.preview.update_dimensions(w, h)
        mg = min_grid_for(w, h)
        self.grid.setMinimum(mg)                      # QSpinBox değeri alt sınıra çeker
        for g, b in self.quick:
            b.setEnabled(g >= mg)
        self.grid_hint.setText("En küçük grid: %d px  (performans için tuval boyutuna göre sınırlanır)" % mg)
        orient = "Yatay" if w > h else ("Dikey" if h > w else "Kare")
        self.info.setText("%.2f Megapiksel • %s • %d x %d hücre" % (w * h / 1e6, orient, w // self.grid.value(),
                                                                      h // self.grid.value()))

    def apply(self, proj):
        proj.width, proj.height, proj.grid = self.w.value(), self.h.value(), self.grid.value()
        proj.fps, proj.frames = self.fps.value(), self.frames.value()
        proj.bg_color, proj.grid_color = self.bgc.color(), self.gc.color()
        proj.fix_grid()
        s = QSettings(SETTINGS_ORG, SETTINGS_APP)
        s.setValue("canvasWidth", proj.width)
        s.setValue("canvasHeight", proj.height)


# --------------------------------------------------------------------------------------
#  Matematiksel nesne ekleme penceresi
# --------------------------------------------------------------------------------------
class MathObjectDialog(QDialog):
    def __init__(self, ed, parent=None):
        super().__init__(parent)
        self.ed = ed
        self.result_data = None
        self.setWindowTitle("Matematiksel nesne ekle")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        top = QFormLayout()
        self.kind = QComboBox()
        for k in ('func', 'param', 'polar', 'line', 'rect', 'ellipse', 'polygon', 'star', 'spline'):
            self.kind.addItem(KIND_NAMES[k], k)
        self.kind.currentIndexChanged.connect(lambda _: self._rebuild())
        top.addRow("Tür", self.kind)
        self.preset = QComboBox()
        self.preset.addItem("— Hazır formül —", None)
        for i, (n, k, p) in enumerate(MATH_PRESETS):
            self.preset.addItem(n, i)
        self.preset.currentIndexChanged.connect(self._preset)
        top.addRow("Hazır", self.preset)
        lay.addLayout(top)
        self.holder = QVBoxLayout()
        lay.addLayout(self.holder)
        pos = QFormLayout()
        g = ed.proj.grid
        cx = round(ed.proj.width / 2.0 / g) * g
        cy = round(ed.proj.height / 2.0 / g) * g
        self.px = QDoubleSpinBox()
        self.px.setRange(-1e6, 1e6)
        self.px.setValue(cx)
        self.py = QDoubleSpinBox()
        self.py.setRange(-1e6, 1e6)
        self.py.setValue(cy)
        self.rot = QDoubleSpinBox()
        self.rot.setRange(-3600, 3600)
        pos.addRow("Konum X (orijin)", self.px)
        pos.addRow("Konum Y (orijin)", self.py)
        pos.addRow("Döndürme (derece)", self.rot)
        lay.addLayout(pos)
        hint = QLabel("Fonksiyonlarda y yukarı doğrudur. Kullanılabilir: sin cos tan sqrt exp log abs pi e ^ ...")
        hint.setStyleSheet("color:#888;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Ekle")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for widget, key in ((self.kind, 'd_kind'), (self.preset, 'd_formula'), (self.px, 'd_px'),
                            (self.py, 'd_px'), (self.rot, 'd_rot')):
            tip(widget, key)
        self.form = None
        self._rebuild()

    def _rebuild(self, params=None):
        if self.form:
            self.holder.removeWidget(self.form)
            self.form.deleteLater()
        k = self.kind.currentData()
        base = copy.deepcopy(DEFAULTS[k])
        if params:
            base.update(params)
        self.form = ParamForm(k, base)
        self.holder.addWidget(self.form)

    def _preset(self):
        i = self.preset.currentData()
        if i is None:
            return
        n, k, p = MATH_PRESETS[i]
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(self.kind.findData(k))
        self.kind.blockSignals(False)
        self._rebuild(p)

    def _ok(self):
        k = self.kind.currentData()
        params = self.form.read()
        path, err = build_path(k, params)
        if err:
            QMessageBox.warning(self, "Hata", "İfade geçersiz: " + err)
            return
        self.result_data = (k, params, self.px.value(), self.py.value(), self.rot.value())
        self.accept()


# --------------------------------------------------------------------------------------
#  Dışa aktarma penceresi
# --------------------------------------------------------------------------------------
class ExportDialog(QDialog):
    def __init__(self, proj, bg_ok, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dışa aktar")
        lay = QFormLayout(self)
        self.fmt = QComboBox()
        self.fmt.addItem("PNG dizisi (klasör)", "png")
        if HAS_CV2:
            self.fmt.addItem("Video (MP4)", "mp4")
        lay.addRow("Biçim", self.fmt)
        self.a = QSpinBox()
        self.a.setRange(1, proj.frames)
        self.a.setValue(1)
        self.b = QSpinBox()
        self.b.setRange(1, proj.frames)
        self.b.setValue(proj.frames)
        lay.addRow("İlk kare", self.a)
        lay.addRow("Son kare", self.b)
        self.bg = QCheckBox("Arka plan videosunu / görüntüsünü dahil et")
        self.bg.setChecked(bg_ok)
        self.bg.setEnabled(bg_ok)
        lay.addRow(self.bg)
        self.grid = QCheckBox("Gridi dahil et")
        lay.addRow(self.grid)
        self.alpha = QCheckBox("Saydam arka plan (yalnızca PNG)")
        lay.addRow(self.alpha)
        self.fmt.currentIndexChanged.connect(self._fmt)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Dışa aktar")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        for widget, key in ((self.fmt, 'e_fmt'), (self.a, 'e_range'), (self.b, 'e_range'), (self.bg, 'e_bg'),
                            (self.grid, 'e_grid'), (self.alpha, 'e_alpha')):
            tip(widget, key)
        self._fmt()

    def _fmt(self):
        png = self.fmt.currentData() == 'png'
        self.alpha.setEnabled(png)
        if not png:
            self.alpha.setChecked(False)


# --------------------------------------------------------------------------------------
#  Arka plan penceresi: tuval rengi + video/görüntü seçimi
# --------------------------------------------------------------------------------------
class BackgroundDialog(QDialog):
    def __init__(self, ed, parent=None):
        super().__init__(parent)
        self.ed = ed
        self.setWindowTitle("Arka plan ayarları")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.color = ColorButton(ed.proj.bg_color)
        self.color.colorChanged.connect(ed.set_canvas_color)
        form.addRow("Tuval rengi", self.color)
        lay.addLayout(form)

        box = QGroupBox("Video / görüntü")
        bl = QVBoxLayout(box)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#9ab;")
        bl.addWidget(self.info)
        row = QHBoxLayout()
        self.b_load = QPushButton("Video / görüntü yükle…")
        self.b_folder = QPushButton("Kare klasörü…")
        self.b_clear = QPushButton("Kaldır")
        self.b_load.clicked.connect(lambda: (ed.load_background(), self.refresh()))
        self.b_folder.clicked.connect(lambda: (ed.load_bg_folder(), self.refresh()))
        self.b_clear.clicked.connect(lambda: (ed.clear_bg(), self.refresh()))
        for b in (self.b_load, self.b_folder, self.b_clear):
            b.setFocusPolicy(Qt.NoFocus)
            row.addWidget(b)
        bl.addLayout(row)
        f2 = QFormLayout()
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(int(round(ed.bg_opacity * 100)))
        self.opacity.valueChanged.connect(ed.set_bg_opacity)
        f2.addRow("Görünürlük", self.opacity)
        self.fit = QComboBox()
        for key, name in (('fit', 'Sığdır (oranı koru)'), ('fill', 'Doldur (kırp)'), ('stretch', 'Esnet')):
            self.fit.addItem(name, key)
        self.fit.setCurrentIndex(max(0, self.fit.findData(ed.bg_fit)))
        self.fit.currentIndexChanged.connect(lambda _: ed.set_bg_fit(self.fit.currentData()))
        f2.addRow("Sığdırma", self.fit)
        self.offset = QSpinBox()
        self.offset.setRange(1, 200000)
        self.offset.setValue(ed.bg_offset + 1)
        self.offset.setKeyboardTracking(False)
        self.offset.valueChanged.connect(lambda v: ed.set_bg_offset_value(v - 1))
        f2.addRow("Başlangıç karesi", self.offset)
        self.above = QCheckBox("Çizimlerin üstünde göster")
        self.above.setChecked(ed.bg_above)
        self.above.toggled.connect(ed.set_bg_above)
        f2.addRow(self.above)
        bl.addLayout(f2)
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Kapat")
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        for widget, key in ((self.color, 'b_color'), (self.b_load, 'b_load'), (self.b_folder, 'b_folder'),
                            (self.b_clear, 'b_clear'), (self.opacity, 'b_opacity'), (self.fit, 'b_fit'),
                            (self.offset, 'b_offset'), (self.above, 'b_above')):
            tip(widget, key)
        self.refresh()

    def refresh(self):
        bg = self.ed.bg
        if bg is None:
            self.info.setText("Arka plan yok.")
        else:
            names = {'video': 'Video', 'image': 'Görüntü', 'folder': 'Kare klasörü'}
            txt = "%s: %d x %d" % (names.get(bg.kind, bg.kind), bg.w, bg.h)
            if bg.count > 1:
                txt += ", %d kare" % bg.count
            if bg.fps:
                txt += ", %.3g FPS" % bg.fps
            if bg.note:
                txt += "\n" + bg.note
            self.info.setText(txt)
        self.offset.blockSignals(True)
        self.offset.setValue(self.ed.bg_offset + 1)
        self.offset.blockSignals(False)
        self.b_clear.setEnabled(bg is not None)


# --------------------------------------------------------------------------------------
#  Zaman çizelgesi
# --------------------------------------------------------------------------------------
class Timeline(QWidget):
    def __init__(self, ed):
        super().__init__()
        self.ed = ed
        self.px = 14.0
        self.off = 0.0
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        tip(self, 'timeline')

    def frame_at(self, x):
        return int((x + self.off) // self.px)

    def ensure_visible(self, f):
        x = f * self.px
        if x < self.off:
            self.off = max(0.0, x - 20)
        elif x + self.px > self.off + self.width() - 10:
            self.off = x + self.px - self.width() + 40
        self.update()

    def mousePressEvent(self, e):
        self._scrub(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._scrub(e)

    def mouseReleaseEvent(self, e):
        self.ed.refresh_props()          # gezinirken hafif mod; bırakınca panel güncellenir

    def _scrub(self, e):
        f = max(0, min(self.ed.proj.frames - 1, self.frame_at(e.x())))
        if f != self.ed.frame:
            self.ed.set_frame(f, light=True)

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if e.modifiers() & Qt.ControlModifier:
            self.px = max(4.0, min(60.0, self.px * (1.1 if d > 0 else 0.9)))
        else:
            self.off = max(0.0, self.off - d * 0.5)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        ed, proj = self.ed, self.ed.proj
        p.fillRect(self.rect(), QColor("#161616"))
        W, Hh = self.width(), self.height()
        px, off = self.px, self.off
        first = int(off // px)
        last = min(proj.frames - 1, int((off + W) // px) + 1)
        bg = ed.bg
        if bg and bg.kind in ("video", "folder"):
            x0 = ed.bg_offset * px - off
            x1 = (ed.bg_offset + bg.count) * px - off
            p.fillRect(QRectF(x0, 22, x1 - x0, 3), QColor("#2b5f9e"))
        p.setFont(QFont("Sans", 7))
        drawn = {o.ls for o in proj.objects if o.ls == o.le and o.ls >= 0}
        for f in range(first, last + 1):
            x = f * px - off
            if f % 5 == 0 or px > 22:
                p.setPen(QColor("#888"))
                p.drawText(QRectF(x, 0, px * 2, 18), Qt.AlignLeft | Qt.AlignVCenter, str(f + 1))
            p.setPen(QPen(QColor("#333")))
            p.drawLine(QPointF(x, 18), QPointF(x, Hh))
            if f in drawn:
                p.setBrush(QColor("#e8a33d"))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(x + px / 2, 40), 3.5, 3.5)
        y = 54
        for o in ed.selected_objs():
            a = o.ls * px - off
            b = ((o.le if o.le >= 0 else proj.frames - 1) + 1) * px - off
            p.fillRect(QRectF(a, y, b - a, 5), QColor("#2f6b3a"))
            for kf in o.keys:
                cx = kf * px - off + px / 2
                p.setBrush(QColor("#ffd24a"))
                p.setPen(QPen(QColor("#000"), 1))
                p.drawPolygon(QPolygonF([QPointF(cx, y - 2), QPointF(cx + 5, y + 3),
                                         QPointF(cx, y + 8), QPointF(cx - 5, y + 3)]))
            y += 14
            if y > Hh - 8:
                break
        cx = ed.frame * px - off
        p.fillRect(QRectF(cx, 0, px, Hh), QColor(255, 70, 70, 40))
        p.setPen(QPen(QColor("#ff5a5a"), 2))
        p.drawLine(QPointF(cx + px / 2, 0), QPointF(cx + px / 2, Hh))
        p.fillRect(QRectF(cx, 0, max(px, 24), 14), QColor("#ff5a5a"))
        p.setPen(QColor("#fff"))
        p.drawText(QRectF(cx, 0, max(px, 24), 14), Qt.AlignCenter, str(ed.frame + 1))
        p.end()
