"""Генератор демо-моделей (.glb) без внешних зависимостей.

Собирает простые сцены из примитивов (куб, цилиндр, сфера, конус, тор, призма)
и пишет их в бинарный glTF 2.0. Запуск: python demo_assets/generate_models.py
"""

import json
import math
import struct
from pathlib import Path

OUT = Path(__file__).parent / "models"

Vec = tuple[float, float, float]
Mesh = tuple[list[Vec], list[Vec], list[int]]  # позиции, нормали, индексы


# --------------------------------------------------------------------- геометрия


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(u: Vec, v: Vec) -> Vec:
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _dot(u: Vec, v: Vec) -> float:
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def _unit(v: Vec) -> Vec:
    length = math.sqrt(_dot(v, v)) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


def _solid(tris: list[tuple[Vec, Vec, Vec]]) -> Mesh:
    """Выпуклое тело с плоскими гранями: нормали направляем от центра."""
    points = [p for tri in tris for p in tri]
    center = tuple(sum(p[i] for p in points) / len(points) for i in range(3))
    pos, nrm, idx = [], [], []
    for a, b, c in tris:
        n = _unit(_cross(_sub(b, a), _sub(c, a)))
        mid = tuple((a[i] + b[i] + c[i]) / 3 for i in range(3))
        if _dot(n, _sub(mid, center)) < 0:
            b, c, n = c, b, (-n[0], -n[1], -n[2])
        base = len(pos)
        pos += [a, b, c]
        nrm += [n] * 3
        idx += [base, base + 1, base + 2]
    return pos, nrm, idx


def _smooth(pos: list[Vec], nrm: list[Vec], idx: list[int]) -> Mesh:
    """Разворачивает треугольники так, чтобы они смотрели в сторону нормалей вершин."""
    fixed = []
    for i in range(0, len(idx), 3):
        a, b, c = idx[i : i + 3]
        geo = _cross(_sub(pos[b], pos[a]), _sub(pos[c], pos[a]))
        avg = tuple(nrm[a][k] + nrm[b][k] + nrm[c][k] for k in range(3))
        fixed += [a, c, b] if _dot(geo, avg) < 0 else [a, b, c]
    return pos, nrm, fixed


def box(w: float, h: float, d: float) -> Mesh:
    x, y, z = w / 2, h / 2, d / 2
    p = [(-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z), (-x, -y, z), (x, -y, z), (x, y, z)]
    p.append((-x, y, z))
    quads = [(4, 5, 6, 7), (1, 0, 3, 2), (5, 1, 2, 6), (0, 4, 7, 3), (3, 7, 6, 2), (0, 1, 5, 4)]
    tris = []
    for a, b, c, d_ in quads:
        tris += [(p[a], p[b], p[c]), (p[a], p[c], p[d_])]
    return _solid(tris)


def prism(w: float, h: float, d: float) -> Mesh:
    """Двускатная крыша: конёк вдоль оси Z, основание на y = 0."""
    x, z = w / 2, d / 2
    fl, fr, fr_top = (-x, 0, z), (x, 0, z), (0, h, z)
    bl, br, br_top = (-x, 0, -z), (x, 0, -z), (0, h, -z)
    tris = [
        (fl, fr, fr_top),
        (bl, br, br_top),
        (fl, fr_top, br_top),
        (fl, br_top, bl),
        (fr, br, br_top),
        (fr, br_top, fr_top),
        (fl, fr, br),
        (fl, br, bl),
    ]
    return _solid(tris)


def cylinder(r: float, h: float, seg: int = 36) -> Mesh:
    pos, nrm, idx = [], [], []
    for i in range(seg + 1):
        a = 2 * math.pi * i / seg
        c, s = math.cos(a), math.sin(a)
        pos += [(r * c, -h / 2, r * s), (r * c, h / 2, r * s)]
        nrm += [(c, 0, s)] * 2
    for i in range(seg):
        b = 2 * i
        idx += [b, b + 1, b + 3, b, b + 3, b + 2]
    for sign in (1, -1):
        center = len(pos)
        pos.append((0, sign * h / 2, 0))
        nrm.append((0, sign, 0))
        for i in range(seg + 1):
            a = 2 * math.pi * i / seg
            pos.append((r * math.cos(a), sign * h / 2, r * math.sin(a)))
            nrm.append((0, sign, 0))
        for i in range(seg):
            idx += [center, center + 1 + i, center + 2 + i]
    return _smooth(pos, nrm, idx)


