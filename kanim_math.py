# -*- coding: utf-8 -*-
"""
Kavram Animasyon — saf matematik katmanı (Qt gerektirmez, tek başına test edilebilir)

  * Sabitler (grid sınırları, çözünürlük listeleri)
  * Güvenli ifade çözücü (eval kullanmaz)
  * Nokta sadeleştirme (radyal inceltme + Ramer-Douglas-Peucker)
  * Yumuşatma (easing) fonksiyonları
"""

import ast
import math
from collections import OrderedDict

APP_NAME = "Kavram Animasyon Stüdyosu"
FILE_EXT = ".kanim"

# --------------------------------------------------------------------------------------
#  Grid / tuval sınırları  (çok küçük grid sistemi yorar -> alt sınır zorunlu)
# --------------------------------------------------------------------------------------
MIN_GRID = 8                # px  — grid hücresi bundan küçük olamaz
MAX_GRID = 1000             # px
MAX_GRID_CELLS = 320        # bir eksende izin verilen en çok hücre sayısı
MIN_GRID_SCREEN_PX = 8      # ekranda iki çizgi arası bundan darsa çizgiler otomatik seyreltilir
MIN_CANVAS = 16
MAX_CANVAS = 16000


def min_grid_for(width, height):
    """Verilen tuval boyutu için izin verilen en küçük grid (px)."""
    biggest = max(int(width), int(height), 1)
    return max(MIN_GRID, int(math.ceil(biggest / float(MAX_GRID_CELLS))))


def clamp_grid(value, width, height):
    return max(min_grid_for(width, height), min(MAX_GRID, int(value)))


# --------------------------------------------------------------------------------------
#  Çözünürlük ön ayarları (Kavram Drawing_editor.py -> AspectRatioDialog listesi)
# --------------------------------------------------------------------------------------
RESOLUTION_GROUPS = OrderedDict([
    ("Varsayılan", [
        ("Klasik Kavram (1100 x 600)", 1100, 600),
        ("Standart Full HD (1920 x 1080)", 1920, 1080),
        ("Kare Tuval (1080 x 1080)", 1080, 1080),
    ]),
    ("Geniş Ekran (16:9)", [
        ("3840 x 2160 - 4K Ultra HD", 3840, 2160),
        ("2560 x 1440 - 2K / QHD", 2560, 1440),
        ("1920 x 1080 - Full HD", 1920, 1080),
        ("1280 x 720 - HD", 1280, 720),
    ]),
    ("Dikey & Sosyal Medya", [
        ("1080 x 1920 - Reels & TikTok", 1080, 1920),
        ("1080 x 1350 - Instagram Post 4:5", 1080, 1350),
        ("1080 x 1080 - Kare Post 1:1", 1080, 1080),
    ]),
    ("Kitap, Manga & Yayın", [
        ("2480 x 3508 - A4 Baskı / PDF", 2480, 3508),
        ("1748 x 2480 - A5 Kitap / PDF", 1748, 2480),
        ("1200 x 1600 - 3:4 Dijital Manga", 1200, 1600),
        ("1500 x 2100 - Yüksek Çözünürlüklü Manga", 1500, 2100),
        ("800 x 1280 - Webtoon Panel Parçası", 800, 1280),
    ]),
    ("Özel Boyut", []),
])


def find_preset(width, height):
    """(grup, indeks) döndürür; eşleşme yoksa None."""
    for group, items in RESOLUTION_GROUPS.items():
        for i, (_, w, h) in enumerate(items):
            if w == width and h == height:
                return group, i
    return None


# --------------------------------------------------------------------------------------
#  Güvenli matematik ifadesi çözücü  (eval KULLANMAZ; sadece izinli düğümler)
# --------------------------------------------------------------------------------------
def _sign(v):
    return (v > 0) - (v < 0)


SAFE_FUNCS = {
    'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
    'asin': math.asin, 'acos': math.acos, 'atan': math.atan, 'atan2': math.atan2,
    'sinh': math.sinh, 'cosh': math.cosh, 'tanh': math.tanh,
    'sqrt': math.sqrt, 'exp': math.exp, 'log': math.log, 'ln': math.log, 'log10': math.log10,
    'abs': abs, 'floor': math.floor, 'ceil': math.ceil, 'sign': _sign,
    'min': min, 'max': max, 'pow': math.pow, 'radians': math.radians, 'degrees': math.degrees,
    'fmod': math.fmod,
}
SAFE_CONSTS = {'pi': math.pi, 'e': math.e, 'tau': math.tau}
MAX_EXPR_LEN = 400


