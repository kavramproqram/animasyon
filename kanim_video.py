# -*- coding: utf-8 -*-
"""
Kavram Animasyon — arka plan kaynakları (video / görüntü / kare klasörü)

Neden çökmez?
  * Kareler ARKA PLAN iş parçacığında çözülür; arayüz hiçbir zaman video beklemez.
  * "Son istek kazanır": hızlı gezinirken eski istekler atlanır, kuyruk birikmez.
  * Ekran için küçültülmüş (proxy, en çok 1280 px) kare tutulur; 4K video bile az bellek yer kaplar.
  * Önbellek kare SAYISINA değil BELLEK BÜTÇESİNE göre sınırlanır (eski kod 48 tam çözünürlüklü kare tutuyordu).
  * Oynatırken ileriye doğru birkaç kare önceden çözülür (prefetch); kare yetişmezse en yakın kare gösterilir.
  * Kapatırken iş parçacığı durdurulur, bekletilir ve kaynak (VideoCapture) serbest bırakılır.
  * Dışa aktarma için ayrı bir okuyucu tam çözünürlükte ardışık okur.
"""

import os
import shutil
import threading
import subprocess

from PyQt5.QtCore import QObject, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QImage, QImageReader

from kanim_frames import (HAS_CV2, FrameCache, SeqReader, proxy_dims, natural_key, to_bgra, resize_bgr,
                          CACHE_BUDGET, PROXY_MAX_EDGE)

_ZOMBIES = []      # kapanması beklenen iş parçacıklarının referansı (QThread çalışırken yok edilmesin)
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff')


def _qimage_bytes(im):
    f = getattr(im, 'sizeInBytes', None)
    return int(f() if f else im.byteCount())


def bgra_to_qimage(a):
    """BGRA numpy dizisi -> QImage (Format_RGB32, veri kopyalanır)."""
    h, w = a.shape[:2]
    try:
        return QImage(a.data, w, h, int(a.strides[0]), QImage.Format_RGB32).copy()
    except TypeError:
        return QImage(a.tobytes(), w, h, int(a.strides[0]), QImage.Format_RGB32).copy()


# --------------------------------------------------------------------------------------
#  Arka plan çözücü iş parçacığı
# --------------------------------------------------------------------------------------
class _Decoder(QThread):
    frameReady = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, src):
        super().__init__()
        self.src = src
        self._cv = threading.Condition()
        self._req = None
        self._stop = False

    def request(self, idx, ahead, step):
        with self._cv:
            self._req = (idx, ahead, step)
            self._cv.notify()

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify()

    def _pending(self):
        with self._cv:
            return self._req is not None or self._stop

    def run(self):
        try:
            while True:
                with self._cv:
                    while self._req is None and not self._stop:
                        self._cv.wait()
                    if self._stop:
                        break
                    idx, ahead, step = self._req
                    self._req = None
                order = [idx] + [idx + step * j for j in range(1, ahead + 1)]
                for i in order:
                    if i < 0 or i >= self.src.count:
                        continue
                    if self.src.cache.has(i):
                        continue
                    if i != idx and self._pending():     # yeni istek geldi: önceden yüklemeyi bırak
                        break
                    try:
                        img = self.src.decode(i)
                    except Exception as ex:               # çözücü hatası arayüzü asla düşürmez
                        self.failed.emit("%s" % ex)
                        break
                    if img is None or img.isNull():
                        continue
                    self.src.cache.put(i, img)
                    self.frameReady.emit(i)
        finally:
            try:
                self.src.release()
            except Exception:
                pass