def sphere(r: float, seg: int = 36, rings: int = 18) -> Mesh:
    pos, nrm, idx = [], [], []
    for j in range(rings + 1):
        phi = math.pi * j / rings
        for i in range(seg + 1):
            theta = 2 * math.pi * i / seg
            n = (math.sin(phi) * math.cos(theta), math.cos(phi), math.sin(phi) * math.sin(theta))
            pos.append((r * n[0], r * n[1], r * n[2]))
            nrm.append(n)
    for j in range(rings):
        for i in range(seg):
            a = j * (seg + 1) + i
            b = a + seg + 1
            idx += [a, b, a + 1, a + 1, b, b + 1]
    return _smooth(pos, nrm, idx)


def cone(r: float, h: float, seg: int = 36) -> Mesh:
    pos, nrm, idx = [], [], []
    for i in range(seg):
        a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
        am = (a0 + a1) / 2
        base = len(pos)
        pos += [
            (r * math.cos(a0), -h / 2, r * math.sin(a0)),
            (r * math.cos(a1), -h / 2, r * math.sin(a1)),
        ]
        pos.append((0, h / 2, 0))
        nrm += [_unit((h * math.cos(a), r, h * math.sin(a))) for a in (a0, a1, am)]
        idx += [base, base + 1, base + 2]
    center = len(pos)
    pos.append((0, -h / 2, 0))
    nrm.append((0, -1, 0))
    for i in range(seg + 1):
        a = 2 * math.pi * i / seg
        pos.append((r * math.cos(a), -h / 2, r * math.sin(a)))
        nrm.append((0, -1, 0))
    for i in range(seg):
        idx += [center, center + 1 + i, center + 2 + i]
    return _smooth(pos, nrm, idx)


def torus(major: float, minor: float, seg: int = 48, tube: int = 20) -> Mesh:
    pos, nrm, idx = [], [], []
    for i in range(seg + 1):
        u = 2 * math.pi * i / seg
        for j in range(tube + 1):
            v = 2 * math.pi * j / tube
            ring = major + minor * math.cos(v)
            pos.append((ring * math.cos(u), minor * math.sin(v), ring * math.sin(u)))
            nrm.append((math.cos(v) * math.cos(u), math.sin(v), math.cos(v) * math.sin(u)))
    for i in range(seg):
        for j in range(tube):
            a = i * (tube + 1) + j
            b = a + tube + 1
            idx += [a, b, a + 1, a + 1, b, b + 1]
    return _smooth(pos, nrm, idx)


def place(mesh: Mesh, t: Vec = (0, 0, 0), r: Vec = (0, 0, 0), s: Vec = (1, 1, 1)) -> Mesh:
    """Масштаб → поворот вокруг X, Y, Z (в градусах) → перенос."""
    rx, ry, rz = (math.radians(a) for a in r)

    def rotate(p: Vec) -> Vec:
        x, y, z = p
        y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
        x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
        x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
        return (x, y, z)

    pos = [
        tuple(a + b for a, b in zip(rotate(tuple(p[i] * s[i] for i in range(3))), t, strict=True))
        for p in mesh[0]
    ]
    nrm = [rotate(_unit(tuple(n[i] / s[i] for i in range(3)))) for n in mesh[1]]
    return pos, nrm, mesh[2]


# --------------------------------------------------------------------- запись .glb


