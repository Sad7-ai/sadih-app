"""tools/smplx_to_glb.py: the .glb, posed the glTF way, must equal SMPL-X linear blend skinning.
No licensed file needed: a synthetic model with SMPL-X's keys, shapes and joint tree stands in.   python tests/test_glb.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import smplx_to_glb as sg  # noqa: E402

# SMPL-X kintree_table row 0 (parents), as in SMPLX_NEUTRAL.npz
PARENTS = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19, 15, 15, 15,
           20, 25, 26, 20, 28, 29, 20, 31, 32, 20, 34, 35, 20, 37, 38,
           21, 40, 41, 21, 43, 44, 21, 46, 47, 21, 49, 50, 21, 52, 53]


def synthetic_npz(path: Path, V=600, seed=0):
    rng = np.random.default_rng(seed)
    J = np.zeros((55, 3))
    for i in range(1, 55):
        J[i] = J[PARENTS[i]] + rng.normal(0, 0.08, 3)
    owner = rng.integers(0, 55, V)
    v = J[owner] + rng.normal(0, 0.02, (V, 3))
    w = np.zeros((V, 55))
    for k in range(V):                                  # <= 4 influences, so top-4 loses nothing here
        js = rng.choice(55, size=rng.integers(1, 5), replace=False)
        w[k, js] = rng.random(len(js))
    w /= w.sum(1, keepdims=True)
    jr = np.zeros((55, V))
    for i in range(55):                                 # each joint = mean of the vertices it owns (or itself)
        mine = np.where(owner == i)[0]
        if len(mine):
            jr[i, mine] = 1 / len(mine)
    f = rng.integers(0, V, (900, 3))
    kt = np.stack([np.array([4294967295] + PARENTS[1:], dtype=np.int64), np.arange(55)])
    sd = rng.normal(0, 1e-3, (V, 3, 400))
    np.savez(path, v_template=v, f=f, weights=w, J_regressor=jr, kintree_table=kt, shapedirs=sd,
             hands_meanl=np.zeros(45), hands_meanr=np.zeros(45))


def rodrigues(r):
    th = np.linalg.norm(r)
    if th < 1e-12:
        return np.eye(3)
    k = r / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K


def smplx_lbs(m, pose):
    """smplx.lbs without pose correctives: pose (55, 3) axis-angle, zero shape and expression."""
    J, P = m["J"], m["parents"]
    G = np.zeros((55, 4, 4))
    for i in range(55):
        T = np.eye(4)
        T[:3, :3] = rodrigues(pose[i])
        T[:3, 3] = J[i] - (J[P[i]] if P[i] >= 0 else 0)
        G[i] = T if P[i] < 0 else G[P[i]] @ T
    A = G.copy()
    for i in range(55):
        A[i, :3, 3] -= G[i, :3, :3] @ J[i]
    vh = np.concatenate([m["v"], np.ones((len(m["v"]), 1))], 1)
    Tv = np.einsum("vk,kab->vab", m["weights"], A)
    return np.einsum("vab,vb->va", Tv, vh)[:, :3], G[:, :3, 3]


def quat_from_aa(r):
    th = np.linalg.norm(r)
    if th < 1e-12:
        return np.array([0, 0, 0, 1.0])
    k = r / th
    return np.concatenate([k * np.sin(th / 2), [np.cos(th / 2)]])


def quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def accessor(js, binb, i):
    a = js["accessors"][i]
    bv = js["bufferViews"][a["bufferView"]]
    dt = {5126: np.float32, 5121: np.uint8, 5123: np.uint16, 5125: np.uint32}[a["componentType"]]
    n = {"SCALAR": 1, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
    return np.frombuffer(binb, dt, a["count"] * n, bv["byteOffset"]).reshape(a["count"], n)


def gltf_pose(js, binb, pose):
    """Pose the glb the way a glTF viewer (three.js) does: node TRS -> global, joint matrix = global @ IBM."""
    nodes = js["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    G = [None] * 55

    def glob(i):
        if G[i] is None:
            T = np.eye(4)
            T[:3, :3] = quat_mat(quat_from_aa(pose[i]))
            T[:3, 3] = nodes[i]["translation"]
            G[i] = T if i not in parent else glob(parent[i]) @ T
        return G[i]

    skin = js["skins"][0]
    ibm = accessor(js, binb, skin["inverseBindMatrices"]).reshape(55, 4, 4).transpose(0, 2, 1)
    jm = np.stack([glob(j) @ ibm[k] for k, j in enumerate(skin["joints"])])
    prim = js["meshes"][0]["primitives"][0]
    v = accessor(js, binb, prim["attributes"]["POSITION"]).astype(np.float64)
    ji = accessor(js, binb, prim["attributes"]["JOINTS_0"]).astype(int)
    jw = accessor(js, binb, prim["attributes"]["WEIGHTS_0"]).astype(np.float64)
    vh = np.concatenate([v, np.ones((len(v), 1))], 1)
    out = np.zeros((len(v), 3))
    for k in range(4):
        out += jw[:, k:k + 1] * np.einsum("vab,vb->va", jm[ji[:, k]], vh)[:, :3]
    return out, np.stack([glob(i)[:3, 3] for i in range(55)])


def main():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="sadih_glb_"))
    npz = tmp / "synthetic_smplx.npz"
    synthetic_npz(npz)
    m = sg.load_model(npz)
    data = sg.build_glb(m)
    js, binb = sg.read_glb(data)
    ok = 0
    assert [n["name"] for n in js["nodes"][:55]] == [sg.bone_name(i) for i in range(55)]
    assert js["nodes"][15]["name"] == "15_head" and js["nodes"][21]["name"] == "21_right_wrist"
    print("ok   55 bones, SMPL-X order and names"); ok += 1
    prim = js["meshes"][0]["primitives"][0]
    assert len(prim["targets"]) == 10 and js["meshes"][0]["extras"]["targetNames"][0] == "expr0"
    e3 = accessor(js, binb, prim["targets"][3]["POSITION"])
    assert np.allclose(e3, m["expr"][:, :, 3], atol=1e-7)
    npz_sd = np.load(npz)["shapedirs"]
    assert np.allclose(e3, npz_sd[:, :, 303], atol=1e-7), "expression must start at 300 in a 400-wide shapedirs"
    print("ok   10 expression morph targets = shapedirs[:, :, 300:310]"); ok += 1
    rng = np.random.default_rng(1)
    worst_v = worst_j = 0.0
    for trial in range(5):
        pose = rng.normal(0, 0.6, (55, 3))
        ref_v, ref_j = smplx_lbs(m, pose)
        got_v, got_j = gltf_pose(js, binb, pose)
        worst_v = max(worst_v, float(np.abs(ref_v - got_v).max()))
        worst_j = max(worst_j, float(np.abs(ref_j - got_j).max()))
    assert worst_v < 1e-4 and worst_j < 1e-5, (worst_v, worst_j)
    print(f"ok   glTF skinning == SMPL-X LBS on 5 random poses (max vertex error {worst_v:.1e} m, joint {worst_j:.1e} m)")
    ok += 1
    zero_v, _ = gltf_pose(js, binb, np.zeros((55, 3)))
    assert np.abs(zero_v - m["v"]).max() < 1e-5
    print("ok   zero pose = the template mesh"); ok += 1
    print(f"{ok} passed")


if __name__ == "__main__":
    main()
