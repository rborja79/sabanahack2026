"""Robot falso: no mueve nada, pero se comporta como un robot con reglas.

Sirve para probar plantillas, seguridad y alertas sin hardware. Se pueden inyectar fallos:

    RobotFalso(fallas={"cambiar_modo": 1})      # el proximo cambiar_modo falla una vez
    RobotFalso(fallas={"enviar_velocidad": 99}) # simula un cable desconectado
"""
import math
import threading
import time

from ..nucleo.errores import ErrorConexion, ErrorRobot, NoSoportado
from ..nucleo.modos import GRAFO, ruta
from ..nucleo.robot import Robot


class RobotFalso(Robot):
    nombre = "falso"
    capacidades = frozenset({"caminar", "brazos", "cabeza", "manos", "hablar", "gestos"})
    vel_min = (0.1, 0.1, 0.1)
    vel_max = (1.0, 1.0, 1.0)

    def __init__(self, config=None, alertas=None, bateria=100.0, modo="pasivo", fallas=None,
                 gasto_por_s=0.0, estricto=True):
        super().__init__(config, alertas)
        self._lock = threading.RLock()
        self._bateria = float(bateria)
        self._modo = modo
        self._fallas = dict(fallas or {})
        self.gasto_por_s = gasto_por_s
        self.estricto = estricto
        self._conectado = False
        self.pose = [0.0, 0.0, 0.0]          # x, y, yaw
        self._vel = (0.0, 0.0, 0.0)
        self._t_vel = None
        self.registro = []                   # (t, metodo, args)
        self.dicho = []
        self.brazos_actuales = None
        self.cabeza_actual = (0.0, 0.0)
        self.manos_actuales = {}

    # ---------- utilidades ----------
    def _anotar(self, metodo, *args):
        with self._lock:
            self.registro.append((time.monotonic(), metodo, args))

    def _falla(self, metodo):
        with self._lock:
            n = self._fallas.get(metodo, 0)
            if n > 0:
                self._fallas[metodo] = n - 1
                raise ErrorConexion(f"fallo inyectado en {metodo}")

    def llamadas(self, metodo):
        with self._lock:
            return [a for (_, m, a) in self.registro if m == metodo]

    def _avanzar(self):
        """Integra la pose segun la ultima velocidad."""
        ahora = time.monotonic()
        with self._lock:
            if self._t_vel is not None:
                dt = ahora - self._t_vel
                vx, vy, wz = self._vel
                c, s = math.cos(self.pose[2]), math.sin(self.pose[2])
                self.pose[0] += (vx * c - vy * s) * dt
                self.pose[1] += (vx * s + vy * c) * dt
                self.pose[2] += wz * dt
                self._bateria = max(0.0, self._bateria - self.gasto_por_s * dt)
            self._t_vel = ahora

    # ---------- ciclo de vida ----------
    def conectar(self):
        self._falla("conectar")
        self._anotar("conectar")
        self._conectado = True

    def cerrar(self):
        self._conectado = False
        self._anotar("cerrar")

    def desconectar_cable(self):
        """Para simular que se cae la comunicacion."""
        self._conectado = False

    def fijar_bateria(self, valor):
        with self._lock:
            self._bateria = float(valor)

    def forzar_modo(self, modo):
        """Para simular que el robot cambia de modo por su cuenta (por ejemplo, una caida)."""
        with self._lock:
            self._modo = modo

    # ---------- estado ----------
    def estado(self):
        self._falla("estado")
        self._avanzar()
        with self._lock:
            return {"conectado": self._conectado, "modo": self._modo, "bateria": round(self._bateria, 1),
                    "pose": list(self.pose)}

    # ---------- modos ----------
    def cambiar_modo(self, modo):
        self._falla("cambiar_modo")
        self._avanzar()
        with self._lock:
            if modo not in self.grafo:
                raise ErrorRobot(f"modo desconocido: {modo}")
            if self.estricto and modo != self._modo and modo not in self.grafo[self._modo]:
                raise ErrorRobot(f"el robot rechaza pasar de '{self._modo}' a '{modo}'",
                                 pista="los cambios deben seguir el diagrama de transiciones")
            self._anotar("cambiar_modo", modo)
            self._modo = modo

    def preparar(self, modo):
        with self._lock:
            origen = self._modo
        for paso in ruta(origen, modo, self.grafo):
            self.cambiar_modo(paso)

    # ---------- movimiento ----------
    def enviar_velocidad(self, vx, vy, wz):
        self._falla("enviar_velocidad")
        if not self._conectado:
            raise ErrorConexion("el robot falso esta desconectado")
        self._avanzar()
        with self._lock:
            if (vx, vy, wz) != (0.0, 0.0, 0.0) and self._modo not in ("estable", "caminar"):
                raise ErrorRobot(f"no puede caminar en modo '{self._modo}'")
            if (vx, vy, wz) != (0.0, 0.0, 0.0):
                self._modo = "caminar"
            self._vel = (vx, vy, wz)
            self._anotar("enviar_velocidad", vx, vy, wz)

    def emergencia(self, nivel="detener"):
        self._anotar("emergencia", nivel)
        with self._lock:
            self._vel = (0.0, 0.0, 0.0)
            if nivel == "amortiguar":
                self._modo = "amortiguado"

    def gestos(self):
        return ["saludar", "levantar", "apretar_mano", "beso"]

    def gesto(self, nombre, lado="derecha"):
        self._falla("gesto")
        if nombre not in self.gestos():
            raise ErrorRobot(f"gesto desconocido: {nombre}")
        self._anotar("gesto", nombre, lado)

    # ---------- tren superior ----------
    def brazos(self, izq, der):
        self._falla("brazos")
        if len(izq) != 7 or len(der) != 7:
            raise ErrorRobot("cada brazo necesita 7 valores")
        self._anotar("brazos", list(izq), list(der))
        self.brazos_actuales = (list(izq), list(der))

    def cabeza(self, yaw, pitch):
        self._anotar("cabeza", yaw, pitch)
        self.cabeza_actual = (yaw, pitch)

    def mano(self, lado, valor, tipo="pinza"):
        self._falla("mano")
        if lado not in ("izquierda", "derecha"):
            raise ErrorRobot(f"lado invalido: {lado}")
        self._anotar("mano", lado, valor, tipo)
        self.manos_actuales[lado] = (valor, tipo)

    # ---------- interaccion ----------
    def hablar(self, texto):
        self._falla("hablar")
        self._anotar("hablar", texto)
        self.dicho.append(texto)
