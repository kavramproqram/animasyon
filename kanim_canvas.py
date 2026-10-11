# -*- coding: utf-8 -*-
"""
Kavram Animasyon — çizim tuvali

Orijinal Canvas mimarisi korunmuştur (paint_scene ekran ve dışa aktarma için ortak). Farklar:
  * Grid yalnızca GÖRÜNEN alana çizilir ve ekranda çizgiler arası <8 px olursa seyreltilir.
    Grid boyutunun kendisi de tuval boyutuna göre alt sınırla (>=8 px) korunur.
  * Arka plan kareleri BLOKLAMADAN alınır (ed.bg.get): çözülmemişse en yakın kare gösterilir.
  * Kalem çiziminde önizleme O(1) eklenir (her fare hareketinde tüm eğri yeniden hesaplanmaz).
  * Tüm çizim try/finally ile korunur; hata olsa bile uygulama kapanmaz.
"""

import math

from PyQt5.QtCore import Qt, QPointF, QRectF, QLineF
from PyQt5.QtGui import (QPainter, QPen, QBrush, QColor, QPainterPathStroker, QPolygonF, QFont)
from PyQt5.QtWidgets import QWidget

from kanim_math import rdp, MIN_GRID_SCREEN_PX
from kanim_core import Obj, catmull_path

HANDLE_R = 6
MAX_PEN_POINTS = 8000