def write_glb(path: Path, parts: list[tuple[Mesh, str]], materials: dict[str, dict]) -> None:
    buf = bytearray()
    views, accessors, meshes, nodes, mat_list = [], [], [], [], []
    mat_index: dict[str, int] = {}

    def add_view(data: bytes, target: int) -> int:
        while len(buf) % 4:
            buf.append(0)
        views.append(
            {"buffer": 0, "byteOffset": len(buf), "byteLength": len(data), "target": target}
        )
        buf.extend(data)
        return len(views) - 1

    for (pos, nrm, idx), material in parts:
        if material not in mat_index:
            mat_index[material] = len(mat_list)
            mat_list.append({"name": material, "doubleSided": True, **materials[material]})
        flat = [c for v in pos for c in v]
        pv = add_view(struct.pack(f"<{len(flat)}f", *flat), 34962)
        flat_n = [c for v in nrm for c in v]
        nv = add_view(struct.pack(f"<{len(flat_n)}f", *flat_n), 34962)
        iv = add_view(struct.pack(f"<{len(idx)}H", *idx), 34963)
        accessors += [
            {
                "bufferView": pv,
                "componentType": 5126,
                "count": len(pos),
                "type": "VEC3",
                "min": [min(v[k] for v in pos) for k in range(3)],
                "max": [max(v[k] for v in pos) for k in range(3)],
            },
            {"bufferView": nv, "componentType": 5126, "count": len(nrm), "type": "VEC3"},
            {"bufferView": iv, "componentType": 5123, "count": len(idx), "type": "SCALAR"},
        ]
        first = len(accessors) - 3
        meshes.append(
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": first, "NORMAL": first + 1},
                        "indices": first + 2,
                        "material": mat_index[material],
                    }
                ]
            }
        )
        nodes.append({"mesh": len(meshes) - 1})

    gltf = {
        "asset": {"version": "2.0", "generator": "polygon3d demo generator"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": mat_list,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(buf)}],
    }
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode()
    json_bytes += b" " * (-len(json_bytes) % 4)
    bin_bytes = bytes(buf) + b"\0" * (-len(buf) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes)
        f.write(struct.pack("<II", len(bin_bytes), 0x004E4942) + bin_bytes)


def mat(color: tuple, metallic: float = 0.0, rough: float = 0.6, emissive: tuple | None = None):
    m = {
        "pbrMetallicRoughness": {
            "baseColorFactor": [*color, 1],
            "metallicFactor": metallic,
            "roughnessFactor": rough,
        }
    }
    if emissive:
        m["emissiveFactor"] = list(emissive)
    return m


# --------------------------------------------------------------------- сцены


def robot():
    m = {
        "body": mat((0.95, 0.45, 0.14), 0.3, 0.45),
        "white": mat((0.88, 0.9, 0.95), 0.2, 0.4),
        "dark": mat((0.12, 0.13, 0.17), 0.5, 0.5),
        "visor": mat((0.05, 0.3, 0.4), 0.1, 0.2, emissive=(0.1, 0.8, 1.0)),
        "red": mat((0.9, 0.1, 0.15), 0.1, 0.3, emissive=(0.6, 0.0, 0.05)),
        "cardboard": mat((0.62, 0.45, 0.27), 0.0, 0.85),
        "steel": mat((0.7, 0.72, 0.78), 1.0, 0.3),
    }
    parts = [
        (place(box(0.9, 1.0, 0.7), (0, 0.95, 0)), "body"),
        (place(box(0.6, 0.45, 0.05), (0, 0.95, 0.36)), "dark"),
        (place(box(0.7, 0.5, 0.6), (0, 1.72, 0)), "white"),
        (place(box(0.56, 0.22, 0.05), (0, 1.74, 0.31)), "visor"),
        (place(cylinder(0.03, 0.35), (0, 2.12, 0)), "steel"),
        (place(sphere(0.07), (0, 2.34, 0)), "red"),
        (place(cylinder(0.08, 0.7), (0.62, 0.95, 0), (0, 0, 14)), "steel"),
        (place(cylinder(0.08, 0.7), (-0.62, 0.95, 0), (0, 0, -14)), "steel"),
        (place(sphere(0.12), (0.69, 0.58, 0)), "dark"),
        (place(sphere(0.12), (-0.69, 0.58, 0)), "dark"),
        (place(cylinder(0.3, 0.2), (0.4, 0.3, 0), (0, 0, 90)), "dark"),
        (place(cylinder(0.3, 0.2), (-0.4, 0.3, 0), (0, 0, 90)), "dark"),
        (place(box(0.62, 0.5, 0.32), (0, 1.05, -0.52)), "cardboard"),
        (place(box(0.64, 0.06, 0.1), (0, 1.05, -0.52)), "white"),
    ]
    return parts, m


def mug():
    m = {
        "ceramic": mat((0.1, 0.55, 0.6), 0.0, 0.25),
        "white": mat((0.95, 0.95, 0.95), 0.0, 0.3),
        "coffee": mat((0.18, 0.09, 0.04), 0.0, 0.15),
    }
    parts = [
        (place(cylinder(0.45, 1.0), (0, 0.0, 0)), "ceramic"),
        (place(torus(0.45, 0.035), (0, 0.5, 0)), "white"),
        (place(cylinder(0.42, 0.02), (0, 0.42, 0)), "coffee"),
        (place(torus(0.27, 0.065), (0.5, 0.0, 0), (90, 0, 0)), "ceramic"),
        (place(cylinder(0.85, 0.06), (0, -0.53, 0)), "white"),
    ]
    return parts, m


def living_room():
    m = {
        "floor": mat((0.55, 0.38, 0.24), 0.0, 0.5),
        "wall": mat((0.72, 0.72, 0.75), 0.0, 0.9),
        "sofa": mat((0.2, 0.32, 0.55), 0.0, 0.85),
        "wood": mat((0.35, 0.22, 0.12), 0.0, 0.5),
        "rug": mat((0.85, 0.78, 0.65), 0.0, 0.95),
        "lamp": mat((1.0, 0.85, 0.55), 0.0, 0.5, emissive=(1.0, 0.7, 0.3)),
        "metal": mat((0.15, 0.15, 0.17), 0.9, 0.35),
        "glass": mat((0.55, 0.75, 0.95), 0.0, 0.1, emissive=(0.3, 0.5, 0.8)),
        "plant": mat((0.15, 0.5, 0.2), 0.0, 0.7),
    }
    parts = [
        (place(box(5.0, 0.1, 4.0), (0, -0.05, 0)), "floor"),
        (place(box(5.0, 2.6, 0.1), (0, 1.3, -2.0)), "wall"),
        (place(box(0.1, 2.6, 4.0), (-2.5, 1.3, 0)), "wall"),
        (place(box(1.4, 1.0, 0.04), (0, 1.5, -1.93)), "glass"),
        (place(box(2.0, 0.45, 0.9), (-0.6, 0.28, -1.4)), "sofa"),
        (place(box(2.0, 0.6, 0.22), (-0.6, 0.78, -1.78)), "sofa"),
        (place(box(0.2, 0.62, 0.9), (-1.7, 0.42, -1.4)), "sofa"),
        (place(box(0.2, 0.62, 0.9), (0.5, 0.42, -1.4)), "sofa"),
        (place(box(2.4, 0.02, 1.6), (-0.6, 0.01, -0.2)), "rug"),
        (place(box(1.1, 0.06, 0.6), (-0.6, 0.42, -0.2)), "wood"),
        *[
            (place(cylinder(0.025, 0.4), (-0.6 + dx, 0.2, -0.2 + dz)), "metal")
            for dx in (-0.48, 0.48)
            for dz in (-0.24, 0.24)
        ],
        (place(cylinder(0.02, 1.5), (1.8, 0.75, -1.6)), "metal"),
        (place(cylinder(0.18, 0.04), (1.8, 0.02, -1.6)), "metal"),
        (place(cone(0.26, 0.36), (1.8, 1.6, -1.6), (180, 0, 0)), "lamp"),
        (place(cylinder(0.14, 0.3), (-2.0, 0.15, -0.6)), "wood"),
        (place(sphere(0.3), (-2.0, 0.55, -0.6), (0, 0, 0), (1, 1.2, 1)), "plant"),
    ]
    return parts, m


def weapons():
    m = {
        "steel": mat((0.78, 0.8, 0.85), 1.0, 0.22),
        "gold": mat((0.95, 0.72, 0.2), 1.0, 0.3),
        "leather": mat((0.25, 0.12, 0.07), 0.0, 0.8),
        "wood": mat((0.45, 0.28, 0.14), 0.0, 0.7),
        "gem": mat((0.8, 0.05, 0.15), 0.2, 0.1, emissive=(0.5, 0.0, 0.08)),
        "blue": mat((0.12, 0.22, 0.5), 0.1, 0.5),
    }
    parts = [
        (place(box(0.14, 1.4, 0.03), (0, 0.95, 0)), "steel"),
        (place(prism(0.14, 0.3, 0.03), (0, 1.65, 0), (0, 0, 0)), "steel"),
        (place(box(0.7, 0.1, 0.12), (0, 0.2, 0)), "gold"),
        (place(cylinder(0.04, 0.42), (0, -0.06, 0)), "leather"),
        (place(sphere(0.08), (0, -0.32, 0)), "gold"),
        (place(sphere(0.045), (0, 0.2, 0.07)), "gem"),
        (place(cylinder(0.6, 0.08), (1.15, 0.65, 0.1), (90, 0, 0)), "blue"),
        (place(torus(0.6, 0.045), (1.15, 0.65, 0.1), (90, 0, 0)), "steel"),
        (place(sphere(0.16), (1.15, 0.65, 0.18), (0, 0, 0), (1, 1, 0.6)), "gold"),
        (place(cylinder(0.025, 1.7), (-0.9, 0.85, 0), (0, 0, 8)), "wood"),
        (place(cone(0.1, 0.35), (-0.78, 1.82, 0), (0, 0, 8)), "steel"),
    ]
    return parts, m


def cottage():
    m = {
        "wall": mat((0.9, 0.84, 0.7), 0.0, 0.9),
        "roof": mat((0.55, 0.2, 0.15), 0.0, 0.7),
        "wood": mat((0.38, 0.23, 0.12), 0.0, 0.6),
        "glass": mat((0.5, 0.75, 0.95), 0.0, 0.1, emissive=(0.35, 0.55, 0.8)),
        "brick": mat((0.6, 0.28, 0.2), 0.0, 0.9),
        "grass": mat((0.25, 0.55, 0.22), 0.0, 0.95),
        "stone": mat((0.62, 0.62, 0.6), 0.0, 0.9),
        "leaf": mat((0.12, 0.42, 0.18), 0.0, 0.8),
    }
    parts = [
        (place(cylinder(2.8, 0.1), (0, -0.05, 0)), "grass"),
        (place(box(3.0, 1.6, 2.4), (0, 0.8, 0)), "wall"),
        (place(prism(3.5, 1.1, 2.8), (0, 1.6, 0)), "roof"),
        (place(box(0.5, 1.0, 0.05), (0, 0.5, 1.22)), "wood"),
        (place(box(0.5, 0.5, 0.05), (-0.95, 0.95, 1.22)), "glass"),
        (place(box(0.5, 0.5, 0.05), (0.95, 0.95, 1.22)), "glass"),
        (place(box(0.3, 0.9, 0.3), (1.0, 2.2, -0.4)), "brick"),
        (place(box(0.55, 0.02, 1.2), (0, 0.01, 1.85)), "stone"),
        (place(cylinder(0.09, 0.7), (2.0, 0.35, 0.9)), "wood"),
        (place(cone(0.5, 0.9), (2.0, 1.05, 0.9)), "leaf"),
        (place(cone(0.38, 0.7), (2.0, 1.6, 0.9)), "leaf"),
    ]
    return parts, m


def phone_stand():
    m = {
        "pla": mat((0.1, 0.7, 0.62), 0.0, 0.55),
        "phone": mat((0.08, 0.08, 0.1), 0.6, 0.3),
        "screen": mat((0.1, 0.2, 0.45), 0.0, 0.1, emissive=(0.15, 0.3, 0.8)),
    }
    tilt = (-18, 0, 0)
    parts = [
        (place(box(0.8, 0.06, 0.75), (0, 0.03, 0)), "pla"),
        (place(box(0.8, 0.8, 0.05), (0, 0.4, -0.2), tilt), "pla"),
        (place(box(0.8, 0.12, 0.06), (0, 0.09, 0.3)), "pla"),
        (place(box(0.4, 0.78, 0.035), (0, 0.45, -0.145), tilt), "phone"),
        (place(box(0.36, 0.7, 0.01), (0, 0.45, -0.125), tilt), "screen"),
    ]
    return parts, m


MODELS = {
    "robot-courier": robot,
    "coffee-mug": mug,
    "loft-living-room": living_room,
    "fantasy-weapons": weapons,
    "small-cottage": cottage,
    "phone-stand": phone_stand,
}


if __name__ == "__main__":
    for name, build in MODELS.items():
        parts, materials = build()
        write_glb(OUT / f"{name}.glb", parts, materials)
        print(f"{name}.glb: {(OUT / f'{name}.glb').stat().st_size // 1024} КБ")