# --------------------------------------------------------------------------------------
#  Kaynak taban sınıfı
# --------------------------------------------------------------------------------------
class BGSource(QObject):
    frameReady = pyqtSignal(int)      # çözülen kare numarası (ana iş parçacığında alınır)
    failed = pyqtSignal(str)
    kind = "none"

    def __init__(self):
        super().__init__()
        self.path = ""
        self.count = 1
        self.w = 0
        self.h = 0
        self.fps = None
        self.note = ""
        self.cache = FrameCache(CACHE_BUDGET, size_of=_qimage_bytes)
        self._dec = None
        self._last = None
        self.closed = False

    def start_decoder(self):
        self._dec = _Decoder(self)
        self._dec.frameReady.connect(self.frameReady)
        self._dec.failed.connect(self.failed)
        self._dec.start()

    # --- ana iş parçacığından çağrılır: asla bloklamaz --------------------------------------
    def get(self, idx, ahead=0, step=1):
        if self.closed or idx < 0 or idx >= self.count:
            return None
        img = self.cache.get(idx)
        dec = self._dec
        if img is None:
            if dec is not None:
                dec.request(idx, ahead, step)
            img = self.cache.nearest(idx, 12) or self._last
        elif ahead and dec is not None:
            dec.request(idx, ahead, step)
        if img is not None:
            self._last = img
        return img

    # --- alt sınıflar -----------------------------------------------------------------------
    def decode(self, idx):          # çözücü iş parçacığında çalışır
        return None

    def release(self):              # çözücü iş parçacığında (ya da kapanışta) çağrılır
        pass

    def open_reader(self):          # dışa aktarma için tam çözünürlüklü okuyucu
        return None

    def close(self):
        self.closed = True
        dec, self._dec = self._dec, None
        if dec is not None:
            for sig in (dec.frameReady, dec.failed):
                try:
                    sig.disconnect()
                except TypeError:
                    pass
            dec.stop()
            if dec.wait(3000):
                self.release()
            else:                   # takıldıysa iş parçacığı kendi finally bloğunda serbest bırakır
                _ZOMBIES.append(dec)
        else:
            self.release()
        self.cache.clear()
        self._last = None


# --------------------------------------------------------------------------------------
#  Görüntü
# --------------------------------------------------------------------------------------
class ImageBG(BGSource):
    kind = "image"

    def __init__(self, path):
        super().__init__()
        self.path = path
        img = QImage(path)
        if img.isNull():
            raise ValueError("Görüntü açılamadı")
        self.w, self.h, self.count = img.width(), img.height(), 1
        pw, ph = proxy_dims(self.w, self.h)
        if (pw, ph) != (self.w, self.h):
            from PyQt5.QtCore import Qt
            img = img.scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.note = "Önizleme küçültüldü (%d x %d); dışa aktarma tam çözünürlükte." % (pw, ph)
        self._img = img.convertToFormat(QImage.Format_RGB32)

    def get(self, idx, ahead=0, step=1):
        return None if self.closed else self._img

    def open_reader(self):
        return _ImageReader(self.path)

    def close(self):
        self.closed = True
        self._img = None


class _ImageReader:
    def __init__(self, path):
        self._img = QImage(path).convertToFormat(QImage.Format_RGB32)

    def read(self, idx):
        return self._img

    def close(self):
        self._img = None


# --------------------------------------------------------------------------------------
#  Kare klasörü (PNG/JPG dizisi)
# --------------------------------------------------------------------------------------
class FolderBG(BGSource):
    kind = "folder"

    def __init__(self, path, fps=None, proxy_only=False):
        super().__init__()
        self.path = path
        self.files = sorted((os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(IMAGE_EXT)),
                            key=natural_key)
        if not self.files:
            raise ValueError("Klasörde görüntü yok")
        r = QImageReader(self.files[0])
        sz = r.size()
        if not sz.isValid():
            im = QImage(self.files[0])
            if im.isNull():
                raise ValueError("İlk kare okunamadı")
            sz = im.size()
        self.w, self.h, self.count, self.fps = sz.width(), sz.height(), len(self.files), fps
        if proxy_only:
            self.note = "Video ffmpeg ile küçültülmüş karelere çevrildi (dışa aktarmada bu kareler kullanılır)."
        self.start_decoder()

    def decode(self, idx):
        r = QImageReader(self.files[idx])
        r.setAutoTransform(True)
        sz = r.size()
        if sz.isValid() and max(sz.width(), sz.height()) > PROXY_MAX_EDGE:
            pw, ph = proxy_dims(sz.width(), sz.height())
            r.setScaledSize(QSize(pw, ph))
        img = r.read()
        if img.isNull():
            return None
        return img.convertToFormat(QImage.Format_RGB32)

    def open_reader(self):
        return _FolderReader(self.files)


