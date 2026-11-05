"""几何计算：路径长度、到点距离、位姿归一化。"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Point = Sequence[float]


def as_point(value: Iterable[float] | None) -> list[float]:
    """转为 [x, y, z] 浮点列表，非法输入返回空列表。"""
    if value is None:
        return []
    try:
        numbers = [float(item) for item in value][:3]
    except (TypeError, ValueError):
        return []
    while len(numbers) < 3:
        numbers.append(0.0)
    return numbers


def distance(a: Point, b: Point) -> float:
    return math.dist(list(a)[:3], list(b)[:3])


def path_length(points: Sequence[Point]) -> float:
    """累计路径长度，少于两点返回 0。"""
    if len(points) < 2:
        return 0.0
    total = 0.0
    for previous, current in zip(points, points[1:]):
        total += distance(previous, current)
    return round(total, 3)


def yaw_from_quaternion(rotation: Sequence[float] | None) -> float:
    """由 [x, y, z, w] 四元数提取偏航角（弧度）。"""
    if not rotation or len(rotation) < 4:
        return 0.0
    x, y, z, w = (float(item) for item in rotation[:4])
    siny_cosp = 2.0 * (w * y + x * z)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return round(math.atan2(siny_cosp, cosy_cosp), 4)


def pose_from(position: Sequence[float] | None, rotation: Sequence[float] | None = None) -> list[float]:
    """位置 + 偏航角，统一为 [x, y, z, yaw]。"""
    point = as_point(position)
    if not point:
        return []
    return [*point, yaw_from_quaternion(rotation)]


def project_2d(points: Sequence[Point]) -> list[list[float]]:
    """投影到水平面，返回 [x, z] 列表，用于俯视轨迹绘制。"""
    return [[round(float(p[0]), 3), round(float(p[2]), 3)] for p in points if len(p) >= 3]


def bounds(points: Sequence[Point]) -> dict[str, float]:
    """二维包围盒，供前端自适应缩放。"""
    if not points:
        return {"min_x": 0.0, "max_x": 0.0, "min_z": 0.0, "max_z": 0.0}
    xs = [float(p[0]) for p in points]
    zs = [float(p[2]) for p in points]
    return {
        "min_x": round(min(xs), 3),
        "max_x": round(max(xs), 3),
        "min_z": round(min(zs), 3),
        "max_z": round(max(zs), 3),
    }
