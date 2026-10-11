# -*- coding: utf-8 -*-
"""
Kavram Animasyon — dışa aktarma (PNG dizisi / MP4)

Eski sürüm tüm kareleri tek bir döngüde, QApplication.processEvents() ile arayüzü zorlayarak
üretiyordu (yeniden giriş = beklenmedik hatalar, donma, iptalde yarım dosya). Burada her kare
ayrı bir zamanlayıcı adımında üretilir: arayüz canlı kalır, iptal anında çalışır, hata olursa
kaynaklar temiz kapatılır. Arka plan videosu TAM çözünürlükte, ardışık (hızlı) okunur.
"""

import os

from PyQt5.QtCore import Qt, QObject, QTimer
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import QProgressDialog, QMessageBox

from kanim_frames import HAS_CV2

if HAS_CV2:
    import cv2
    import numpy as np


def _qimage_to_bgr(img):
    """Format_RGB32 (bayt sırası B,G,R,X) -> BGR numpy (kopyasız bakış, sonra bitişik kopya)."""
    w, h = img.width(), img.height()
    ptr = img.constBits()
    n = img.sizeInBytes() if hasattr(img, 'sizeInBytes') else img.byteCount()
    ptr.setsize(n)
    arr = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w, :3]
    return np.ascontiguousarray(arr)


class Exporter(QObject):
    def __init__(self, ed, fmt, a, b, with_bg, with_grid, alpha, target):
        super().__init__(ed)
        self.ed = ed
        self.fmt, self.a, self.b = fmt, a, b
        self.with_bg, self.with_grid, self.alpha = with_bg, with_grid, alpha
        self.target = target
        self.i = 0
        self.total = b - a + 1
        self.reader = None
        self.writer = None
        self.error = ""
        self.done = False
        self.prog = None

    # ---------------------------------------------------------------------------------------
    def start(self):
        ed, pr = self.ed, self.ed.proj
        try:
            if self.with_bg and ed.bg is not None:
                self.reader = ed.bg.open_reader()
            if self.fmt == 'mp4':
                if not HAS_CV2:
                    raise RuntimeError("Video dışa aktarma için opencv gerekli (pip install opencv-python)")
                self.writer = cv2.VideoWriter(self.target, cv2.VideoWriter_fourcc(*'mp4v'), float(pr.fps),
                                              (pr.width, pr.height))
                if not self.writer.isOpened():
                    raise RuntimeError("Video dosyası oluşturulamadı:\n%s" % self.target)
            else:
                os.makedirs(self.target, exist_ok=True)
        except Exception as ex:
            self._finish(str(ex))
            return
        self.prog = QProgressDialog("Dışa aktarılıyor...", "İptal", 0, self.total, ed)
        self.prog.setWindowTitle("Lütfen bekleyin")
        self.prog.setWindowModality(Qt.WindowModal)
        self.prog.setMinimumDuration(0)
        self.prog.setAutoClose(False)
        self.prog.setAutoReset(False)
        self.prog.canceled.connect(self._cancel)
        self.prog.setValue(0)
        ed.exporting = True
        QTimer.singleShot(0, self._step)

    def _cancel(self):
        self.error = "İptal edildi"
        self.done = True

    def _step(self):
        if self.done:
            self._finish(self.error)
            return
        try:
            f = self.a + self.i
            self._render_one(f)
        except Exception as ex:
            self._finish("Kare %d üretilemedi: %s" % (f + 1, ex))
            return
        self.i += 1
        if self.prog is not None:
            self.prog.setValue(self.i)
        if self.i >= self.total:
            self._finish("")
        else:
            QTimer.singleShot(0, self._step)

    def _render_one(self, f):
        ed, pr = self.ed, self.ed.proj
        bg_img = None
        if self.reader is not None:
            idx = max(0, min(ed.bg.count - 1, f - ed.bg_offset))
            bg_img = self.reader.read(idx)
        if self.alpha and self.fmt == 'png':
            img = QImage(pr.width, pr.height, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
        else:
            img = QImage(pr.width, pr.height, QImage.Format_RGB32)
            if img.isNull():
                raise MemoryError("Bellek yetersiz (%d x %d)" % (pr.width, pr.height))
            img.fill(pr.bg_color)
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            ed.canvas.paint_scene(p, f, with_grid=self.with_grid, with_bg=self.with_bg, ghosts=False,
                                  bg_img=bg_img, alpha_bg=(self.alpha and self.fmt == 'png'), zoom=1.0)
        finally:
            p.end()
        if self.fmt == 'png':
            path = os.path.join(self.target, "kare_%04d.png" % (f + 1))
            if not img.save(path):
                raise IOError("Yazılamadı (disk dolu / izin yok?): %s" % path)
        else:
            self.writer.write(_qimage_to_bgr(img))

    def _finish(self, err):
        self.done = True
        ed = self.ed
        for closer in (getattr(self.reader, 'close', None), getattr(self.writer, 'release', None)):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        self.reader = self.writer = None
        if self.prog is not None:
            try:
                self.prog.canceled.disconnect(self._cancel)
            except TypeError:
                pass
            self.prog.close()
            self.prog.deleteLater()
            self.prog = None
        ed.exporting = False
        ed._exporter = None
        if err and err != "İptal edildi":
            QMessageBox.warning(ed, "Dışa aktarma", err)
        elif err:
            ed.statusBar().showMessage("Dışa aktarma iptal edildi (%d kare yazıldı)." % self.i, 6000)
        else:
            ed.statusBar().showMessage("Dışa aktarma tamam: %s" % self.target, 8000)
        self.deleteLater()
