# -*- coding: utf-8 -*-
"""
Kavram Animasyon — nesne modeli (Qt gerektirir)

Her nesne matematiksel parametrelerle tanımlıdır; yerel (orijin merkezli) yolu bu parametrelerden
üretilir ve önbelleğe alınır. Hareket, anahtar karelerle (keyframe) tanımlanır.
"""

import math
import copy
import bisect

from PyQt5.QtGui import QPainterPath, QTransform, QColor
from PyQt5.QtCore import QRectF, QPointF

from kanim_math import SafeExpr, ease_val, clamp_grid

# --------------------------------------------------------------------------------------
#  Geometri
# --------------------------------------------------------------------------------------


def catmull_path(pts, closed=False, tension=1.0):
    """Noktalardan geçen yumuşak (Catmull-Rom -> kübik Bezier) eğri."""
    path = QPainterPath()
    n = len(pts)
    if n < 1:
        return path
    path.moveTo(pts[0][0], pts[0][1])
    if n == 1:
        return path
    if n == 2 and not closed:
        path.lineTo(pts[1][0], pts[1][1])
        return path
    k = tension / 6.0

    def P(i):
        if closed:
            return pts[i % n]
        return pts[max(0, min(n - 1, i))]

    for i in range(n if closed else n - 1):
        p0, p1, p2, p3 = P(i - 1), P(i), P(i + 1), P(i + 2)
        c1x = p1[0] + (p2[0] - p0[0]) * k
        c1y = p1[1] + (p2[1] - p0[1]) * k
        c2x = p2[0] - (p3[0] - p1[0]) * k
        c2y = p2[1] - (p3[1] - p1[1]) * k
        path.cubicTo(c1x, c1y, c2x, c2y, p2[0], p2[1])
    if closed:
        path.closeSubpath()
    return path


def sample_curve(fx, fy, t0, t1, steps, unit):
    """x(t), y(t) fonksiyonlarını örnekleyip yol üretir. Matematikte y yukarı olduğu için y ters çevrilir."""
    path = QPainterPath()
    steps = max(2, min(int(steps), 20000))
    down = False
    last_y = 0.0
    for i in range(steps + 1):
        t = t0 + (t1 - t0) * i / steps
        try:
            x = fx(t)
            y = fy(t)
        except Exception:
            down = False
            continue
        if not (math.isfinite(x) and math.isfinite(y)) or abs(x) > 1e5 or abs(y) > 1e5:
            down = False
            continue
        px, py = x * unit, -y * unit
        if down and abs(py - last_y) > 6000:  # tan(x) gibi kopukluklar
            down = False
        if down:
            path.lineTo(px, py)
        else:
            path.moveTo(px, py)
            down = True
        last_y = py
    return path


# --------------------------------------------------------------------------------------
#  Nesne modeli
# --------------------------------------------------------------------------------------
F, I, B, S, P, PRO = 'float', 'int', 'bool', 'str', 'pts', 'pts_ro'

