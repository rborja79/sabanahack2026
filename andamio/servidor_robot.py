"""Servidor del robot: corre junto al robot de verdad (por ejemplo dentro del contenedor del
X2) y recibe ordenes por TCP desde otro computador, como el Mac.

Solo usa la libreria estandar. Protocolo: una linea JSON por mensaje.

  cliente -> {"id": 1, "m": "hola", "token": "..."}        servidor -> {"id": 1, "ok": true, "r": {...meta...}}
  cliente -> {"id": 2, "m": "cambiar_modo", "a": ["estable"]}  servidor -> {"id": 2, "ok": true, "r": null}
  cliente -> {"m": "enviar_velocidad", "a": [0.2, 0, 0]}       (sin id: no hay respuesta; los errores llegan como evento)

Seguridad en este lado, independiente del cliente:
  * exige el token (ANDAMIO_TOKEN) y un solo cliente a la vez;
  * la velocidad la repite el servidor a 50 Hz y caduca a los 0.3 s si el cliente se calla;
  * si se cae la conexion se detiene el robot;
  * recorta velocidades a los limites configurados y rechaza numeros no finitos.

Uso (dentro del contenedor o en la unidad de desarrollo):

    python -m andamio.servidor_robot --robot x2 --puerto 8790
"""
import argparse
import base64
import hmac
import json
import math
import os
import socket
import socketserver
import sys
import threading
import time

from .nucleo.errores import ErrorAndamio, ErrorConexion

PERMITIDOS = {"estado", "modos", "cambiar_modo", "preparar", "enviar_velocidad", "detener", "emergencia",
              "gestos", "gesto", "brazos", "cabeza", "mano", "hablar", "ver", "foto",
              "video", "audio", "expresion", "luces"}
SIN_RESPUESTA = {"enviar_velocidad", "brazos", "cabeza"}


def meta_robot(robot):
    return {"nombre": robot.nombre, "capacidades": sorted(robot.capacidades), "vel_min": list(robot.vel_min),
            "vel_max": list(robot.vel_max), "grafo": {k: sorted(v) for k, v in robot.grafo.items()},
            "confirmaciones": dict(robot.confirmaciones),
            "modos_para": {k: sorted(v) for k, v in robot.modos_para.items()}}


