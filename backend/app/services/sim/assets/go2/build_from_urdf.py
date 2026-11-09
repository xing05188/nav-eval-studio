"""把 Unitree Go2 的 URDF 烘成单个 GLB（离线工具，不参与运行时）。

为什么不用 habitat 的 `add_articulated_object_from_urdf`：
我们只要"看得见一只狗"，不需要 12 个关节的物理；静态网格每帧抄一次 agent 位姿即可，
不建 bullet 多体、不跑关节求解，也就没有 URDF 路径/单位/朝向那些运行时坑。

用法（需要额外装 trimesh + pycollada，它们不是项目依赖）：

    pip install --target /tmp/urdfdeps trimesh pycollada
    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/unitreerobotics/unitree_ros /tmp/unitree_ros
    cd /tmp/unitree_ros && git sparse-checkout set robots/go2_description

    PYTHONPATH=/tmp/urdfdeps python backend/app/services/sim/assets/go2/build_from_urdf.py \
        --urdf /tmp/unitree_ros/robots/go2_description/urdf/go2_description.urdf \
        --pkg-root /tmp/unitree_ros/robots \
        --out backend/app/services/sim/assets/go2/go2.glb

产物约定：Y-up、脚底在 y=0、车头朝 -Z（与 habitat 的前向一致），所以运行时只需把
agent 的位置/朝向原样抄给模型。
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import trimesh
from trimesh.transformations import euler_matrix, rotation_matrix

# Unitree 常见站姿（与 mujoco menagerie 的 home keyframe 一致）
STAND = {"hip": 0.0, "thigh": 0.9, "calf": -1.8}


def _floats(text: str | None, default) -> np.ndarray:
    if not text:
        return np.array(default, dtype=float)
    return np.array([float(x) for x in text.split()], dtype=float)


def _resolve(filename: str, pkg_root: Path) -> Path:
    if filename.startswith("package://"):
        return pkg_root / filename[len("package://"):]
    return Path(filename)


def _transform(xyz, rpy, scale=None) -> np.ndarray:
    mat = euler_matrix(float(rpy[0]), float(rpy[1]), float(rpy[2]), "sxyz")
    mat[:3, 3] = xyz
    if scale is not None and not np.allclose(scale, 1.0):
        mat[:3, :3] = mat[:3, :3] @ np.diag(scale)
    return mat


def _joint_angle(name: str) -> float:
    for key, value in STAND.items():
        if name.endswith(f"_{key}_joint"):
            return value
    return 0.0


def convert(urdf: Path, pkg_root: Path, out: Path) -> None:
    root = ET.parse(urdf).getroot()
    links = {el.get("name"): el for el in root.findall("link")}

    joints: dict[str, tuple[str, np.ndarray]] = {}
    for joint in root.findall("joint"):
        parent = joint.find("parent").get("link")
        child = joint.find("child").get("link")
        origin = joint.find("origin")
        xyz = _floats(origin.get("xyz") if origin is not None else None, [0, 0, 0])
        rpy = _floats(origin.get("rpy") if origin is not None else None, [0, 0, 0])
        rel = _transform(xyz, rpy)
        axis_el = joint.find("axis")
        axis = _floats(axis_el.get("xyz") if axis_el is not None else None, [0, 0, 0])
        angle = _joint_angle(joint.get("name"))
        if joint.get("type") in ("revolute", "continuous") and np.linalg.norm(axis) > 0 and angle:
            rel = rel @ rotation_matrix(angle, axis)
        joints[child] = (parent, rel)

    def world(link: str) -> np.ndarray:
        mat = np.eye(4)
        chain = []
        cur = link
        while cur in joints:
            parent, rel = joints[cur]
            chain.append(rel)
            cur = parent
        for rel in reversed(chain):
            mat = mat @ rel
        return mat

    cache: dict[Path, trimesh.Scene] = {}
    scene = trimesh.Scene()
    for name, link in links.items():
        link_mat = world(name)
        for visual in link.findall("visual"):
            geom = visual.find("geometry/mesh")
            if geom is None:
                continue
            path = _resolve(geom.get("filename"), pkg_root)
            if not path.exists():
                print(f"missing mesh: {path}")
                continue
            if path not in cache:
                cache[path] = trimesh.load(str(path), force="scene")
            origin = visual.find("origin")
            xyz = _floats(origin.get("xyz") if origin is not None else None, [0, 0, 0])
            rpy = _floats(origin.get("rpy") if origin is not None else None, [0, 0, 0])
            scale = _floats(geom.get("scale"), [1, 1, 1])
            mat = link_mat @ _transform(xyz, rpy, scale)
            sub = cache[path]
            for node in sub.graph.nodes_geometry:
                T, geom_name = sub.graph[node]
                mesh = sub.geometry[geom_name].copy()
                mesh.apply_transform(mat @ T)
                scene.add_geometry(mesh, geom_name=f"{name}_{geom_name}")

    # URDF 是 Z-up、车头 +X；habitat 是 Y-up、车头 -Z
    scene.apply_transform(rotation_matrix(-np.pi / 2, [1, 0, 0]))
    scene.apply_transform(rotation_matrix(np.pi / 2, [0, 1, 0]))
    scene.apply_translation([0, -scene.bounds[0][1], 0])   # 脚底贴 y=0

    out.parent.mkdir(parents=True, exist_ok=True)
    scene.export(out)
    tris = sum(len(g.faces) for g in scene.geometry.values())
    print(f"wrote {out} ({out.stat().st_size / 1024 / 1024:.2f} MB, {tris} tris)")
    print(f"bounds: {np.round(scene.bounds, 3).tolist()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Go2 URDF → 单个 GLB")
    parser.add_argument("--urdf", required=True, type=Path)
    parser.add_argument("--pkg-root", required=True, type=Path,
                        help="package:// 的根目录，例如 .../unitree_ros/robots")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    convert(args.urdf, args.pkg_root, args.out)


if __name__ == "__main__":
    main()