PSCHEMA = {
    'line': [('x1', 'Başlangıç X', F), ('y1', 'Başlangıç Y', F), ('x2', 'Bitiş X', F), ('y2', 'Bitiş Y', F)],
    'rect': [('w', 'Genişlik', F), ('h', 'Yükseklik', F), ('r', 'Köşe yarıçapı', F)],
    'ellipse': [('rx', 'Yarıçap X', F), ('ry', 'Yarıçap Y', F)],
    'polygon': [('n', 'Kenar sayısı', I), ('r', 'Yarıçap', F)],
    'star': [('n', 'Uç sayısı', I), ('r', 'Dış yarıçap', F), ('r2', 'İç yarıçap', F)],
    'spline': [('pts', 'Noktalar (x,y; x,y; ...)', P), ('closed', 'Kapalı', B), ('tension', 'Gerilim', F)],
    'freehand': [('pts', 'Noktalar', PRO)],
    'func': [('expr', 'y = f(x)', S), ('x0', 'x başlangıç', F), ('x1', 'x bitiş', F),
             ('steps', 'Adım sayısı', I), ('unit', '1 birim = px', F)],
    'param': [('xexpr', 'x(t) =', S), ('yexpr', 'y(t) =', S), ('t0', 't başlangıç', F), ('t1', 't bitiş', F),
              ('steps', 'Adım sayısı', I), ('unit', '1 birim = px', F)],
    'polar': [('expr', 'r(a) =', S), ('a0', 'a başlangıç', F), ('a1', 'a bitiş', F),
              ('steps', 'Adım sayısı', I), ('unit', '1 birim = px', F)],
}
DEFAULTS = {
    'line': {'x1': -60, 'y1': 0, 'x2': 60, 'y2': 0},
    'rect': {'w': 120, 'h': 80, 'r': 0},
    'ellipse': {'rx': 60, 'ry': 40},
    'polygon': {'n': 5, 'r': 60},
    'star': {'n': 5, 'r': 60, 'r2': 25},
    'spline': {'pts': [[-80, 0], [-30, -50], [30, 50], [80, 0]], 'closed': False, 'tension': 1.0},
    'freehand': {'pts': [], 'closed': False, 'tension': 1.0},
    'func': {'expr': '3*sin(x)', 'x0': -10, 'x1': 10, 'steps': 300, 'unit': 20},
    'param': {'xexpr': '5*cos(t)', 'yexpr': '5*sin(t)', 't0': 0, 't1': 6.2832, 'steps': 300, 'unit': 20},
    'polar': {'expr': '3*(1+cos(a))', 'a0': 0, 'a1': 6.2832, 'steps': 400, 'unit': 20},
}
KIND_NAMES = {
    'line': 'Çizgi', 'rect': 'Dikdörtgen', 'ellipse': 'Elips', 'polygon': 'Çokgen', 'star': 'Yıldız',
    'spline': 'Eğri', 'freehand': 'Serbest', 'func': 'Fonksiyon', 'param': 'Parametrik', 'polar': 'Kutupsal',
}
MATH_PRESETS = [
    ("Sinüs dalgası", 'func', {'expr': '3*sin(x)', 'x0': -10, 'x1': 10}),
    ("Parabol", 'func', {'expr': 'x^2/4', 'x0': -6, 'x1': 6}),
    ("Sönümlü salınım", 'func', {'expr': '6*exp(-0.3*abs(x))*cos(3*x)', 'x0': -10, 'x1': 10}),
    ("Daire", 'param', {'xexpr': '5*cos(t)', 'yexpr': '5*sin(t)', 't0': 0, 't1': 6.2832}),
    ("Spiral", 'param', {'xexpr': 't*cos(t)/3', 'yexpr': 't*sin(t)/3', 't0': 0, 't1': 25}),
    ("Lissajous", 'param', {'xexpr': '6*sin(3*t)', 'yexpr': '6*sin(2*t)', 't0': 0, 't1': 6.2832}),
    ("Kalp", 'param', {'xexpr': '0.4*16*sin(t)^3',
                       'yexpr': '0.4*(13*cos(t)-5*cos(2*t)-2*cos(3*t)-cos(4*t))', 't0': 0, 't1': 6.2832}),
    ("Kardiyoid", 'polar', {'expr': '3*(1+cos(a))', 'a0': 0, 'a1': 6.2832}),
    ("Gül eğrisi (5 yaprak)", 'polar', {'expr': '6*cos(5*a)', 'a0': 0, 'a1': 6.2832}),
    ("Arşimet spirali", 'polar', {'expr': 'a/2', 'a0': 0, 'a1': 31.4}),
]


