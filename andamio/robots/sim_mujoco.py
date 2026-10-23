"""Robot simulado con el modelo MuJoCo del X2 (o el que indiques).

Hereda del robot falso (modos, bateria, fallos inyectables) y agrega un modelo cinematico:
los brazos y la cabeza mueven articulaciones de verdad, la base avanza segun la velocidad
y se puede pedir la pose de cada pieza para pintarla en el visor. No simula fisica.
"""
import math
import pathlib
import threading

import numpy as np

from ..cinematica import Modelo
from ..nucleo.errores import ErrorRobot
from .falso import RobotFalso

RAIZ_REPO = pathlib.Path(__file__).resolve().parents[2]
BUSCAR = [
    "robots/X2_URDF/X2-Ultra.xml", "robots/X2_URDF/scene.xml",
    "robots/Agibot X2-X2ultra/X2_URDF-v1.4.0/X2-Ultra.xml",
    "sim/mujoco_menagerie/unitree_g1/g1.xml",
]


def mallas_faltantes(xml):
    """Archivos de malla que el MJCF pide y no estan (descarga incompleta o 'solo en la nube')."""
    import xml.etree.ElementTree as ET
    xml = pathlib.Path(xml)
    try:
        raiz = ET.parse(xml).getroot()
    except Exception as e:
        return [f"(no se pudo leer el XML: {e})"]
    comp = raiz.find("compiler")
    base = xml.parent / ((comp.get("meshdir") if comp is not None else None) or "")
    faltan = []
    for m in raiz.iter("mesh"):
        f = m.get("file")
        if not f:
            continue
        p = base / f
        if not p.exists() or p.stat().st_size == 0:
            faltan.append(str(p.relative_to(xml.parent)) if p.is_relative_to(xml.parent) else str(p))
    return faltan


def buscar_modelo(ruta=""):
    if ruta:
        p = pathlib.Path(ruta)
        if not p.exists():
            raise ErrorRobot(f"no existe el modelo: {ruta}", pista="usa --modelo con la ruta a un .xml de MuJoCo")
        return p
    candidatos = [RAIZ_REPO / rel for rel in BUSCAR]
    if (RAIZ_REPO / "robots").exists():
        candidatos += sorted((RAIZ_REPO / "robots").rglob("X2-Ultra.xml"))
    incompletos = []
    for p in candidatos:
        if not p.exists():
            continue
        faltan = mallas_faltantes(p)
        if not faltan:
            return p
        incompletos.append(f"{p.relative_to(RAIZ_REPO)} (faltan {len(faltan)} mallas, por ejemplo {faltan[0]})")
    if incompletos:
        raise ErrorRobot("el modelo MuJoCo esta incompleto: " + "; ".join(incompletos),
                         pista="vuelve a descargar la carpeta completa del URDF/MJCF (si esta en iCloud o Dropbox, "
                               "marcala 'Descargar ahora' / 'Disponible sin conexion')")
    raise ErrorRobot("no se encontro un modelo MuJoCo",
                     pista="copia el URDF/MJCF del X2 en robots/ o pasa --modelo ruta.xml")


class RobotSim(RobotFalso):
    nombre = "sim"

    def __init__(self, config=None, alertas=None, modelo="", efectores=None, **kw):
        super().__init__(config, alertas, **kw)
        self.ruta_modelo = buscar_modelo(modelo or (config or {}).get("sim", {}).get("modelo", ""))
        self.modelo = Modelo(self.ruta_modelo, efectores)
        self._mlock = threading.RLock()
        self.apertura = {"izquierda": 1.0, "derecha": 1.0}
        self._sincronizar_base()

    # ---------- base ----------
    def _sincronizar_base(self):
        b = self.modelo.base
        if b is None:
            return
        x, y, yaw = self.pose
        q = self.modelo.d.qpos
        q[b], q[b + 1] = x, y
        q[b + 3], q[b + 4], q[b + 5], q[b + 6] = math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)
        import mujoco
        mujoco.mj_kinematics(self.modelo.m, self.modelo.d)

    def estado(self):
        est = super().estado()
        with self._mlock:
            self._sincronizar_base()
        return est

    # ---------- tren superior ----------
    def brazos(self, izq, der):
        super().brazos(izq, der)
        n = len(self.modelo.cadenas["izquierda"])
        if n != 7 or len(self.modelo.cadenas["derecha"]) != 7:
            raise ErrorRobot(f"el modelo tiene brazos de {n} articulaciones, se esperaban 7")
        with self._mlock:
            self.modelo.fijar_articulaciones("izquierda", izq)
            self.modelo.fijar_articulaciones("derecha", der)

    def cabeza(self, yaw, pitch):
        super().cabeza(yaw, pitch)
        with self._mlock:
            if self.modelo.cabeza:
                self.modelo.fijar_cabeza(yaw, pitch)

    def mano(self, lado, valor, tipo="pinza"):
        super().mano(lado, valor, tipo)
        self.apertura[lado] = float(valor)

    def mover_mano_a(self, lado, objetivo):
        """IK hacia un punto del mundo. Devuelve (error_m, alcanzado)."""
        with self._mlock:
            return self.modelo.ik(lado, objetivo)

    # ---------- para el visor ----------
    def poses(self):
        """Posicion y orientacion de cada pieza, en el mismo formato que el puente anterior."""
        with self._mlock:
            self._sincronizar_base()
            d, m = self.modelo.d, self.modelo.m
            p = np.round(d.xpos[1:], 4).tolist()
            q = np.round(d.xquat[1:], 4).tolist()
        return p, q

    def nombres_piezas(self):
        import mujoco
        return [mujoco.mj_id2name(self.modelo.m, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(1, self.modelo.m.nbody)]

    def qpos(self):
        with self._mlock:
            return [round(float(v), 5) for v in self.modelo.d.qpos]