class Canvas(QWidget):
    def __init__(self, ed):
        super().__init__()
        self.ed = ed
        self.zoom = 1.0
        self.offset = QPointF(40, 40)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(400, 300)
        self.drag = None
        self.cursor_p = QPointF()
        self.spline_pts = []
        self._fitted = False

    # --- koordinatlar ---------------------------------------------------------------
    def to_proj(self, v):
        return QPointF((v.x() - self.offset.x()) / self.zoom, (v.y() - self.offset.y()) / self.zoom)

    def to_view(self, p):
        return QPointF(p.x() * self.zoom + self.offset.x(), p.y() * self.zoom + self.offset.y())

    def snap(self, p, mods=Qt.NoModifier):
        if self.ed.snap and not (mods & Qt.ControlModifier):
            g = self.ed.proj.grid
            return QPointF(round(p.x() / g) * g, round(p.y() / g) * g)
        return QPointF(p)

    def fit_view(self):
        pr = self.ed.proj
        m = 40
        z = min((self.width() - m * 2) / float(pr.width), (self.height() - m * 2) / float(pr.height))
        self.zoom = max(0.02, z)
        self.offset = QPointF((self.width() - pr.width * self.zoom) / 2, (self.height() - pr.height * self.zoom) / 2)
        self.update()

    def resizeEvent(self, e):
        if not self._fitted and self.width() > 100:
            self._fitted = True
            self.fit_view()
        super().resizeEvent(e)

    def visible_rect(self):
        """Görünen alanın proje koordinatlarındaki karşılığı (tuvalle kesişimi)."""
        tl = self.to_proj(QPointF(0, 0))
        br = self.to_proj(QPointF(self.width(), self.height()))
        pr = self.ed.proj
        return QRectF(tl, br).normalized().intersected(QRectF(0, 0, pr.width, pr.height))

    # --- çizim ----------------------------------------------------------------------
    def draw_obj(self, p, o, f, ghost=None):
        if not o.visible or not o.alive(f):
            return
        wp = o.world_path(f)
        if wp.isEmpty():
            return
        if ghost is not None:
            p.setPen(QPen(ghost, max(1.0, o.width), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(wp)
            return
        if o.width <= 0 or o.stroke.alpha() == 0:
            p.setPen(Qt.NoPen)
        else:
            p.setPen(QPen(o.stroke, o.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QBrush(o.fill) if o.fill_on else Qt.NoBrush)
        p.drawPath(wp)

    def paint_bg(self, p, img, canvas_rect, smooth):
        if img is None or img.isNull():
            return
        ed = self.ed
        p.save()
        p.setOpacity(ed.bg_opacity)
        p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
        p.drawImage(self.bg_target(img, canvas_rect), img)
        p.restore()

    def paint_scene(self, p, f, with_grid=True, with_bg=True, ghosts=True, bg_img=None, view_rect=None,
                    zoom=1.0, smooth=True, alpha_bg=False):
        """Ekran ve dışa aktarma için ortak. p, proje koordinatlarında çizer.
        bg_img: verilmezse ve with_bg ise ed.bg'den bloklamadan alınır."""
        ed, pr = self.ed, self.ed.proj
        canvas_rect = QRectF(0, 0, pr.width, pr.height)
        if not alpha_bg:
            p.fillRect(canvas_rect, pr.bg_color)
        p.save()
        p.setClipRect(canvas_rect)
        img = None
        if with_bg and ed.bg is not None:
            img = bg_img if bg_img is not None else ed.bg_image_for(f)
        if img is not None and not ed.bg_above:
            self.paint_bg(p, img, canvas_rect, smooth)
        if with_grid:
            self.draw_grid(p, view_rect or canvas_rect, zoom)
        if ghosts and ed.onion and not ed.playing:
            for d in range(ed.onion_n, 0, -1):
                a = int(90 / d)
                for o in pr.objects:
                    if f - d >= 0:
                        self.draw_obj(p, o, f - d, ghost=QColor(255, 70, 70, a))
                    if f + d < pr.frames:
                        self.draw_obj(p, o, f + d, ghost=QColor(70, 255, 110, a))
        for o in pr.objects:
            self.draw_obj(p, o, f)
        if img is not None and ed.bg_above:
            self.paint_bg(p, img, canvas_rect, smooth)
        p.restore()

    def bg_target(self, img, cr):
        mode = self.ed.bg_fit
        iw, ih = max(1, img.width()), max(1, img.height())
        if mode == 'stretch':
            return QRectF(cr)
        s = min(cr.width() / iw, cr.height() / ih) if mode == 'fit' else max(cr.width() / iw, cr.height() / ih)
        w, h = iw * s, ih * s
        return QRectF((cr.width() - w) / 2, (cr.height() - h) / 2, w, h)

    def draw_grid(self, p, view, zoom):
        """Sadece 'view' içindeki çizgileri üretir; ekranda sık olursa seyreltir. Çizgi sayısı sınırlıdır."""
        pr = self.ed.proj
        g = float(max(1, pr.grid))
        k = 1
        while g * k * zoom < MIN_GRID_SCREEN_PX and k < (1 << 24):
            k *= 2
        step = g * k
        x0, x1 = max(0.0, view.left()), min(float(pr.width), view.right())
        y0, y1 = max(0.0, view.top()), min(float(pr.height), view.bottom())
        if x1 <= x0 or y1 <= y0:
            return
        minor, major = [], []
        for i in range(int(x0 // step), int(x1 // step) + 2):
            x = i * step
            if x > pr.width:
                break
            (major if i % 5 == 0 else minor).append(QLineF(x, y0, x, y1))
            if len(minor) + len(major) > 4000:
                break
        for i in range(int(y0 // step), int(y1 // step) + 2):
            y = i * step
            if y > pr.height:
                break
            (major if i % 5 == 0 else minor).append(QLineF(x0, y, x1, y))
            if len(minor) + len(major) > 8000:
                break
        gc = pr.grid_color
        p.save()
        p.setBrush(Qt.NoBrush)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(QPen(gc, 0))
        p.drawLines(minor)
        p.setPen(QPen(gc.lighter(165), 0))
        p.drawLines(major)
        p.restore()

    def paintEvent(self, e):
        ed, pr = self.ed, self.ed.proj
        p = QPainter(self)
        try:
            busy = ed.playing or (self.drag is not None)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.fillRect(self.rect(), QColor("#101010"))
            p.save()
            p.translate(self.offset)
            p.scale(self.zoom, self.zoom)
            self.paint_scene(p, ed.frame, with_grid=ed.show_grid, view_rect=self.visible_rect(), zoom=self.zoom,
                             smooth=not busy)
            self.draw_preview(p)
            p.restore()
            tl = self.to_view(QPointF(0, 0))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#777"), 1))
            p.drawRect(QRectF(tl, QPointF(tl.x() + pr.width * self.zoom, tl.y() + pr.height * self.zoom)))
            self.draw_selection(p)
            p.setPen(QColor("#9a9a9a"))
            p.setFont(QFont("Sans", 9))
            txt = "Kare %d / %d    %d%%    %s" % (ed.frame + 1, pr.frames, round(self.zoom * 100),
                                                 "OYNATILIYOR" if ed.playing else "")
            if ed.bg is not None and ed.bg.count > 1:
                bi = ed.frame - ed.bg_offset
                txt += "    Video karesi %d / %d" % (max(0, min(ed.bg.count - 1, bi)) + 1, ed.bg.count)
            p.drawText(10, 18, txt)
        finally:
            p.end()

    def draw_preview(self, p):
        d = self.drag
        ed = self.ed
        if ed.tool == 'spline' and self.spline_pts:
            pts = [list(q) for q in self.spline_pts]
            cp = self.snap(self.cursor_p)
            pts.append([cp.x(), cp.y()])
            p.setPen(QPen(QColor("#4fc3f7"), max(1.5, ed.cur_width), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(catmull_path(pts))
            p.setPen(QPen(QColor("#fff"), 0))
            p.setBrush(QColor("#4fc3f7"))
            for q in self.spline_pts:
                p.drawEllipse(QPointF(q[0], q[1]), 4 / self.zoom, 4 / self.zoom)
        if not d:
            return
        m = d['mode']
        if m == 'pen':
            poly = d['poly']
            if poly.size() > 1:
                p.setPen(QPen(ed.cur_stroke, ed.cur_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.setBrush(Qt.NoBrush)
                p.drawPolyline(poly)
        elif m == 'shape':
            o = self.make_shape(d['p0'], d['p1'], d['mods'])
            if o:
                self.draw_obj(p, o, ed.frame)
        elif m == 'marquee':
            r = QRectF(d['p0'], d['p1']).normalized()
            p.setPen(QPen(QColor("#4fc3f7"), 0, Qt.DashLine))
            p.setBrush(QColor(79, 195, 247, 30))
            p.drawRect(r)

    def sel_rect_view(self):
        ed = self.ed
        r = None
        for o in ed.selected_objs():
            if not o.alive(ed.frame):
                continue
            br = o.world_path(ed.frame).boundingRect()
            r = br if r is None else r.united(br)
        if r is None:
            return None
        v = QRectF(self.to_view(r.topLeft()), self.to_view(r.bottomRight())).normalized()
        return v.adjusted(-5, -5, 5, 5)

    def handle_points(self):
        v = self.sel_rect_view()
        if v is None or len(self.ed.selected_objs()) != 1:
            return v, None
        hp = {'tl': v.topLeft(), 'tr': v.topRight(), 'br': v.bottomRight(), 'bl': v.bottomLeft(),
              'rot': QPointF(v.center().x(), v.top() - 26)}
        return v, hp

    def draw_selection(self, p):
        if self.ed.tool != 'select':
            return
        v, hp = self.handle_points()
        if v is None:
            return
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#4fc3f7"), 1, Qt.DashLine))
        p.drawRect(v)
        if hp:
            p.drawLine(QPointF(v.center().x(), v.top()), hp['rot'])
            p.setPen(QPen(QColor("#4fc3f7"), 1))
            p.setBrush(QColor("#101010"))
            for k, q in hp.items():
                if k == 'rot':
                    p.drawEllipse(q, HANDLE_R, HANDLE_R)
                else:
                    p.drawRect(QRectF(q.x() - HANDLE_R + 1, q.y() - HANDLE_R + 1, (HANDLE_R - 1) * 2, (HANDLE_R - 1) * 2))
        p.setPen(QPen(QColor("#ffd24a"), 1))
        for o in self.ed.selected_objs():
            if o.alive(self.ed.frame):
                s = o.state(self.ed.frame)
                c = self.to_view(QPointF(s['x'], s['y']))
                p.drawLine(QPointF(c.x() - 5, c.y()), QPointF(c.x() + 5, c.y()))
                p.drawLine(QPointF(c.x(), c.y() - 5), QPointF(c.x(), c.y() + 5))

    # --- şekil oluşturma ---------------------------------------------------------------
    def make_shape(self, p0, p1, mods):
        ed = self.ed
        t = ed.tool
        dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
        o = None
        if t == 'line':
            if math.hypot(dx, dy) < 1:
                return None
            if mods & Qt.ShiftModifier:  # 15 derecelik açı kilidi
                L = math.hypot(dx, dy)
                a = round(math.atan2(dy, dx) / (math.pi / 12)) * (math.pi / 12)
                dx, dy = L * math.cos(a), L * math.sin(a)
                p1 = QPointF(p0.x() + dx, p0.y() + dy)
            mid = QPointF((p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2)
            o = Obj('line', {'x1': -dx / 2, 'y1': -dy / 2, 'x2': dx / 2, 'y2': dy / 2})
            o.base.update(x=mid.x(), y=mid.y())
        elif t in ('rect', 'ellipse'):
            if mods & Qt.ShiftModifier:
                s = max(abs(dx), abs(dy))
                dx = s if dx >= 0 else -s
                dy = s if dy >= 0 else -s
                p1 = QPointF(p0.x() + dx, p0.y() + dy)
            w, h = abs(dx), abs(dy)
            if w < 1 or h < 1:
                return None
            c = QPointF((p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2)
            o = Obj('rect', {'w': w, 'h': h, 'r': 0}) if t == 'rect' else Obj('ellipse', {'rx': w / 2, 'ry': h / 2})
            o.base.update(x=c.x(), y=c.y())
        elif t in ('polygon', 'star'):
            r = math.hypot(dx, dy)
            if r < 2:
                return None
            o = Obj('polygon', {'n': ed.sides, 'r': r}) if t == 'polygon' else \
                Obj('star', {'n': ed.sides, 'r': r, 'r2': r * 0.42})
            o.base.update(x=p0.x(), y=p0.y(), rot=math.degrees(math.atan2(dy, dx)) + 90)
        if o:
            o.stroke, o.fill, o.fill_on, o.width = ed.cur_stroke, ed.cur_fill, ed.cur_fill_on, ed.cur_width
        return o

    def finish_pen(self, pts):
        ed = self.ed
        if len(pts) < 2:
            return
        pts = rdp(pts, max(0.4, 0.8 / self.zoom))
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        loc = [[round(q[0] - cx, 2), round(q[1] - cy, 2)] for q in pts]
        o = Obj('freehand', {'pts': loc, 'closed': False, 'tension': 1.0})
        o.base.update(x=cx, y=cy)
        ed.add_object(o)

    def finish_spline(self, closed=False):
        pts = self.spline_pts
        self.spline_pts = []
        if len(pts) < 2:
            self.update()
            return
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        o = Obj('spline', {'pts': [[round(q[0] - cx, 2), round(q[1] - cy, 2)] for q in pts],
                           'closed': closed, 'tension': 1.0})
        o.base.update(x=cx, y=cy)
        self.ed.add_object(o)

    # --- fare -----------------------------------------------------------------------
    def hit_object(self, pp):
        ed = self.ed
        for o in reversed(ed.proj.objects):
            if not o.visible or o.locked or not o.alive(ed.frame):
                continue
            wp = o.world_path(ed.frame)
            if wp.isEmpty():
                continue
            tol = max(o.width / 2.0, 6.0 / self.zoom)
            if not wp.boundingRect().adjusted(-tol, -tol, tol, tol).contains(pp):
                continue                      # pahalı stroker'a girmeden ele
            st = QPainterPathStroker()
            st.setWidth(tol * 2)
            if st.createStroke(wp).contains(pp):
                return o
            if o.fill_on and wp.contains(pp):
                return o
        return None

    def mousePressEvent(self, e):
        self.setFocus()
        ed = self.ed
        pp = self.to_proj(e.pos())
        self.cursor_p = pp
        mods = e.modifiers()
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and ed.tool == 'pan'):
            self.drag = {'mode': 'pan', 'last': e.pos()}
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.RightButton:
            if ed.tool == 'spline' and self.spline_pts:
                self.finish_spline()
            return
        if e.button() != Qt.LeftButton:
            return
        if ed.playing:                       # oynatırken çizim başlatma (kararlılık)
            return
        t = ed.tool
        if t == 'select':
            v, hp = self.handle_points()
            if hp:
                for k, q in hp.items():
                    if QLineF(q, QPointF(e.pos())).length() <= HANDLE_R + 3:
                        o = ed.primary()
                        s = o.state(ed.frame)
                        self.drag = {'mode': 'rotate' if k == 'rot' else 'scale', 'obj': o, 'init': s,
                                     'pushed': False, 'start': pp}
                        return
            o = self.hit_object(pp)
            if o:
                if mods & Qt.ShiftModifier:
                    ids = list(ed.sel)
                    if o.id in ids:
                        ids.remove(o.id)
                    else:
                        ids.append(o.id)
                    ed.set_selection(ids)
                elif o.id not in ed.sel:
                    ed.set_selection([o.id])
                self.drag = {'mode': 'move', 'start': pp, 'pushed': False,
                             'init': {x.id: x.state(ed.frame) for x in ed.selected_objs()}}
            else:
                if not (mods & Qt.ShiftModifier):
                    ed.set_selection([])
                self.drag = {'mode': 'marquee', 'p0': pp, 'p1': pp}
        elif t == 'pen':
            s = self.snap(pp, mods)
            self.drag = {'mode': 'pen', 'pts': [[s.x(), s.y()]], 'poly': QPolygonF([QPointF(s)])}
        elif t in ('line', 'rect', 'ellipse', 'polygon', 'star'):
            s = self.snap(pp, mods)
            self.drag = {'mode': 'shape', 'p0': s, 'p1': s, 'mods': mods}
        elif t == 'spline':
            s = self.snap(pp, mods)
            if len(self.spline_pts) >= 3:
                f0 = self.to_view(QPointF(*self.spline_pts[0]))
                if QLineF(f0, QPointF(e.pos())).length() < 10:
                    self.finish_spline(closed=True)
                    return
            self.spline_pts.append([s.x(), s.y()])
            self.update()
        elif t == 'eraser':
            ed.push_undo()
            self.drag = {'mode': 'erase'}
            self.erase_at(pp)
        elif t == 'eyedrop':
            ed.pick_color_at(pp, e.pos())
        self.update()

    def erase_at(self, pp):
        o = self.hit_object(pp)
        if o:
            self.ed.proj.objects.remove(o)
            if o.id in self.ed.sel:
                self.ed.sel.remove(o.id)
            self.ed.structure_changed()

    def mouseMoveEvent(self, e):
        ed = self.ed
        pp = self.to_proj(e.pos())
        self.cursor_p = pp
        mods = e.modifiers()
        g = ed.proj.grid
        ed.show_cursor_info(pp)
        d = self.drag
        if not d:
            if ed.tool == 'spline' and self.spline_pts:
                self.update()
            return
        m = d['mode']
        if m == 'pan':
            delta = e.pos() - d['last']
            self.offset += QPointF(delta)
            d['last'] = e.pos()
        elif m == 'pen':
            s = self.snap(pp, mods)
            last = d['pts'][-1]
            if len(d['pts']) < MAX_PEN_POINTS and \
                    math.hypot(s.x() - last[0], s.y() - last[1]) >= max(0.6, 1.5 / self.zoom):
                d['pts'].append([s.x(), s.y()])
                d['poly'].append(QPointF(s))
        elif m == 'shape':
            d['p1'] = self.snap(pp, mods)
            d['mods'] = mods
        elif m == 'marquee':
            d['p1'] = pp
        elif m == 'erase':
            self.erase_at(pp)
        elif m == 'move':
            delta = pp - d['start']
            if not d['pushed'] and (abs(delta.x()) + abs(delta.y())) * self.zoom > 2:
                ed.push_undo()
                d['pushed'] = True
            if d['pushed']:
                objs = ed.selected_objs()
                snap_on = ed.snap and not (mods & Qt.ControlModifier)
                if snap_on and len(objs) > 1:
                    delta = QPointF(round(delta.x() / g) * g, round(delta.y() / g) * g)
                for o in objs:
                    s0 = d['init'].get(o.id)
                    if s0 is None or o.locked:
                        continue
                    nx, ny = s0['x'] + delta.x(), s0['y'] + delta.y()
                    if snap_on and len(objs) == 1:
                        nx, ny = round(nx / g) * g, round(ny / g) * g
                    ed.edit_state(o, x=nx, y=ny)
                ed.state_edited()
        elif m == 'rotate':
            o = d['obj']
            if not d['pushed']:
                ed.push_undo()
                d['pushed'] = True
            s0 = d['init']
            ang = math.degrees(math.atan2(pp.y() - s0['y'], pp.x() - s0['x'])) + 90
            if mods & Qt.ShiftModifier:
                ang = round(ang / 15.0) * 15.0
            ed.edit_state(o, rot=ang)
            ed.state_edited()
        elif m == 'scale':
            o = d['obj']
            if not d['pushed']:
                ed.push_undo()
                d['pushed'] = True
            s0 = d['init']
            d0 = math.hypot(d['start'].x() - s0['x'], d['start'].y() - s0['y'])
            d1 = math.hypot(pp.x() - s0['x'], pp.y() - s0['y'])
            if d0 > 1e-6:
                f = d1 / d0
                ed.edit_state(o, sx=s0['sx'] * f, sy=s0['sy'] * f)
                ed.state_edited()
        self.update()

    def mouseReleaseEvent(self, e):
        d = self.drag
        self.drag = None
        self.setCursor(self.ed.tool_cursor())
        if not d:
            return
        ed = self.ed
        m = d['mode']
        if m == 'pen':
            self.finish_pen(d['pts'])
        elif m == 'shape':
            o = self.make_shape(d['p0'], d['p1'], d['mods'])
            if o:
                ed.add_object(o)
        elif m == 'marquee':
            r = QRectF(d['p0'], d['p1']).normalized()
            if r.width() * self.zoom > 3 or r.height() * self.zoom > 3:
                ids = list(ed.sel) if (e.modifiers() & Qt.ShiftModifier) else []
                for o in ed.proj.objects:
                    if o.visible and not o.locked and o.alive(ed.frame):
                        if o.world_path(ed.frame).boundingRect().intersects(r) and o.id not in ids:
                            ids.append(o.id)
                ed.set_selection(ids)
        elif m in ('move', 'rotate', 'scale'):
            ed.state_edited(final=True)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.ed.tool == 'spline' and self.spline_pts:
            if len(self.spline_pts) >= 2 and self.spline_pts[-1] == self.spline_pts[-2]:
                self.spline_pts.pop()
            self.finish_spline()

    def wheelEvent(self, e):
        old = self.zoom
        d = e.angleDelta().y()
        self.zoom = max(0.03, min(60.0, self.zoom * (1.15 ** (d / 120.0))))
        pos = QPointF(e.pos())
        self.offset = pos - (pos - self.offset) * (self.zoom / old)
        self.update()

    def keyPressEvent(self, e):
        k = e.key()
        if self.ed.tool == 'spline' and self.spline_pts:
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.finish_spline(closed=bool(e.modifiers() & Qt.ControlModifier))
                return
            if k == Qt.Key_Escape:
                self.spline_pts = []
                self.update()
                return
            if k == Qt.Key_Backspace:
                self.spline_pts.pop()
                self.update()
                return
        if k == Qt.Key_Escape:
            self.ed.set_selection([])
        super().keyPressEvent(e)