def build_path(kind, p):
    """Nesnenin yerel (origin merkezli) QPainterPath'ini üretir. Hata varsa (path, mesaj) döner."""
    path = QPainterPath()
    err = ""
    try:
        if kind == 'line':
            path.moveTo(p['x1'], p['y1'])
            path.lineTo(p['x2'], p['y2'])
        elif kind == 'rect':
            w, h, r = p['w'], p['h'], max(0.0, p.get('r', 0))
            rect = QRectF(-w / 2.0, -h / 2.0, w, h)
            if r > 0:
                path.addRoundedRect(rect, r, r)
            else:
                path.addRect(rect)
        elif kind == 'ellipse':
            path.addEllipse(QPointF(0, 0), abs(p['rx']), abs(p['ry']))
        elif kind == 'polygon':
            n = max(3, min(500, int(p['n'])))
            r = p['r']
            for i in range(n):
                a = math.radians(-90 + 360.0 * i / n)
                x, y = r * math.cos(a), r * math.sin(a)
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
            path.closeSubpath()
        elif kind == 'star':
            n = max(3, min(500, int(p['n'])))
            r1, r2 = p['r'], p['r2']
            for i in range(n * 2):
                a = math.radians(-90 + 180.0 * i / n)
                rr = r1 if i % 2 == 0 else r2
                x, y = rr * math.cos(a), rr * math.sin(a)
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
            path.closeSubpath()
        elif kind in ('spline', 'freehand'):
            path = catmull_path(p.get('pts', []), bool(p.get('closed', False)), float(p.get('tension', 1.0)))
        elif kind == 'func':
            f = SafeExpr(p['expr'], ['x'])
            path = sample_curve(lambda t: t, lambda t: f(x=t), p['x0'], p['x1'], p['steps'], p['unit'])
        elif kind == 'param':
            fx = SafeExpr(p['xexpr'], ['t'])
            fy = SafeExpr(p['yexpr'], ['t'])
            path = sample_curve(lambda t: fx(t=t), lambda t: fy(t=t), p['t0'], p['t1'], p['steps'], p['unit'])
        elif kind == 'polar':
            f = SafeExpr(p['expr'], ['a', 't'])
            u = p['unit']
            path = QPainterPath()
            steps = max(2, min(int(p['steps']), 20000))
            down = False
            for i in range(steps + 1):
                a = p['a0'] + (p['a1'] - p['a0']) * i / steps
                try:
                    r = f(a=a, t=a)
                except Exception:
                    down = False
                    continue
                if not math.isfinite(r) or abs(r) > 1e5:
                    down = False
                    continue
                x, y = r * math.cos(a) * u, -r * math.sin(a) * u
                if down:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
                    down = True
    except Exception as e:  # noqa
        err = str(e) or e.__class__.__name__
        path = QPainterPath()
    return path, err


STATE_KEYS = ('x', 'y', 'rot', 'sx', 'sy')


