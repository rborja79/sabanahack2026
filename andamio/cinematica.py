"""Cinematica con MuJoCo: carga un MJCF, encuentra las cadenas de los brazos y resuelve IK.

No simula fisica: coloca las articulaciones y calcula posiciones (cinematica pura). Sirve
para el robot simulado y para convertir "mueve la mano aqui" en 7 angulos por brazo, que es
lo que reciben el X2 (`arm_pos`) y el simulador.

El orden de las articulaciones de cada brazo es el de la cadena desde el hombro hacia la
mano. En el X2 coincide con el orden del mensaje (hombro pitch, roll, yaw, codo, muneca...).
La prueba de integracion lo comprueba contra el MJCF real.
"""
import re

import numpy as np

try:
    import mujoco
except ImportError:  # el resto del andamio funciona sin mujoco
    mujoco = None

from .nucleo.errores import ErrorRobot

PATRON_BRAZO = re.compile(r"shoulder|elbow|wrist|arm", re.I)
PATRON_CABEZA = re.compile(r"head|neck", re.I)


class Modelo:
    def __init__(self, ruta_xml, efectores=None, patron_brazo=PATRON_BRAZO, patron_cabeza=PATRON_CABEZA):
        """efectores: {'izquierda': 'nombre_del_body', 'derecha': ...}. Si falta, se buscan por nombre."""
        if mujoco is None:
            raise ErrorRobot("falta mujoco", pista="pip install mujoco")
        try:
            self.m = mujoco.MjModel.from_xml_path(str(ruta_xml))
        except Exception as e:
            raise ErrorRobot(f"no se pudo cargar el modelo {ruta_xml}: {e}",
                             pista="revisa la ruta del MJCF y que mujoco este instalado")
        self.d = mujoco.MjData(self.m)
        self.ruta = str(ruta_xml)
        self.efectores = efectores or self._buscar_efectores()
        self.cadenas = {}
        for lado, body in self.efectores.items():
            self.cadenas[lado] = self._cadena(body, patron_brazo)
            if not self.cadenas[lado]:
                raise ErrorRobot(f"no hay articulaciones de brazo hacia '{body}' en el modelo")
        self.cabeza = self._articulaciones_cabeza(patron_cabeza)
        self.base = self._base_libre()
        self.reposo()

    # ---------- construccion ----------
    def _nombre_body(self, i):
        return mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_BODY, i)

    def _buscar_efectores(self):
        res = {}
        for i in range(1, self.m.nbody):
            n = self._nombre_body(i) or ""
            nl = n.lower()
            for lado, pref in (("izquierda", "left"), ("derecha", "right")):
                if nl.startswith(pref) and ("wrist" in nl or "hand" in nl):
                    res.setdefault(lado, {})[n] = i
        # el eslabon de muneca mas profundo de cada lado
        out = {}
        for lado, cand in res.items():
            out[lado] = max(cand, key=lambda n: self._profundidad(cand[n]))
        return out

    def _profundidad(self, bid):
        d = 0
        while bid > 0:
            bid = int(self.m.body_parentid[bid])
            d += 1
        return d

    def _cadena(self, nombre_body, patron):
        bid = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, nombre_body)
        if bid < 0:
            raise ErrorRobot(f"el modelo no tiene el cuerpo '{nombre_body}'",
                             pista="cuerpos disponibles: " + ", ".join(
                                 (self._nombre_body(i) or "") for i in range(1, min(self.m.nbody, 60))))
        juntas = []
        while bid > 0:
            for k in range(int(self.m.body_jntnum[bid])):
                j = int(self.m.body_jntadr[bid]) + k
                if int(self.m.jnt_type[j]) not in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE)):
                    continue
                nombre = mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_JOINT, j) or ""
                if patron.search(nombre):
                    juntas.append(j)
            bid = int(self.m.body_parentid[bid])
        juntas.reverse()
        return juntas

    def _articulaciones_cabeza(self, patron):
        out = []
        for j in range(self.m.njnt):
            n = mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_JOINT, j) or ""
            if patron.search(n) and int(self.m.jnt_type[j]) == int(mujoco.mjtJoint.mjJNT_HINGE):
                out.append(j)
        return out

    def _base_libre(self):
        for j in range(self.m.njnt):
            if int(self.m.jnt_type[j]) == int(mujoco.mjtJoint.mjJNT_FREE):
                return int(self.m.jnt_qposadr[j])
        return None

    # ---------- estado ----------
    def reposo(self):
        mujoco.mj_resetData(self.m, self.d)
        if self.m.nkey > 0:
            mujoco.mj_resetDataKeyframe(self.m, self.d, 0)
        mujoco.mj_forward(self.m, self.d)

    def nombres(self, lado):
        return [mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_JOINT, j) for j in self.cadenas[lado]]

    def limites(self, lado):
        out = []
        for j in self.cadenas[lado]:
            if self.m.jnt_limited[j]:
                out.append(tuple(self.m.jnt_range[j]))
            else:
                out.append((-np.pi, np.pi))
        return out

    def articulaciones(self, lado):
        return np.array([self.d.qpos[self.m.jnt_qposadr[j]] for j in self.cadenas[lado]])

    def fijar_articulaciones(self, lado, valores, recortar=True):
        ch = self.cadenas[lado]
        if len(valores) != len(ch):
            raise ErrorRobot(f"el brazo {lado} necesita {len(ch)} valores y llegaron {len(valores)}")
        lim = self.limites(lado)
        for j, v, (lo, hi) in zip(ch, valores, lim):
            v = float(v)
            if recortar:
                v = min(max(v, lo), hi)
            self.d.qpos[self.m.jnt_qposadr[j]] = v
        mujoco.mj_kinematics(self.m, self.d)

    def fijar_cabeza(self, yaw, pitch):
        for j, v in zip(self.cabeza[:2], (yaw, pitch)):
            lo, hi = (self.m.jnt_range[j] if self.m.jnt_limited[j] else (-np.pi, np.pi))
            self.d.qpos[self.m.jnt_qposadr[j]] = min(max(float(v), lo), hi)
        mujoco.mj_kinematics(self.m, self.d)

    def pos_efector(self, lado):
        bid = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, self.efectores[lado])
        mujoco.mj_kinematics(self.m, self.d)
        return np.array(self.d.xpos[bid])

    # ---------- IK ----------
    def ik(self, lado, objetivo, iteraciones=40, amortiguacion=0.05, paso_max=0.3, tolerancia=1e-3):
        """Mueve las articulaciones del brazo hacia `objetivo` (x, y, z en el mundo).
        Devuelve (error_m, alcanzado)."""
        ch = self.cadenas[lado]
        bid = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, self.efectores[lado])
        dofs = [int(self.m.jnt_dofadr[j]) for j in ch]
        objetivo = np.asarray(objetivo, float)
        jacp = np.zeros((3, self.m.nv))
        err = np.inf
        for _ in range(iteraciones):
            mujoco.mj_kinematics(self.m, self.d)
            mujoco.mj_comPos(self.m, self.d)
            e = objetivo - self.d.xpos[bid]
            err = float(np.linalg.norm(e))
            if err < tolerancia:
                break
            mujoco.mj_jacBody(self.m, self.d, jacp, None, bid)
            J = jacp[:, dofs]
            dq = J.T @ np.linalg.solve(J @ J.T + amortiguacion ** 2 * np.eye(3), e)
            n = float(np.max(np.abs(dq)))
            if n > paso_max:
                dq *= paso_max / n
            q = self.articulaciones(lado) + dq
            self.fijar_articulaciones(lado, q)
        mujoco.mj_kinematics(self.m, self.d)
        err = float(np.linalg.norm(objetivo - self.pos_efector(lado)))
        return err, err < 0.02
