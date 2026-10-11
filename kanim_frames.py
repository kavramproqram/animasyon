# -*- coding: utf-8 -*-
"""
Kavram Animasyon — kare okuma katmanı (Qt gerektirmez)

Video / görüntü karelerini güvenli ve hafif okumak için:
  * FrameCache   : bayt bütçeli LRU önbellek (kare SAYISINA değil BELLEĞE göre sınırlar)
  * SeqReader    : cv2.VideoCapture sarmalayıcı; ardışık okumada seek yapmaz, kısa atlamada
                   grab() ile ilerler, uzak atlamada seek eder
  * proxy_dims   : ekran için küçültülmüş (proxy) boyut hesabı
  * natural_key  : f_2 < f_10 doğal dosya sıralaması

ai_editor.py'deki kare kare gezinme mantığıyla aynı fikirler: bir seferde tek kare, gereksiz
yeniden yükleme yok, kaynaklar kapatılırken açıkça serbest bırakılır.
"""

import re
import threading
from collections import OrderedDict

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except Exception:  # opencv yoksa ffmpeg yedeği kullanılır
    cv2 = None
    np = None
    HAS_CV2 = False

# ÇÖKME ÖNLEMİ: "opencv-python" (GUI sürümü) içe aktarılırken kendi Qt eklenti yolunu ortam
# değişkenine yazar. PyQt5 sonradan bu yolu okuyup uyumsuz eklenti yükler ve uygulama
# "Could not load the Qt platform plugin" ile ya da doğrudan çöker. QApplication oluşmadan önce siliyoruz.
import os as _os
for _k in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_FONTDIR"):
    if "cv2" in _os.environ.get(_k, "").replace("\\", "/"):
        _os.environ.pop(_k, None)

PROXY_MAX_EDGE = 1280                 # ekran önizlemesi için uzun kenar üst sınırı (px)
CACHE_BUDGET = 160 * 1024 * 1024      # önbellek bütçesi (bayt)
SKIP_LIMIT = 30                       # bu kadar kareye kadar ileri atlama grab() ile yapılır


def proxy_dims(w, h, edge=PROXY_MAX_EDGE):
    m = max(w, h)
    if m <= edge or m <= 0:
        return max(1, w), max(1, h)
    s = edge / float(m)
    return max(1, int(round(w * s))), max(1, int(round(h * s)))


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


class FrameCache:
    """İş parçacığı güvenli, bayt bütçeli LRU önbellek."""

    def __init__(self, budget=CACHE_BUDGET, size_of=None):
        self.budget = int(budget)
        self._size_of = size_of or (lambda o: int(getattr(o, 'nbytes', 0)))
        self._d = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._d)

    @property
    def bytes_used(self):
        return self._bytes

    def get(self, key):
        with self._lock:
            v = self._d.get(key)
            if v is not None:
                self._d.move_to_end(key)
            return v

    def has(self, key):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return True
            return False

    def put(self, key, value):
        sz = self._size_of(value)
        with self._lock:
            old = self._d.pop(key, None)
            if old is not None:
                self._bytes -= self._size_of(old)
            self._d[key] = value
            self._bytes += sz
            while self._bytes > self.budget and len(self._d) > 1:
                _, ev = self._d.popitem(last=False)
                self._bytes -= self._size_of(ev)

    def nearest(self, key, radius=12):
        """Anahtara en yakın önbellekteki kareyi (önce geçmiş) döndürür."""
        with self._lock:
            for d in range(1, radius + 1):
                for k in (key - d, key + d):
                    v = self._d.get(k)
                    if v is not None:
                        return v
        return None

    def clear(self):
        with self._lock:
            self._d.clear()
            self._bytes = 0


class SeqReader:
    """cv2.VideoCapture üzerinde kare numarasıyla okuma. Tek bir iş parçacığından kullanılmalıdır."""

    def __init__(self, path):
        if not HAS_CV2:
            raise RuntimeError("opencv yok")
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            self.cap.release()
            raise ValueError("Video açılamadı")
        self.pos = 0          # bir sonraki read() hangi kareyi okuyacak

    def read_bgr(self, idx):
        """idx. kareyi BGR numpy dizisi olarak döndürür; okunamazsa None."""
        cap = self.cap
        if cap is None:
            return None
        if idx != self.pos:
            gap = idx - self.pos
            # pos < 0: konum bilinmiyor (önceki okuma başarısız) -> her zaman seek et
            if self.pos >= 0 and 0 < gap <= SKIP_LIMIT:
                for _ in range(gap):
                    if not cap.grab():
                        self.pos = -1
                        return None
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            self.pos = idx
        ok, fr = cap.read()
        if not ok or fr is None:
            self.pos = -1
            return None
        self.pos = idx + 1
        return fr

    def info(self):
        c = self.cap
        return (int(c.get(cv2.CAP_PROP_FRAME_COUNT)), int(c.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(c.get(cv2.CAP_PROP_FRAME_HEIGHT)), float(c.get(cv2.CAP_PROP_FPS)))

    def count_by_grab(self):
        """Kare sayısı bilinmiyorsa baştan sona sayar (nadiren gerekir)."""
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        n = 0
        while self.cap.grab():
            n += 1
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.pos = 0
        return n

    def release(self):
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        self.cap = None


def to_bgra(fr):
    """Her türlü cv2 karesini BGRA (Qt Format_RGB32 ile bayt uyumlu) diziye çevirir."""
    if fr.ndim == 2:
        return cv2.cvtColor(fr, cv2.COLOR_GRAY2BGRA)
    if fr.shape[2] == 4:
        return np.ascontiguousarray(fr)
    return cv2.cvtColor(fr, cv2.COLOR_BGR2BGRA)


def resize_bgr(fr, w, h):
    if fr.shape[1] == w and fr.shape[0] == h:
        return fr
    return cv2.resize(fr, (w, h), interpolation=cv2.INTER_AREA)
