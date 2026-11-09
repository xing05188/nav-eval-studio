"""俯视图：navmesh 底图 + 起点 / 终点圈 / 轨迹 / 狗。

坐标约定（沿用旧脚本）：世界 `(x, z)` → 图像 `(px, py)`，**x 向右、z 向下**，
所以 z 与图像行方向一致，不需要翻转。navmesh 三角面底图只画一次并缓存。
"""

from __future__ import annotations

import math

import numpy as np

from . import constants as C

# BGR（cv2 顺序）：三种线的配色，图例与绘制共用一套，别各写各的
COLOR_TRAIL = (60, 200, 255)      # 实际轨迹：青
COLOR_HUMAN = (235, 120, 240)     # 人类示范轨迹：紫红
COLOR_ORACLE = (120, 245, 255)    # oracle 最短路径：淡黄


class TopDownMap:
    def __init__(self, sim, w: int = C.MAP_W, h: int = C.MAP_H, margin: int = C.MAP_MARGIN):
        pf = sim.pathfinder
        vertices = np.asarray(pf.build_navmesh_vertices(), dtype=np.float64)
        indices = np.asarray(pf.build_navmesh_vertex_indices(), dtype=np.int64).reshape(-1, 3)
        if vertices.size == 0 or indices.size == 0:
            # navmesh 为空时给一个占位范围，别让 min() 直接抛异常
            self.tris = np.zeros((0, 3, 2), dtype=np.float64)
            self.x0, self.x1 = -5.0, 5.0
            self.z0, self.z1 = -5.0, 5.0
        else:
            self.tris = vertices[indices][:, :, [0, 2]]      # (M,3,2) 取 X-Z 平面
            xs, zs = vertices[:, 0], vertices[:, 2]
            self.x0, self.x1 = float(xs.min()), float(xs.max())
            self.z0, self.z1 = float(zs.min()), float(zs.max())
        self.w, self.h, self.margin = w, h, margin
        self.scale = min((w - 2 * margin) / max(self.x1 - self.x0, 1e-6),
                         (h - 2 * margin) / max(self.z1 - self.z0, 1e-6))
        self._base = None
        self._static = None
        self._static_key = None

    def to_px(self, x: float, z: float) -> tuple[int, int]:
        px = int(self.margin + (x - self.x0) * self.scale)
        py = int(self.margin + (z - self.z0) * self.scale)
        return px, py

    def base_canvas(self) -> np.ndarray:
        """导航区域画一次就够（缓存），返回副本避免被上层叠加污染。"""
        if self._base is not None:
            return self._base.copy()
        import cv2

        canvas = np.zeros((self.h, self.w, 3), np.uint8)
        canvas[:] = C.MAP_BG
        for tri in self.tris:
            pts = np.array([self.to_px(x, z) for x, z in tri], dtype=np.int32)
            cv2.fillConvexPoly(canvas, pts, C.MAP_FLOOR, lineType=cv2.LINE_AA)
        self._base = canvas
        return canvas.copy()

    def static_layer(self, key, builder):
        """静态层缓存：底图 + 起点 + 终点圈，只在换局/换半径时重建。"""
        if self._static is None or self._static_key != key:
            self._static = builder()
            self._static_key = key
        return self._static




def draw_dog_marker(img, px: int, py: int, yaw: float, gait: float, scale: float = 1.0) -> None:
    """在俯视图上画一只朝向 yaw 的四足狗（占位造型，带步态摆动）。"""
    import cv2

    # 实测：yaw=150° 前进时 Δx=-0.125、Δz=+0.217，即前方向量 = (-sinθ, -cosθ)，
    # 所以这里取 s = -sinθ，否则整只狗会在俯视图上左右镜像（左转画成右转）
    c, s = math.cos(yaw), -math.sin(yaw)

    def rot(dx: float, dz: float) -> tuple[int, int]:
        # 世界系（x 向右, z 向下）按 yaw 旋转
        return (int(px + (dx * c - dz * s) * scale), int(py + (dx * s + dz * c) * scale))

    body = np.array([rot(-7, -5), rot(7, -5), rot(7, 5), rot(-7, 5)], np.int32)
    cv2.fillConvexPoly(img, body, (52, 60, 72))
    cv2.polylines(img, [body], True, (245, 245, 245), 1, cv2.LINE_AA)
    # 头朝前 = 世界 -Z 方向（dz < 0）
    hx, hy = rot(0, -9)
    cv2.circle(img, (hx, hy), int(4 * scale) + 1, (90, 100, 118), -1, cv2.LINE_AA)
    cv2.circle(img, (hx, hy), int(4 * scale) + 1, (245, 245, 245), 1, cv2.LINE_AA)
    # 四条腿：对角相位差 0.5
    for dx, dz, ph in ((-5, -4, 0.0), (-5, 4, 0.5), (5, -4, 0.5), (5, 4, 0.0)):
        sw = 3.0 * math.sin(2 * math.pi * (gait + ph))
        cv2.line(img, rot(dx, dz), rot(dx + sw, dz + 3), (210, 210, 210), 1, cv2.LINE_AA)
    cv2.arrowedLine(img, (px, py), rot(0, -16), (60, 220, 255), 1, cv2.LINE_AA, tipLength=0.35)