class ServidorRobot:
    def __init__(self, robot, alertas, cfg, token, host="0.0.0.0", puerto=8790, hz=50, caduca_s=0.3,
                 silencio_s=4.0, ojo=None):
        if not token or len(token) < 12 or token.startswith("cambia-esto") or token.startswith("pon-aqui"):
            raise ErrorConexion("el servidor necesita un token propio de al menos 12 caracteres",
                                pista="define ANDAMIO_TOKEN con algo largo y aleatorio (no el del .env.ejemplo)")
        self.robot, self.alertas, self.cfg = robot, alertas, cfg["seguridad"] if "seguridad" in cfg else cfg
        self.token = token
        self.ojo = ojo
        self.host, self.puerto = host, puerto
        self.periodo = 1.0 / hz
        self.caduca_s = caduca_s
        self.silencio_s = silencio_s
        self._lock = threading.Lock()
        self._vel = (0.0, 0.0, 0.0)
        self._t_vel = 0.0
        self._ceros = 0
        self._cliente = None
        self._fin = threading.Event()
        self._srv = None
        self._conexiones = set()
        self.envios = 0

    # ---------- repetidor de velocidad ----------
    def _repetir(self):
        siguiente = time.monotonic()
        while not self._fin.is_set():
            ahora = time.monotonic()
            with self._lock:
                vel, t = self._vel, self._t_vel
                if vel != (0.0, 0.0, 0.0) and ahora - t > self.caduca_s:
                    self._vel = vel = (0.0, 0.0, 0.0)
                    self._ceros = int(0.5 / self.periodo)
                    self.alertas.aviso("el cliente dejo de enviar velocidad; el servidor frena")
                ceros = self._ceros
                if vel == (0.0, 0.0, 0.0) and ceros > 0:
                    self._ceros -= 1
            if vel != (0.0, 0.0, 0.0) or ceros > 0:
                try:
                    self.robot.enviar_velocidad(*vel)
                    self.envios += 1
                except Exception as e:
                    self.alertas.error(f"fallo enviando velocidad al robot: {e}")
                    self._avisar({"ev": "error", "clase": type(e).__name__, "msg": str(e),
                                  "pista": getattr(e, "pista", "")})
            siguiente += self.periodo
            espera = siguiente - time.monotonic()
            if espera > 0:
                self._fin.wait(espera)
            else:
                siguiente = time.monotonic()

    def _avisar(self, evento):
        c = self._cliente
        if c is not None:
            c.enviar(evento)

    def _fijar_velocidad(self, vx, vy, wz):
        vals = []
        for v, tope in zip((vx, vy, wz), (self.cfg["vx_max"], self.cfg["vy_max"], self.cfg["wz_max"])):
            v = float(v)
            if not math.isfinite(v):
                raise ErrorAndamio("velocidad no finita")
            vals.append(math.copysign(min(abs(v), tope), v) if v else 0.0)
        for v, minimo in zip(vals, self.robot.vel_min):
            if v and abs(v) < minimo:
                raise ErrorAndamio(f"velocidad {v} bajo el minimo {minimo} del robot")
        with self._lock:
            self._vel = tuple(vals)
            self._t_vel = time.monotonic()
            if self._vel == (0.0, 0.0, 0.0):
                self._ceros = int(0.5 / self.periodo)

    def parar_todo(self, motivo):
        with self._lock:
            self._vel = (0.0, 0.0, 0.0)
            self._ceros = int(0.5 / self.periodo)
        self.alertas.aviso(f"servidor: se detiene el robot ({motivo})")
        try:
            self.robot.detener()
        except Exception:
            pass

    # ---------- despacho ----------
    def despachar(self, msg):
        m = msg.get("m")
        a = msg.get("a", [])
        if m not in PERMITIDOS:
            raise ErrorAndamio(f"metodo no permitido: {m}")
        if not isinstance(a, list):
            raise ErrorAndamio("los argumentos deben ser una lista")
        if m in ("brazos", "cabeza", "mano"):
            for v in a:                      # JSON acepta NaN e Infinity: se rechazan antes del driver
                for x in (v if isinstance(v, list) else [v]):
                    if isinstance(x, float) and not math.isfinite(x):
                        raise ErrorAndamio(f"{m}: valor no finito")
        if m == "enviar_velocidad":
            self._fijar_velocidad(*a)
            return None
        if m == "detener":
            self._fijar_velocidad(0.0, 0.0, 0.0)
            return None
        if m in ("ver", "foto"):
            if self.ojo is None:
                from .nucleo.errores import NoSoportado
                raise NoSoportado("el servidor del robot no tiene ojo",
                                  pista="inicia el servidor con --ojo x2 (necesita opencv en el contenedor)")
            if m == "ver":
                return self.ojo.ver()
            datos = self.ojo.jpeg()
            return base64.b64encode(datos).decode() if datos else ""
        if m == "emergencia":
            with self._lock:
                self._vel = (0.0, 0.0, 0.0)
            return self.robot.emergencia(*a)
        return getattr(self.robot, m)(*a)

    # ---------- red ----------
    def servir(self):
        servidor = self

        class Manejador(socketserver.StreamRequestHandler):
            def setup(self):
                super().setup()
                self.lock = threading.Lock()

            def enviar(self, obj):
                try:
                    with self.lock:
                        self.wfile.write((json.dumps(obj, default=str) + "\n").encode())
                        self.wfile.flush()
                except OSError:
                    pass

            def handle(self):
                servidor._conexiones.add(self.request)
                self.request.settimeout(servidor.silencio_s)
                autenticado = False
                try:
                    for crudo in self.rfile:
                        try:
                            msg = json.loads(crudo)
                        except ValueError:
                            self.enviar({"ok": False, "clase": "ErrorAndamio", "msg": "JSON invalido"})
                            continue
                        rid = msg.get("id")
                        if not autenticado:
                            if msg.get("m") != "hola" or not hmac.compare_digest(
                                    str(msg.get("token", "")), servidor.token):
                                servidor.alertas.error(f"conexion rechazada de {self.client_address[0]}: token incorrecto")
                                self.enviar({"id": rid, "ok": False, "clase": "ErrorConexion", "msg": "token incorrecto"})
                                return
                            if servidor._cliente is not None:
                                self.enviar({"id": rid, "ok": False, "clase": "ErrorConexion",
                                             "msg": "ya hay otro computador controlando el robot"})
                                return
                            autenticado = True
                            servidor._cliente = self
                            servidor.alertas.info(f"cliente conectado desde {self.client_address[0]}")
                            self.enviar({"id": rid, "ok": True, "r": meta_robot(servidor.robot)})
                            continue
                        try:
                            r = servidor.despachar(msg)
                            if rid is not None:
                                self.enviar({"id": rid, "ok": True, "r": r})
                        except Exception as e:
                            servidor.alertas.error(f"{msg.get('m')}: {e}")
                            err = {"clase": type(e).__name__, "msg": str(e), "pista": getattr(e, "pista", "")}
                            if rid is not None:
                                self.enviar({"id": rid, "ok": False, **err})
                            else:
                                self.enviar({"ev": "error", **err})
                except (OSError, TimeoutError):
                    pass
                finally:
                    servidor._conexiones.discard(self.request)
                    if autenticado:
                        servidor._cliente = None
                        servidor.parar_todo("se perdio el cliente")

        class Servidor(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._srv = Servidor((self.host, self.puerto), Manejador)
        threading.Thread(target=self._repetir, daemon=True, name="andamio-repetidor").start()
        self.alertas.info(f"servidor del robot en {self.host}:{self.puerto}")
        try:
            self._srv.serve_forever(poll_interval=0.2)
        finally:
            self._fin.set()

    def cerrar(self):
        self._fin.set()
        for c in list(self._conexiones):
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()


def _leer_env():
    """Carga un .env sencillo (raiz del repo o carpeta actual) sin pisar variables ya definidas."""
    import pathlib
    for p in (pathlib.Path(__file__).resolve().parents[1] / ".env", pathlib.Path.cwd() / ".env"):
        if p.exists():
            for linea in p.read_text(encoding="utf-8").splitlines():
                linea = linea.strip()
                if linea and not linea.startswith("#") and "=" in linea:
                    k, _, v = linea.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def principal(argv=None):
    from .config import cargar
    from .nucleo.alertas import Alertas
    _leer_env()
    ap = argparse.ArgumentParser(description="Servidor del robot para controlarlo desde otro computador")
    ap.add_argument("--robot", default="x2", choices=["x2", "d1", "falso", "sim"])
    ap.add_argument("--puerto", type=int)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--token", default=os.environ.get("ANDAMIO_TOKEN", ""))
    ap.add_argument("--config")
    ap.add_argument("--ojo", default="ninguno", choices=["ninguno", "x2", "camara", "simulado"],
                    help="camara del robot para los pasos buscar/acercarse desde el portatil")
    args = ap.parse_args(argv)
    cfg = cargar(args.config)
    alertas = Alertas(archivo=None)
    from .fabrica import crear_robot
    robot = crear_robot(args.robot, cfg, alertas)
    try:
        robot.conectar()
    except ErrorAndamio as e:
        alertas.critico(f"no se pudo conectar al robot: {e}", pista=e.pista)
        return 2
    ojo = None
    if args.ojo != "ninguno":
        from .vision import crear_ojo
        try:
            ojo = crear_ojo(args.ojo, robot, cfg, alertas)
            ojo.iniciar()
        except ErrorAndamio as e:
            alertas.error(f"no se pudo iniciar el ojo: {e}", pista=e.pista)
            ojo = None
    srv = ServidorRobot(robot, alertas, cfg, args.token, args.host, args.puerto or cfg["remoto"]["puerto"], ojo=ojo)
    try:
        srv.servir()
    except KeyboardInterrupt:
        pass
    finally:
        srv.parar_todo("servidor cerrado")
        srv.cerrar()
        if ojo is not None:
            ojo.cerrar()
        robot.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
