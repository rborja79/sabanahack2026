"""Cliente del servidor del robot: hace que un robot que esta en otra maquina (por ejemplo
el contenedor del X2) se vea como un robot local. Sirve para planear, hacer IK y mostrar el
visor en el Mac mientras el codigo que toca ROS corre junto al robot.
"""
import json
import os
import socket
import threading

from ..nucleo import errores
from ..nucleo.errores import ErrorConexion, ErrorRobot
from ..nucleo.robot import Robot

SIN_RESPUESTA = {"enviar_velocidad", "brazos", "cabeza"}


class RobotRemoto(Robot):
    nombre = "remoto"

    def __init__(self, config=None, alertas=None, host=None, puerto=None, token=None):
        super().__init__(config, alertas)
        from ..config import DEFECTO
        c = {**DEFECTO["remoto"], **(config or {}).get("remoto", {})}
        self.host = host or c["host"]
        self.puerto = int(puerto or c["puerto"])
        self.token = token if token is not None else (c["token"] or os.environ.get("ANDAMIO_TOKEN", ""))
        self.timeout = float(c["timeout_s"])
        self._sock = None
        self._lock = threading.Lock()
        self._espera = {}
        self._id = 0
        self._error_pendiente = None
        self._vivo = False

    # ---------- conexion ----------
    def conectar(self):
        if not self.token:
            raise ErrorConexion("falta el token", pista="define ANDAMIO_TOKEN (el mismo que uso el servidor)")
        try:
            self._sock = socket.create_connection((self.host, self.puerto), timeout=self.timeout)
        except OSError as e:
            raise ErrorConexion(f"no se pudo conectar a {self.host}:{self.puerto} ({e})",
                                pista="revisa que el servidor este corriendo (python -m andamio.servidor_robot), "
                                      "la IP y que el puerto este publicado en el contenedor")
        self._sock.settimeout(None)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._vivo = True
        self._lector = threading.Thread(target=self._leer, daemon=True, name="andamio-remoto-lector")
        self._lector.start()
        meta = self._rpc("hola", token=self.token)
        self.nombre = "remoto:" + meta["nombre"]
        self.capacidades = frozenset(meta["capacidades"])
        self.vel_min, self.vel_max = tuple(meta["vel_min"]), tuple(meta["vel_max"])
        self.grafo = {k: set(v) for k, v in meta["grafo"].items()}
        self.confirmaciones = meta["confirmaciones"]
        self.modos_para = {k: set(v) for k, v in meta["modos_para"].items()}
        if self.alertas:
            self.alertas.info(f"conectado al servidor del robot {self.host}:{self.puerto} ({meta['nombre']})")

    def cerrar(self):
        self._vivo = False
        try:
            if self._sock:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)   # sin esto el lector mantiene abierta la conexion
                except OSError:
                    pass
                self._sock.close()
        except OSError:
            pass

    def _leer(self):
        try:
            with self._sock.makefile("r", encoding="utf-8") as f:
                for linea in f:
                    try:
                        msg = json.loads(linea)
                    except ValueError:
                        continue
                    if "ev" in msg:
                        self._evento(msg)
                        continue
                    esp = self._espera.pop(msg.get("id"), None)
                    if esp:
                        esp["r"] = msg
                        esp["e"].set()
        except (OSError, ValueError):
            pass
        finally:
            self._vivo = False
            for esp in list(self._espera.values()):
                esp["e"].set()

    def _evento(self, msg):
        if msg["ev"] == "error":
            self._error_pendiente = (msg.get("clase"), msg.get("msg"), msg.get("pista", ""))
            if self.alertas:
                self.alertas.error(f"el servidor del robot informa: {msg.get('msg')}", pista=msg.get("pista", ""))

    # ---------- rpc ----------
    def _enviar(self, obj):
        datos = (json.dumps(obj) + "\n").encode()
        try:
            with self._lock:
                self._sock.sendall(datos)
        except (OSError, AttributeError) as e:
            self._vivo = False
            raise ErrorConexion(f"se perdio la conexion con el servidor del robot: {e}",
                                pista="revisa el cable/Wi-Fi; el servidor frena el robot solo")

    def _rpc(self, metodo, *args, **extra):
        if not self._vivo:
            raise ErrorConexion("sin conexion con el servidor del robot")
        with self._lock:
            self._id += 1
            rid = self._id
        esp = {"e": threading.Event(), "r": None}
        self._espera[rid] = esp
        self._enviar({"id": rid, "m": metodo, "a": list(args), **extra})
        if not esp["e"].wait(self.timeout):
            self._espera.pop(rid, None)
            raise ErrorConexion(f"el servidor no respondio a '{metodo}' en {self.timeout} s")
        r = esp["r"]
        if r is None:
            raise ErrorConexion("se cerro la conexion con el servidor del robot")
        if not r.get("ok"):
            clase = getattr(errores, r.get("clase", ""), errores.ErrorRobot)
            if not (isinstance(clase, type) and issubclass(clase, errores.ErrorAndamio)):
                clase = errores.ErrorRobot
            raise clase(r.get("msg", "error"), pista=r.get("pista", ""))
        return r.get("r")

    def _notificar(self, metodo, *args):
        if self._error_pendiente:
            clase, msg, pista = self._error_pendiente
            self._error_pendiente = None
            c = getattr(errores, clase or "", errores.ErrorRobot)
            raise (c if isinstance(c, type) and issubclass(c, errores.ErrorAndamio) else errores.ErrorRobot)(msg, pista=pista)
        if not self._vivo:
            raise ErrorConexion("sin conexion con el servidor del robot")
        self._enviar({"m": metodo, "a": list(args)})

    # ---------- interfaz Robot ----------
    def estado(self):
        est = self._rpc("estado")
        est["conectado"] = bool(est.get("conectado", True)) and self._vivo
        return est

    def modos(self):
        return self._rpc("modos")

    def cambiar_modo(self, modo):
        self._rpc("cambiar_modo", modo)

    def preparar(self, modo):
        self._rpc("preparar", modo)

    def enviar_velocidad(self, vx, vy, wz):
        self._notificar("enviar_velocidad", vx, vy, wz)

    def detener(self):
        self._notificar("enviar_velocidad", 0.0, 0.0, 0.0)

    def emergencia(self, nivel="detener"):
        self._rpc("emergencia", nivel)

    def gestos(self):
        return self._rpc("gestos")

    def gesto(self, nombre, lado="derecha"):
        self._rpc("gesto", nombre, lado)

    def brazos(self, izq, der):
        self._notificar("brazos", list(izq), list(der))

    def cabeza(self, yaw, pitch):
        self._notificar("cabeza", yaw, pitch)

    def mano(self, lado, valor, tipo="pinza"):
        self._rpc("mano", lado, valor, tipo)

    def hablar(self, texto):
        self._rpc("hablar", texto)

    def video(self, ruta, repetir=False):
        self._rpc("video", ruta, bool(repetir))

    def audio(self, ruta):
        self._rpc("audio", ruta)

    def expresion(self, emocion, repetir=False):
        self._rpc("expresion", emocion, bool(repetir))

    def luces(self, modo, color):
        self._rpc("luces", modo, list(color))

    # ---------- vision (la camara y el detector viven en el robot) ----------
    def ver_remoto(self):
        return self._rpc("ver") or []

    def foto_remota(self):
        return self._rpc("foto") or ""
