"""Robot simulado con el modelo MuJoCo del X2 (o el que indiques).

Hereda del robot falso (modos, bateria, fallos inyectables) y agrega un modelo cinematico:
los brazos y la cabeza mueven articulaciones de verdad, la base avanza segun la velocidad
y se puede pedir la pose de cada pieza para pintarla en el visor. No simula fisica.
"""
import math
import pathlib
import threading
import time

import numpy as np

from ..cinematica import Modelo
from ..nucleo.errores import ErrorRobot
from .falso import RobotFalso

RAIZ_REPO = pathlib.Path(__file__).resolve().parents[2]
BUSCAR = [
    "robots/X2_URDF/scene.xml", "robots/X2_URDF/X2-Ultra.xml",
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
        self.marcadores = []              # [{"clase", "x", "y"}] que se dibujan en el visor 3D (ojo simulado)
        self._visor = None
        self._sincronizar_base()

    # ---------- visor 3D (ventana de MuJoCo) ----------
    def abrir_visor_3d(self):
        """Abre una ventana 3D que sigue al robot. En el Mac hay que lanzar con mjpython:
            .venv/bin/mjpython -m andamio PLANTILLA --robot sim --ver3d"""
        try:
            import mujoco
            import mujoco.viewer
            self._visor = mujoco.viewer.launch_passive(self.modelo.m, self.modelo.d,
                                                       show_left_ui=False, show_right_ui=False)
        except Exception as e:
            pista = ("en el Mac lanza con:  .venv/bin/mjpython -m andamio ... --robot sim --ver3d"
                     if "mjpython" in str(e) else "el visor 3D necesita pantalla (no funciona por SSH sin X)")
            raise ErrorRobot(f"no se pudo abrir el visor 3D: {e}", pista=pista)
        try:
            v = self._visor
            v.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
            az, dist = 210.0, 5.0
            if self.marcadores:                      # de lado, para ver robot y objetivo a la vez
                dx = float(self.marcadores[0]["x"]) - self.pose[0]
                dy = float(self.marcadores[0]["y"]) - self.pose[1]
                az = math.degrees(math.atan2(dy, dx)) - 90
                dist = max(5.0, 1.6 * math.hypot(dx, dy))
            v.cam.distance, v.cam.elevation, v.cam.azimuth = dist, -22, az
        except Exception:
            pass
        self._seguir_camara = True
        threading.Thread(target=self._bucle_visor, daemon=True, name="andamio-visor3d").start()
        if self.alertas:
            self.alertas.info("visor 3D abierto (cierra la ventana o pulsa Ctrl+C para salir)")

    def visor_abierto(self):
        return self._visor is not None and self._visor.is_running()

    def _bucle_visor(self):
        import mujoco
        while self.visor_abierto():
            t0 = time.monotonic()
            try:
                self._avanzar()
                with self._mlock:
                    self._sincronizar_base()
                    x, y = self.pose[0], self.pose[1]
                    marcas = list(self.marcadores)
                with self._visor.lock():
                    scn = self._visor.user_scn
                    scn.ngeom = 0
                    for mk in marcas[: max(0, scn.maxgeom - 1)]:
                        mujoco.mjv_initGeom(scn.geoms[scn.ngeom], mujoco.mjtGeom.mjGEOM_CAPSULE,
                                            np.array([0.18, 0.65, 0.0]),
                                            np.array([float(mk["x"]), float(mk["y"]), 0.85]),
                                            np.eye(3).flatten(), np.array([0.25, 0.8, 0.5, 0.85], dtype=np.float32))
                        scn.ngeom += 1
                    if getattr(self, "_seguir_camara", False):
                        if marcas:
                            x, y = (x + float(marcas[0]["x"])) / 2, (y + float(marcas[0]["y"])) / 2
                        self._visor.cam.lookat[:] = (x, y, 0.6)
                # sync() FUERA de los candados: en el Mac (mjpython) espera al hilo grafico y,
                # si se llama con el candado tomado, se bloquea todo
                self._visor.sync()
            except Exception:
                pass
            time.sleep(max(0.0, 1 / 30 - (time.monotonic() - t0)))

    def cerrar(self):
        if self._visor is not None:
            try:
                self._visor.close()
            except Exception:
                pass
        super().cerrar()

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
