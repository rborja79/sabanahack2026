"""Adaptador del AgiBot D1 (cuadrupedo, SDK ZSL-1 en Python, solo Linux).

Usa la libreria oficial `mc_sdk_zsl_1_py` (CPython 3.10, x86_64 o aarch64). Hay que apuntar a
la carpeta del SDK (la que contiene lib/) con `d1.sdk` en config.yaml o ANDAMIO_D1__SDK.

Notas del manual:
  * move(vx, vy, wz): 0 si no se mueve; rangos vx 0.05-3 m/s, vy 0.1-1 m/s, wz 0.02-3 rad/s.
  * Solo se mueve estando de pie. Devuelve un codigo: 0 es correcto, 0x30xx son errores.
  * Las acrobacias (salto, voltereta) desgastan motores y pueden danar el robot: estan
    desactivadas salvo que se active d1.acrobacias.
  * El D1 no tiene brazos ni manos.
"""
import importlib
import os
import platform
import sys
import threading
import time

from ..nucleo.errores import ErrorConexion, ErrorRobot
from ..nucleo.robot import Robot

CODIGOS = {
    0x3012: "se perdieron los datos de los motores",
    0x3010: "motores deshabilitados",
    0x3011: "falla de motor",
    0x3009: "angulo de motor fuera de rango",
    0x3007: "fallo el cambio de estado (el robot no esta en un estado que lo permita)",
    0x3013: "velocidad demasiado grande",
}
MODO_D1 = {0: "amortiguado", 1: "estable", 10: "amortiguado", 18: "caminar", 21: "estable", 51: "amortiguado"}
GRAFO_D1 = {
    "pasivo": {"amortiguado", "estable"},
    "amortiguado": {"pasivo", "estable"},
    "estable": {"pasivo", "amortiguado", "caminar"},
    "caminar": {"estable"},
}


