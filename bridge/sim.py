"""Simulacion del robot y cinematica inversa.

Funciona sin robot fisico. Si el viernes hay un robot de verdad, lo unico que
cambia es de donde salen las posiciones: se reemplaza `paso()` por la lectura
del robot y `aplicar_objetivo()` por el envio de comandos.
"""
import pathlib
import numpy as np
import mujoco

MENAGERIE = pathlib.Path(__file__).resolve().parents[1] / "sim" / "mujoco_menagerie"

# Que body sigue a cada mano, por robot.
EFECTORES = {
    "unitree_g1": {"left": "left_wrist_yaw_link", "right": "right_wrist_yaw_link"},
    "unitree_z1": {"right": "link06"},
    "unitree_go2": {},
}


class Robot:
    def __init__(self, modelo="unitree_g1", amortiguacion=0.08, ganancia=0.6):
        self.modelo = modelo
        ruta = MENAGERIE / modelo / "scene.xml"
        self.m = mujoco.MjModel.from_xml_path(str(ruta))
        self.d = mujoco.MjData(self.m)
        self.amortiguacion = amortiguacion
        self.ganancia = ganancia
        self.bodies = [mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_BODY, i)
                       for i in range(self.m.nbody)]
        self.indices_body = [i for i, b in enumerate(self.bodies) if b != "world"]
        self.nombres_body = [self.bodies[i] for i in self.indices_body]
        self.efectores = EFECTORES.get(modelo, {})
        self.cadenas = {lado: self._cadena(nombre) for lado, nombre in self.efectores.items()}
        self.objetivos = {}
        self._jacp = np.zeros((3, self.m.nv))
        self._jacr = np.zeros((3, self.m.nv))
        self.reposo()

    # ---------- estado ----------
    def reposo(self):
        mujoco.mj_resetData(self.m, self.d)
        clave = 0 if self.m.nkey > 0 else None
        if clave is not None:
            mujoco.mj_resetDataKeyframe(self.m, self.d, clave)
        mujoco.mj_forward(self.m, self.d)

    def _cadena(self, nombre_body):
        """Indices de grados de libertad desde la raiz hasta ese body."""
        bid = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, nombre_body)
        if bid < 0:
            return np.array([], dtype=int)
        dofs = []
        while bid > 0:
            inicio = int(self.m.body_dofadr[bid])
            n = int(self.m.body_dofnum[bid])
            if inicio >= 0 and n > 0:
                # el cuerpo libre de la pelvis no se mueve con la mano
                if not (self.m.body_jntnum[bid] == 1 and
                        self.m.jnt_type[self.m.body_jntadr[bid]] == mujoco.mjtJoint.mjJNT_FREE):
                    dofs.extend(range(inicio, inicio + n))
            bid = int(self.m.body_parentid[bid])
        return np.array(sorted(dofs), dtype=int)

    # ---------- control ----------
    def fijar_objetivo(self, lado, punto):
        if lado in self.efectores and punto is not None:
            self.objetivos[lado] = np.asarray(punto, dtype=float)

    def _ik(self, lado, iteraciones=2):
        nombre = self.efectores[lado]
        dofs = self.cadenas[lado]
        if len(dofs) == 0:
            return
        bid = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, nombre)
        objetivo = self.objetivos[lado]
        for _ in range(iteraciones):
            mujoco.mj_jacBody(self.m, self.d, self._jacp, self._jacr, bid)
            err = objetivo - self.d.xpos[bid]
            norma = np.linalg.norm(err)
            if norma < 1e-3:
                return
            err = err * min(1.0, 0.08 / max(norma, 1e-9)) if norma > 0.08 else err
            J = self._jacp[:, dofs]
            lam = self.amortiguacion
            dq = J.T @ np.linalg.solve(J @ J.T + lam * lam * np.eye(3), err)
            for k, dof in enumerate(dofs):
                jid = int(self.m.dof_jntid[dof])
                qadr = int(self.m.jnt_qposadr[jid])
                v = self.d.qpos[qadr] + self.ganancia * dq[k]
                if self.m.jnt_limited[jid]:
                    lo, hi = self.m.jnt_range[jid]
                    v = float(np.clip(v, lo, hi))
                self.d.qpos[qadr] = v
            mujoco.mj_forward(self.m, self.d)

    def paso(self):
        for lado in list(self.objetivos):
            if lado in self.efectores:
                self._ik(lado)
        mujoco.mj_forward(self.m, self.d)

    # ---------- salida ----------
    def estado(self):
        """Posiciones y cuaterniones de cada body, planos, para el visor."""
        p = self.d.xpos[self.indices_body].astype(np.float32).ravel()
        q = self.d.xquat[self.indices_body].astype(np.float32).ravel()  # wxyz
        return p.tolist(), q.tolist()

    def qpos(self):
        return self.d.qpos.astype(np.float32).tolist()

    def pos_efector(self, lado):
        nombre = self.efectores.get(lado)
        if not nombre:
            return None
        bid = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, nombre)
        return self.d.xpos[bid].astype(float).tolist()
