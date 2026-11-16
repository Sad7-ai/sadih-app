"""SMPLX_NEUTRAL.npz -> avatar.glb for the phone's avatar player. numpy only.

  python tools/smplx_to_glb.py <path>/SMPLX_NEUTRAL.npz private/avatar.glb

What goes in, and why it needs no retargeting:
  - the neutral SMPL-X mesh at zero shape (betas = 0), as in every team render
  - a 55-bone skeleton whose bones ARE the SMPL-X joints (same order, same parents), rest rotation = identity,
    each bone placed at its joint (J = J_regressor @ v_template). So an SMPL-X axis-angle for joint i is
    exactly bone i's local rotation, and glTF skinning (global * inverse bind) is SMPL-X's linear blend
    skinning. Bone names are "<index>_<smplx name>", e.g. "21_right_wrist".
  - the 4 strongest skinning weights per vertex (renormalised): glTF's limit per attribute set
  - the first 10 SMPL-X expression blend shapes as morph targets "expr0".."expr9" (the motion's face numbers)
Left out: pose-corrective blend shapes (posedirs). Without them elbows and finger joints crease slightly more
than in the renders; the pose itself is identical.

The SMPL-X model is licensed (smpl-x.is.tue.mpg.de). The .npz and the .glb made from it must never be
committed or served without the access code. .gitignore blocks private/ and *.glb.
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np

JOINT_NAMES = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee", "spine2", "left_ankle", "right_ankle",
    "spine3", "left_foot", "right_foot", "neck", "left_collar", "right_collar", "head", "left_shoulder",
    "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "jaw", "left_eye_smplhf",
    "right_eye_smplhf",
    "left_index1", "left_index2", "left_index3", "left_middle1", "left_middle2", "left_middle3",
    "left_pinky1", "left_pinky2", "left_pinky3", "left_ring1", "left_ring2", "left_ring3",
    "left_thumb1", "left_thumb2", "left_thumb3",
    "right_index1", "right_index2", "right_index3", "right_middle1", "right_middle2", "right_middle3",
    "right_pinky1", "right_pinky2", "right_pinky3", "right_ring1", "right_ring2", "right_ring3",
    "right_thumb1", "right_thumb2", "right_thumb3",
]
N_JOINTS = 55
N_EXPR = 10
SHAPE_SPACE_DIM = 300          # smplx: SMPL-X 2020 shapedirs hold 300 shape + 100 expression directions


def bone_name(i: int) -> str:
    return f"{i:02d}_{JOINT_NAMES[i]}"


def load_model(npz_path) -> dict:
    with np.load(npz_path, allow_pickle=False) as z:   # the arrays we read need no pickle; never run a file's code
        v = np.asarray(z["v_template"], np.float64)
        f = np.asarray(z["f"], np.int64)
        w = np.asarray(z["weights"], np.float64)
        jr = z["J_regressor"]
        jr = np.asarray(jr.toarray() if hasattr(jr, "toarray") else jr, np.float64)
        kt = np.asarray(z["kintree_table"], np.int64)
        sd = np.asarray(z["shapedirs"], np.float64)
    if w.shape[1] < N_JOINTS or jr.shape[0] < N_JOINTS:
        raise ValueError(f"expected {N_JOINTS} joints, got weights {w.shape}, J_regressor {jr.shape}")
    w, jr = w[:, :N_JOINTS], jr[:N_JOINTS]
    parents = kt[0, :N_JOINTS].copy()
    parents[0] = -1
    # smplx body_models.SMPLX: expression directions start at 300 in the 400-wide 2020 files, at 10 in old ones
    start = SHAPE_SPACE_DIM if sd.shape[-1] >= SHAPE_SPACE_DIM + N_EXPR else 10
    expr = sd[:, :, start:start + N_EXPR]
    return {"v": v, "f": f, "weights": w, "J": jr @ v, "parents": parents, "expr": expr}


def vertex_normals(v, f) -> np.ndarray:
    n = np.zeros_like(v)
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return n


def top4(weights) -> tuple:
    idx = np.argsort(-weights, axis=1)[:, :4]
    w = np.take_along_axis(weights, idx, axis=1)
    w /= np.maximum(w.sum(axis=1, keepdims=True), 1e-12)
    return idx.astype(np.uint8), w.astype(np.float32)


class _Bin:
    def __init__(self):
        self.data = bytearray()
        self.views = []

    def add(self, arr: np.ndarray, target=None) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        b = np.ascontiguousarray(arr).tobytes()
        view = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(b)}
        if target:
            view["target"] = target
        self.data += b
        self.views.append(view)
        return len(self.views) - 1


def build_glb(m: dict) -> bytes:
    v = m["v"].astype(np.float32)
    J = m["J"]
    parents = m["parents"]
    nrm = vertex_normals(m["v"], m["f"]).astype(np.float32)
    jidx, jw = top4(m["weights"])
    faces = m["f"].astype(np.uint16 if len(v) < 65536 else np.uint32).reshape(-1)
    binb, accessors = _Bin(), []

    def acc(arr, comp, typ, target=None, minmax=False):
        a = {"bufferView": binb.add(arr, target), "componentType": comp, "count": int(len(arr)), "type": typ}
        if minmax:
            a["min"] = [float(x) for x in arr.min(axis=0)]
            a["max"] = [float(x) for x in arr.max(axis=0)]
        accessors.append(a)
        return len(accessors) - 1

    FLOAT, U8, U16, U32 = 5126, 5121, 5123, 5125
    pos = acc(v, FLOAT, "VEC3", 34962, minmax=True)
    nor = acc(nrm, FLOAT, "VEC3", 34962)
    joi = acc(jidx, U8, "VEC4", 34962)
    wei = acc(jw, FLOAT, "VEC4", 34962)
    ind = acc(faces, U16 if faces.dtype == np.uint16 else U32, "SCALAR", 34963)
    targets = [{"POSITION": acc(m["expr"][:, :, k].astype(np.float32), FLOAT, "VEC3", 34962, minmax=True)}
               for k in range(m["expr"].shape[2])]
    ibm = np.zeros((N_JOINTS, 16), np.float32)              # column-major translate(-J_i)
    for i in range(N_JOINTS):
        mat = np.eye(4)
        mat[:3, 3] = -J[i]
        ibm[i] = mat.T.reshape(16)
    ibm_acc = acc(ibm, FLOAT, "MAT4")

    nodes = []
    children = {i: [] for i in range(N_JOINTS)}
    for i in range(1, N_JOINTS):
        children[int(parents[i])].append(i)
    for i in range(N_JOINTS):
        t = J[i] - (J[parents[i]] if parents[i] >= 0 else 0)
        node = {"name": bone_name(i), "translation": [float(x) for x in t]}
        if children[i]:
            node["children"] = children[i]
        nodes.append(node)
    mesh_node = len(nodes)
    nodes.append({"name": "body", "mesh": 0, "skin": 0})
    gltf = {
        "asset": {"version": "2.0", "generator": "sadih tools/smplx_to_glb.py"},
        "scene": 0,
        "scenes": [{"nodes": [0, mesh_node]}],
        "nodes": nodes,
        "skins": [{"joints": list(range(N_JOINTS)), "inverseBindMatrices": ibm_acc, "skeleton": 0}],
        "meshes": [{"name": "smplx_neutral",
                    "primitives": [{"attributes": {"POSITION": pos, "NORMAL": nor, "JOINTS_0": joi, "WEIGHTS_0": wei},
                                    "indices": ind, "material": 0, "targets": targets}],
                    "weights": [0.0] * len(targets),
                    "extras": {"targetNames": [f"expr{k}" for k in range(len(targets))]}}],
        "materials": [{"name": "skin", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0],
                                                                "metallicFactor": 0.0, "roughnessFactor": 0.75}}],
        "accessors": accessors,
        "bufferViews": binb.views,
        "buffers": [{"byteLength": len(binb.data)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    bn = bytes(binb.data) + b"\0" * (-len(binb.data) % 4)
    total = 12 + 8 + len(js) + 8 + len(bn)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
            + struct.pack("<I4s", len(bn), b"BIN\0") + bn)


def read_glb(data: bytes) -> tuple:
    """-> (gltf json, bin bytes). For tests."""
    magic, version, total = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2 and total == len(data)
    jl, jt = struct.unpack_from("<I4s", data, 12)
    assert jt == b"JSON"
    js = json.loads(data[20:20 + jl])
    bl, bt = struct.unpack_from("<I4s", data, 20 + jl)
    assert bt == b"BIN\0"
    return js, data[28 + jl:28 + jl + bl]


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    src, dst = Path(argv[0]), Path(argv[1])
    m = load_model(src)
    out = build_glb(m)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    print(f"{dst}: {len(out) / 1e6:.2f} MB  ·  {len(m['v'])} vertices, {len(m['f'])} faces, {N_JOINTS} bones, "
          f"{m['expr'].shape[2]} expression shapes")


if __name__ == "__main__":
    main(sys.argv[1:])
