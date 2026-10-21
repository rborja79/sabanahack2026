"""Exporta un modelo de MuJoCo a GLB para que el visor lo pinte.

Cada geom queda como un nodo con el nombre del body al que pertenece, en su pose
local. El visor carga el GLB una sola vez y despues solo recibe, por websocket,
la posicion y rotacion de cada body.
"""
import argparse, json, os, pathlib
import numpy as np
import mujoco
import trimesh

MENAGERIE = pathlib.Path(__file__).resolve().parents[1] / "sim" / "mujoco_menagerie"


def quat_a_matriz(q):
    """MuJoCo guarda wxyz; devuelve una matriz 4x4."""
    w, x, y, z = q
    n = w * w + x * x + y * y + z * z
    if n < 1e-12:
        return np.eye(4)
    s = 2.0 / n
    wx, wy, wz = s * w * x, s * w * y, s * w * z
    xx, xy, xz = s * x * x, s * x * y, s * x * z
    yy, yz, zz = s * y * y, s * y * z, s * z * z
    M = np.eye(4)
    M[:3, :3] = [[1 - (yy + zz), xy - wz, xz + wy],
                 [xy + wz, 1 - (xx + zz), yz - wx],
                 [xz - wy, yz + wx, 1 - (xx + yy)]]
    return M


def malla_de_geom(m, i):
    """Devuelve un trimesh en coordenadas locales del body, o None si se omite."""
    t = int(m.geom_type[i])
    s = m.geom_size[i]
    G = mujoco.mjtGeom
    if t == G.mjGEOM_PLANE:
        return None
    if t == G.mjGEOM_SPHERE:
        g = trimesh.creation.icosphere(subdivisions=2, radius=float(s[0]))
    elif t == G.mjGEOM_CAPSULE:
        g = trimesh.creation.capsule(radius=float(s[0]), height=float(2 * s[1]), count=[12, 12])
        g.apply_translation([0, 0, -float(s[1])])
    elif t == G.mjGEOM_CYLINDER:
        g = trimesh.creation.cylinder(radius=float(s[0]), height=float(2 * s[1]), sections=16)
    elif t == G.mjGEOM_BOX:
        g = trimesh.creation.box(extents=[2 * s[0], 2 * s[1], 2 * s[2]])
    elif t == G.mjGEOM_MESH:
        did = int(m.geom_dataid[i])
        if did < 0:
            return None
        v0, nv = int(m.mesh_vertadr[did]), int(m.mesh_vertnum[did])
        f0, nf = int(m.mesh_faceadr[did]), int(m.mesh_facenum[did])
        verts = np.array(m.mesh_vert[v0:v0 + nv]).reshape(-1, 3)
        faces = np.array(m.mesh_face[f0:f0 + nf]).reshape(-1, 3)
        g = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    else:
        return None
    T = quat_a_matriz(m.geom_quat[i])
    T[:3, 3] = m.geom_pos[i]
    g.apply_transform(T)
    rgba = np.clip(np.array(m.geom_rgba[i], dtype=float), 0, 1)
    if rgba[3] == 0:
        rgba[3] = 1.0
    g.visual = trimesh.visual.ColorVisuals(
        mesh=g, face_colors=np.tile((rgba * 255).astype(np.uint8), (len(g.faces), 1)))
    return g


def simplificar(g, objetivo):
    """Reduce la malla a un maximo de triangulos, conservando el color."""
    try:
        import fast_simplification
    except ImportError:
        return g
    reduccion = 1.0 - (objetivo / len(g.faces))
    try:
        v, f = fast_simplification.simplify(
            np.asarray(g.vertices, dtype=np.float32),
            np.asarray(g.faces, dtype=np.int32), reduccion)
    except Exception:
        return g
    color = g.visual.face_colors[0] if len(getattr(g.visual, "face_colors", [])) else [200, 200, 200, 255]
    nuevo = trimesh.Trimesh(vertices=v, faces=f, process=False)
    nuevo.visual = trimesh.visual.ColorVisuals(
        mesh=nuevo, face_colors=np.tile(np.array(color, dtype=np.uint8), (len(nuevo.faces), 1)))
    return nuevo


def exportar(modelo, destino, decimar=0):
    ruta = MENAGERIE / modelo / "scene.xml"
    m = mujoco.MjModel.from_xml_path(str(ruta))
    escena = trimesh.Scene()
    cuerpos, n_geoms, n_tris = [], 0, 0
    for i in range(m.ngeom):
        bid = int(m.geom_bodyid[i])
        nombre_body = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, bid) or f"body{bid}"
        if nombre_body == "world":
            continue
        g = malla_de_geom(m, i)
        if g is None or len(g.faces) == 0:
            continue
        if decimar and len(g.faces) > decimar:
            g = simplificar(g, decimar)
        n_geoms += 1
        n_tris += len(g.faces)
        escena.add_geometry(g, node_name=f"{nombre_body}__{i}", geom_name=f"g{i}")
    for bid in range(m.nbody):
        nb = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, bid) or f"body{bid}"
        if nb != "world":
            cuerpos.append(nb)
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    escena.export(destino)
    manifiesto = {
        "modelo": modelo, "bodies": cuerpos, "geoms": n_geoms, "triangulos": n_tris,
        "nq": int(m.nq), "nv": int(m.nv), "nu": int(m.nu),
        "actuadores": [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(m.nu)],
    }
    with open(os.path.splitext(destino)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(manifiesto, fh, ensure_ascii=False, indent=1)
    return manifiesto, os.path.getsize(destino)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default="unitree_g1")
    ap.add_argument("--salida", default="../web/public/robots/unitree_g1.glb")
    ap.add_argument("--decimar", type=int, default=0, help="maximo de triangulos por geom")
    a = ap.parse_args()
    man, tam = exportar(a.modelo, a.salida, a.decimar)
    print(f"{a.salida}  {tam/1e6:.2f} MB  geoms={man['geoms']}  triangulos={man['triangulos']}  bodies={len(man['bodies'])}")