class Obj:
    _next_id = 1

    def __init__(self, kind, params=None, name=None):
        self.id = Obj._next_id
        Obj._next_id += 1
        self.kind = kind
        self.params = copy.deepcopy(DEFAULTS[kind])
        if params:
            self.params.update(copy.deepcopy(params))
        self.name = name or "%s %d" % (KIND_NAMES[kind], self.id)
        self.stroke = QColor("#ffffff")
        self.fill = QColor("#3a7bd5")
        self.fill_on = False
        self.width = 3.0
        self.visible = True
        self.locked = False
        self.base = {'x': 0.0, 'y': 0.0, 'rot': 0.0, 'sx': 1.0, 'sy': 1.0}
        self.keys = {}          # kare -> {'x','y','rot','sx','sy','ease'}
        self.ls = 0             # yaşam başlangıç karesi
        self.le = -1            # yaşam bitiş karesi (-1 = son kareye kadar)
        self._path = None
        self._wp = None         # (durum anahtarı, yol nesnesi, dünya yolu) önbelleği
        self._err = ""

    # --- geometri -----------------------------------------------------------------
    def touch(self):
        self._path = None
        self._wp = None

    def path(self):
        if self._path is None:
            self._path, self._err = build_path(self.kind, self.params)
        return self._path

    def alive(self, f):
        return f >= self.ls and (self.le < 0 or f <= self.le)

    def state(self, f):
        if not self.keys:
            return dict(self.base)
        ks = sorted(self.keys)
        if f <= ks[0]:
            return {k: self.keys[ks[0]][k] for k in STATE_KEYS}
        if f >= ks[-1]:
            return {k: self.keys[ks[-1]][k] for k in STATE_KEYS}
        i = bisect.bisect_right(ks, f) - 1
        a, b = self.keys[ks[i]], self.keys[ks[i + 1]]
        t = (f - ks[i]) / float(ks[i + 1] - ks[i])
        t = ease_val(t, a.get('ease', 'linear'))
        return {k: a[k] + (b[k] - a[k]) * t for k in STATE_KEYS}

    def transform(self, f):
        s = self.state(f)
        return QTransform().translate(s['x'], s['y']).rotate(s['rot']).scale(s['sx'], s['sy'])

    def world_path(self, f):
        """Dünya koordinatlı yol. Durum değişmedikçe önbellekten verilir (soğan kabuğu / fare hareketi hızlanır)."""
        s = self.state(f)
        key = (s['x'], s['y'], s['rot'], s['sx'], s['sy'])
        local = self.path()
        c = self._wp
        if c is not None and c[0] == key and c[1] is local:
            return c[2]
        wp = QTransform().translate(s['x'], s['y']).rotate(s['rot']).scale(s['sx'], s['sy']).map(local)
        self._wp = (key, local, wp)
        return wp

    # --- kayıt --------------------------------------------------------------------
    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'kind': self.kind, 'params': copy.deepcopy(self.params),
            'stroke': self.stroke.name(QColor.HexArgb), 'fill': self.fill.name(QColor.HexArgb),
            'fill_on': self.fill_on, 'width': self.width, 'visible': self.visible, 'locked': self.locked,
            'base': dict(self.base), 'keys': {str(k): dict(v) for k, v in self.keys.items()},
            'ls': self.ls, 'le': self.le,
        }

    @staticmethod
    def from_dict(d):
        o = Obj.__new__(Obj)
        o.id = d['id']
        o.kind = d['kind']
        o.params = copy.deepcopy(d['params'])
        o.name = d.get('name', KIND_NAMES.get(o.kind, o.kind))
        o.stroke = QColor(d.get('stroke', '#ffffff'))
        o.fill = QColor(d.get('fill', '#3a7bd5'))
        o.fill_on = d.get('fill_on', False)
        o.width = d.get('width', 3.0)
        o.visible = d.get('visible', True)
        o.locked = d.get('locked', False)
        o.base = dict(d.get('base', {'x': 0, 'y': 0, 'rot': 0, 'sx': 1, 'sy': 1}))
        o.keys = {int(k): dict(v) for k, v in d.get('keys', {}).items()}
        o.ls = d.get('ls', 0)
        o.le = d.get('le', -1)
        o._path = None
        o._wp = None
        o._err = ""
        Obj._next_id = max(Obj._next_id, o.id + 1)
        return o

    def clone(self):
        d = self.to_dict()
        o = Obj.from_dict(d)
        o.id = Obj._next_id
        Obj._next_id += 1
        o.name = self.name + " kopya"
        return o


class Project:
    def __init__(self):
        self.width = 1100
        self.height = 600
        self.grid = 20
        self.fps = 12
        self.frames = 48
        self.bg_color = QColor("#000000")
        self.grid_color = QColor("#3c3c3c")
        self.objects = []

    def fix_grid(self):
        """Grid'i tuval boyutuna göre izin verilen aralığa çeker (çok küçük grid sistemi yorar)."""
        self.grid = clamp_grid(self.grid, self.width, self.height)

    def meta(self):
        return {'width': self.width, 'height': self.height, 'grid': self.grid, 'fps': self.fps,
                'frames': self.frames, 'bg_color': self.bg_color.name(), 'grid_color': self.grid_color.name()}