def draw_goal(img, mapper: TopDownMap, goal, radius: float = C.SUCCESS_DIST) -> None:
    """终点：半透明成功圈 + 十字 + 半径文字。"""
    import cv2

    gx, gy = mapper.to_px(float(goal[0]), float(goal[2]))
    r = max(4, int(radius * mapper.scale))
    overlay = img.copy()
    cv2.circle(overlay, (gx, gy), r, (60, 140, 60), -1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.22, img, 0.78, 0, img)
    cv2.circle(img, (gx, gy), r, (80, 200, 80), 2, cv2.LINE_AA)
    cv2.drawMarker(img, (gx, gy), (80, 240, 80), cv2.MARKER_CROSS, 14, 2, cv2.LINE_AA)
    cv2.putText(img, f"GOAL r={radius:.1f}m", (gx + 8, gy - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 240, 150), 1, cv2.LINE_AA)


def draw_start(img, mapper: TopDownMap, start, yaw: float = 0.0) -> None:
    """起点：菱形标记 + 朝向箭头 + START 文字（与狗当前位置区分开）。"""
    import cv2

    sx, sy = mapper.to_px(float(start[0]), float(start[2]))
    d = 7
    diamond = np.array([[sx, sy - d], [sx + d, sy], [sx, sy + d], [sx - d, sy]], np.int32)
    cv2.fillConvexPoly(img, diamond, (40, 90, 180))
    cv2.polylines(img, [diamond], True, (255, 190, 80), 2, cv2.LINE_AA)
    # 同上：前方 = (-sinθ, -cosθ)
    ex = int(sx - 22 * math.sin(yaw))
    ey = int(sy - 22 * math.cos(yaw))
    cv2.arrowedLine(img, (sx, sy), (ex, ey), (255, 190, 80), 2, cv2.LINE_AA, tipLength=0.35)
    cv2.putText(img, "START", (sx + 9, sy + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 205, 120), 1, cv2.LINE_AA)


def draw_path(img, mapper: TopDownMap, points, color, *, width: int = 2,
              dash: int = 6, label: str = "", label_at=None) -> None:
    """画一条参考路径（人类示范 / oracle 最短路径）。

    `dash>0` 时手工打断成虚线：俯视图上已经有青色的实线轨迹，
    参考线用虚线才分得清"走过的"和"该走的"。
    """
    import cv2

    if not points or len(points) < 2:
        return
    pts = np.array([mapper.to_px(float(p[0]), float(p[2])) for p in points], np.int32)
    if dash > 0:
        step = max(2, int(dash))
        for i in range(0, len(pts) - 1, step * 2):
            seg = pts[i:i + step + 1]
            if len(seg) >= 2:
                cv2.polylines(img, [seg], False, color, width, cv2.LINE_AA)
    else:
        cv2.polylines(img, [pts], False, color, width, cv2.LINE_AA)
    if label:
        x, y = mapper.to_px(float(points[0][0]), float(points[0][2]))
        tx, ty = (x + 10, y - 6) if label_at is None else label_at
        cv2.putText(img, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)


def draw_legend(img, entries) -> None:
    """左上角图例：`[(颜色, 文字)]`。只写英文，避免缺中文字体时变方块。"""
    import cv2

    entries = [e for e in entries if e]
    if not entries:
        return
    pad, line_h, x0, y0 = 6, 13, 24, 22
    width = max(cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)[0][0] for _, t in entries)
    overlay = img.copy()
    cv2.rectangle(overlay, (x0 - 4, y0 - 12), (x0 + width + 34, y0 + line_h * len(entries) - 4),
                  (14, 16, 20), -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
    for i, (color, text) in enumerate(entries):
        y = y0 + line_h * i
        cv2.line(img, (x0, y), (x0 + 14, y), color, 2, cv2.LINE_AA)
        cv2.putText(img, text, (x0 + 20, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color,
                    1, cv2.LINE_AA)


def draw_trail(img, mapper: TopDownMap, trail) -> None:
    """实际走过的轨迹（青色实线）。"""
    import cv2

    if trail is None or len(trail) < 2:
        return
    pts = np.array([mapper.to_px(float(x), float(z)) for x, z in trail], np.int32)
    cv2.polylines(img, [pts], False, COLOR_TRAIL, 2, cv2.LINE_AA)


def draw_scale_bar(img, mapper: TopDownMap) -> None:
    """右下角比例尺：1–10 m 之间取整，读数才可信。"""
    import cv2

    meters = max(1, int(round((mapper.w * 0.18) / max(mapper.scale, 1e-6))))
    px = int(meters * mapper.scale)
    x1, y1 = mapper.w - 16, mapper.h - 14
    x0 = x1 - px
    cv2.line(img, (x0, y1), (x1, y1), (190, 195, 205), 2, cv2.LINE_AA)
    cv2.line(img, (x0, y1 - 3), (x0, y1 + 3), (190, 195, 205), 1, cv2.LINE_AA)
    cv2.line(img, (x1, y1 - 3), (x1, y1 + 3), (190, 195, 205), 1, cv2.LINE_AA)
    cv2.putText(img, f"{meters} m", (x0, y1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (190, 195, 205), 1, cv2.LINE_AA)


__all__ = [
    "TopDownMap",
    "draw_dog_marker",
    "draw_goal",
    "draw_start",
    "draw_trail",
    "draw_scale_bar",
    "draw_path",
    "draw_legend",
    "COLOR_TRAIL",
    "COLOR_HUMAN",
    "COLOR_ORACLE",
]