class RobotD1(Robot):
    nombre = "d1"
    capacidades = frozenset({"caminar", "gestos"})
    vel_min = (0.05, 0.1, 0.02)
    vel_max = (3.0, 1.0, 3.0)
    grafo = GRAFO_D1
    confirmaciones = {}
    modos_para = {"caminar": {"estable", "caminar"}, "gestos": {"estable"}}

    def __init__(self, config=None, alertas=None, sdk=None):
        super().__init__(config, alertas)
        from ..config import DEFECTO
        self.cfg = {**DEFECTO["d1"], **(config or {}).get("d1", {})}
        self.sdk = sdk                 # inyectable para pruebas: objeto con la API de HighLevel
        self._lock = threading.RLock()
        self._ult_vel = (0.0, 0.0, 0.0)
        self._conectado = False

    def modos(self):
        return list(GRAFO_D1)

    # ---------- ciclo de vida ----------
    def _cargar_sdk(self):
        raiz = self.cfg.get("sdk") or os.environ.get("D1_SDK", "")
        arq = platform.machine().replace("amd64", "x86_64").replace("arm64", "aarch64")
        if raiz:
            lib = os.path.join(raiz, "lib", "zsl-1", arq)
            if not os.path.isdir(lib):
                raise ErrorConexion(f"no existe {lib}", pista="d1.sdk debe ser la carpeta que contiene lib/")
            sys.path.insert(0, lib)
        try:
            return importlib.import_module("mc_sdk_zsl_1_py")
        except ImportError as e:
            raise ErrorConexion(
                f"no se pudo cargar mc_sdk_zsl_1_py ({e})",
                pista=f"solo funciona en Linux con Python 3.10 ({arq}); define d1.sdk o D1_SDK con la carpeta del SDK")

    def conectar(self):
        if self.sdk is None:
            modulo = self._cargar_sdk()
            self.sdk = modulo.HighLevel()
            try:
                self.sdk.initRobot(self.cfg["ip_local"], int(self.cfg["puerto"]), self.cfg["ip_robot"])
            except Exception as e:
                raise ErrorConexion(f"initRobot fallo: {e}",
                                    pista=f"tu IP debe ser {self.cfg['ip_local']} en la red del robot ({self.cfg['ip_robot']})")
        time.sleep(0.5)
        if not self._revisar_conexion():
            raise ErrorConexion("el D1 no responde",
                                pista=f"ping {self.cfg['ip_robot']}; cable o Wi-Fi del robot; IP local {self.cfg['ip_local']}")
        self._conectado = True
        self.alertas and self.alertas.info("D1 conectado")

    def _revisar_conexion(self):
        try:
            return bool(self.sdk.checkConnection())
        except Exception:
            return False

    def cerrar(self):
        try:
            self.detener()
        except Exception:
            pass
        self._conectado = False

    # ---------- estado ----------
    def estado(self):
        ok = self._revisar_conexion() if self.sdk is not None else False
        modo, bat = None, None
        if ok:
            try:
                modo = MODO_D1.get(int(self.sdk.getCurrentCtrlmode()))
                bat = float(self.sdk.getBatteryPower())
            except Exception as e:
                self.alertas and self.alertas.aviso(f"no se pudo leer el estado del D1: {e}")
        return {"conectado": ok, "modo": modo, "bateria": bat}

    def _comprobar(self, codigo, accion):
        codigo = 0 if codigo is None else int(codigo)
        if codigo != 0:
            raise ErrorRobot(f"el D1 rechazo '{accion}': {CODIGOS.get(codigo, hex(codigo))}",
                             pista="si es 0x3007, ponlo de pie primero (preparar: estable)")

    # ---------- modos ----------
    def cambiar_modo(self, modo):
        with self._lock:
            if modo == "estable":
                self._comprobar(self.sdk.standUp(), "levantarse")
            elif modo == "amortiguado":
                self._comprobar(self.sdk.lieDown(), "echarse")
            elif modo == "pasivo":
                self._comprobar(self.sdk.passive(), "pasivo")
            elif modo == "caminar":
                return                       # se entra a caminar al mandar velocidad desde de pie
            else:
                raise ErrorRobot(f"el D1 no tiene el modo '{modo}'", pista=f"modos: {self.modos()}")
        fin = time.monotonic() + 8.0
        esperado = modo
        while time.monotonic() < fin:
            if self.estado().get("modo") == esperado:
                return
            time.sleep(0.3)
        raise ErrorRobot(f"el D1 no llego al modo '{modo}' en 8 s")

    # ---------- movimiento ----------
    def enviar_velocidad(self, vx, vy, wz):
        with self._lock:
            self._comprobar(self.sdk.move(float(vx), float(vy), float(wz)), "mover")
            self._ult_vel = (vx, vy, wz)

    def emergencia(self, nivel="detener"):
        for _ in range(3):
            try:
                self.sdk.move(0.0, 0.0, 0.0)
            except Exception:
                break
            time.sleep(0.01)
        if nivel == "amortiguar":
            try:
                self.sdk.passive()
            except Exception:
                pass

    def gestos(self):
        g = ["saludar"]
        if self.cfg.get("acrobacias"):
            g += ["salto", "salto_frontal", "voltereta"]
        return g

    def gesto(self, nombre, lado="derecha"):
        mapa = {"saludar": "shakeHand"}
        if self.cfg.get("acrobacias"):
            mapa.update({"salto": "jump", "salto_frontal": "frontJump", "voltereta": "backflip"})
        if nombre not in mapa:
            if nombre in ("salto", "salto_frontal", "voltereta"):
                raise ErrorRobot(f"'{nombre}' esta desactivado por seguridad",
                                 pista="activa d1.acrobacias solo si el responsable del robot lo autoriza")
            raise ErrorRobot(f"gesto desconocido: {nombre}", pista=f"gestos: {self.gestos()}")
        with self._lock:
            self._comprobar(getattr(self.sdk, mapa[nombre])(), nombre)
        time.sleep(4.0)