class SafeExpr:
    """'3*sin(x)+x^2/10' gibi ifadeleri güvenle hesaplar."""

    def __init__(self, text, variables):
        text = (text or "").strip().replace('^', '**')
        if not text:
            raise ValueError("İfade boş")
        if len(text) > MAX_EXPR_LEN:
            raise ValueError("İfade çok uzun")
        self.vars = set(variables)
        self.tree = ast.parse(text, mode='eval')
        self._check(self.tree.body)

    def _check(self, n):
        if isinstance(n, ast.Constant):
            if isinstance(n.value, bool) or not isinstance(n.value, (int, float)):
                raise ValueError("Sadece sayı kullanılabilir")
        elif isinstance(n, ast.BinOp):
            if not isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv, ast.Pow)):
                raise ValueError("Desteklenmeyen işlem")
            self._check(n.left)
            self._check(n.right)
        elif isinstance(n, ast.UnaryOp):
            if not isinstance(n.op, (ast.UAdd, ast.USub)):
                raise ValueError("Desteklenmeyen işlem")
            self._check(n.operand)
        elif isinstance(n, ast.Name):
            if n.id not in self.vars and n.id not in SAFE_CONSTS:
                raise ValueError("Bilinmeyen isim: %s" % n.id)
        elif isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name) or n.func.id not in SAFE_FUNCS or n.keywords:
                raise ValueError("Bilinmeyen fonksiyon")
            for a in n.args:
                self._check(a)
        else:
            raise ValueError("Geçersiz ifade")

    def _ev(self, n, env):
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.BinOp):
            a = self._ev(n.left, env)
            b = self._ev(n.right, env)
            op = n.op
            if isinstance(op, ast.Add):
                return a + b
            if isinstance(op, ast.Sub):
                return a - b
            if isinstance(op, ast.Mult):
                return a * b
            if isinstance(op, ast.Div):
                return a / b
            if isinstance(op, ast.Mod):
                return a % b
            if isinstance(op, ast.FloorDiv):
                return a // b
            if abs(b) > 200:
                raise OverflowError("Üs çok büyük")
            return math.pow(a, b)
        if isinstance(n, ast.UnaryOp):
            v = self._ev(n.operand, env)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Name):
            if n.id in env:
                return env[n.id]
            return SAFE_CONSTS[n.id]
        if isinstance(n, ast.Call):
            return float(SAFE_FUNCS[n.func.id](*[self._ev(a, env) for a in n.args]))
        raise ValueError("Geçersiz ifade")

    def __call__(self, **env):
        return self._ev(self.tree.body, env)


# --------------------------------------------------------------------------------------
#  Nokta listesi yardımcıları
# --------------------------------------------------------------------------------------
def thin_points(pts, eps):
    """Birbirine eps'ten yakın ardışık noktaları atar (O(n)). Son nokta korunur."""
    if len(pts) < 3:
        return list(pts)
    out = [pts[0]]
    e2 = eps * eps
    for p in pts[1:-1]:
        dx = p[0] - out[-1][0]
        dy = p[1] - out[-1][1]
        if dx * dx + dy * dy >= e2:
            out.append(p)
    out.append(pts[-1])
    return out


def rdp(pts, eps):
    """Ramer-Douglas-Peucker sadeleştirme. Önce O(n) inceltme yapılır; böylece en kötü durum da hızlıdır."""
    pts = thin_points(pts, eps * 0.5)
    n = len(pts)
    if n < 3:
        return list(pts)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        ax, ay = pts[s]
        bx, by = pts[e]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        dmax, idx = 0.0, -1
        for i in range(s + 1, e):
            px, py = pts[i]
            if L2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps and idx > 0:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [p for p, k in zip(pts, keep) if k]


def parse_pts(text):
    pts = []
    for chunk in text.replace('\n', ';').split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        a = chunk.replace(' ', ',').split(',')
        a = [s for s in a if s != '']
        if len(a) != 2:
            raise ValueError("Nokta biçimi: x,y; x,y")
        pts.append([float(a[0]), float(a[1])])
    return pts


def fmt_pts(pts):
    return "; ".join("%g,%g" % (p[0], p[1]) for p in pts)


# --------------------------------------------------------------------------------------
#  Yumuşatma
# --------------------------------------------------------------------------------------
def ease_val(t, mode):
    if mode == 'linear':
        return t
    if mode == 'ease':
        return t * t * (3 - 2 * t)
    if mode == 'in':
        return t * t
    if mode == 'out':
        return 1 - (1 - t) * (1 - t)
    if mode == 'hold':
        return 0.0
    return t


EASES = [('linear', 'Doğrusal'), ('ease', 'Yumuşak (giriş-çıkış)'), ('in', 'Yavaş başla'),
         ('out', 'Yavaş bitir'), ('hold', 'Sabit tut')]