class _FolderReader:
    def __init__(self, files):
        self.files = files

    def read(self, idx):
        idx = max(0, min(len(self.files) - 1, idx))
        img = QImage(self.files[idx])
        return None if img.isNull() else img.convertToFormat(QImage.Format_RGB32)

    def close(self):
        pass


# --------------------------------------------------------------------------------------
#  Video (opencv)
# --------------------------------------------------------------------------------------
class VideoBG(BGSource):
    kind = "video"

    def __init__(self, path):
        super().__init__()
        if not HAS_CV2:
            raise RuntimeError("opencv yok")
        self.path = path
        rd = SeqReader(path)
        try:
            n, w, h, fps = rd.info()
            fr = rd.read_bgr(0)
            if fr is None:
                raise ValueError("Video karesi çözülemedi (codec desteklenmiyor olabilir)")
            h, w = fr.shape[:2]
            if n <= 1:                         # bazı kapsayıcılar kare sayısını bildirmez
                n = rd.count_by_grab()
                first = rd.read_bgr(0)
                if first is not None:
                    fr = first
        except Exception:
            rd.release()
            raise
        self._rd = rd
        self.count = max(1, n)
        self.w, self.h = w, h
        self.fps = fps if fps and fps > 0 else None
        self.pw, self.ph = proxy_dims(w, h)
        if (self.pw, self.ph) != (w, h):
            self.note = "Önizleme küçültüldü (%d x %d); dışa aktarma tam çözünürlükte." % (self.pw, self.ph)
        self.cache.put(0, self._proxy(fr))
        self.start_decoder()

    def _proxy(self, fr):
        return bgra_to_qimage(to_bgra(resize_bgr(fr, self.pw, self.ph)))

    def decode(self, idx):
        rd = self._rd
        if rd is None:
            return None
        fr = rd.read_bgr(idx)
        if fr is None:
            if 0 < idx >= self.count - 3:      # sondaki sahte kareler: sayıyı düzelt
                self.count = idx
            return None
        return self._proxy(fr)

    def release(self):
        rd, self._rd = self._rd, None
        if rd is not None:
            rd.release()

    def open_reader(self):
        return _VideoReader(self.path)


class _VideoReader:
    def __init__(self, path):
        self._rd = SeqReader(path)

    def read(self, idx):
        fr = self._rd.read_bgr(idx)
        if fr is None:
            return None
        return bgra_to_qimage(to_bgra(fr))

    def close(self):
        self._rd.release()


# --------------------------------------------------------------------------------------
#  opencv yoksa / codec açılamıyorsa ffmpeg yedeği (arka plan iş parçacığında, iptal edilebilir)
# --------------------------------------------------------------------------------------
class FfmpegExtractThread(QThread):
    def __init__(self, path, outdir):
        super().__init__()
        self.path, self.outdir = path, outdir
        self.ok = False
        self.error = ""

    def run(self):
        ff = shutil.which("ffmpeg")
        if not ff:
            self.error = "ffmpeg bulunamadı"
            return
        cmd = [ff, "-y", "-v", "error", "-i", self.path, "-an",
               "-vf", "scale='min(%d\\,iw)':-2" % PROXY_MAX_EDGE,
               "-q:v", "3", os.path.join(self.outdir, "f_%06d.jpg")]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while p.poll() is None:
                if self.isInterruptionRequested():
                    p.terminate()
                    try:
                        p.wait(3)
                    except Exception:
                        p.kill()
                    self.error = "İptal edildi"
                    return
                self.msleep(100)
            self.ok = (p.returncode == 0)
            if not self.ok:
                self.error = "ffmpeg hata kodu %s" % p.returncode
        except Exception as ex:
            self.error = str(ex)
