"""Teleoperacion: recibe las manos del visor (WebXR), las convierte en angulos de brazo con
IK y se las manda al robot, con limite de velocidad por articulacion y grabacion opcional.

Habla el mismo protocolo websocket que bridge/server.py, asi que el visor de web/ funciona
sin cambios:

    entra  {"type":"manos","left":{"p":[x,y,z],"pinza":1.0},"right":{...},"head":{...}}
    entra  {"type":"cmd","cmd":"calibrar"|"reset"|"grabar"|"parar","tarea":"..."}
    sale   {"type":"hola",...}  {"type":"estado","p":[...],"q":[...],...}  {"type":"aviso","texto":"..."}

La primera mano que llega fija un ancla: lo que se mueva la mano respecto a ese punto se
le suma a la posicion actual de la muneca del robot.
"""
import asyncio
import hmac
import json
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

import numpy as np

from .cinematica import Modelo
from .nucleo.errores import ErrorAndamio, ErrorSeguridad, NoSoportado

LADOS = {"left": "izquierda", "right": "derecha"}


class Teleop:
    def __init__(self, robot, seguridad, alertas, cfg, grabador=None, modelo=None, puerto=None, hz=50):
        self.robot = robot
        self.seguridad = seguridad
        self.alertas = alertas
        self.cfg = cfg["teleop"]
        self.grabador = grabador
        self.puerto = int(puerto or self.cfg["puerto"])
        self.host = str(self.cfg.get("host") or "0.0.0.0")
        # PIN que el visor debe mandar en la URL (ws://ip:puerto/?pin=XXXX). Sin PIN configurado
        # se genera uno nuevo en cada ejecucion: cualquiera en la red podria mover los brazos.
        self.pin = str(self.cfg.get("pin") or secrets.token_urlsafe(6))
        self.hz = hz
        self.modelo = modelo or getattr(robot, "modelo", None)
        if self.modelo is None or not hasattr(self.modelo, "ik"):
            raise NoSoportado("la teleoperacion necesita un modelo cinematico",
                              pista="usa --modelo ruta.xml o el robot sim")
        # modelo privado para no pisar la pose que muestra el simulador
        self.ik = Modelo(self.modelo.ruta, self.modelo.efectores)
        self._lock = threading.RLock()
        self.anclas = {}                    # lado -> (mano_ref, efector_ref)
        self.ultimas = {}                   # ultimo mensaje de manos
        self.objetivo_q = {l: self.ik.articulaciones(l).copy() for l in self.ik.cadenas}
        self.q_cmd = {l: v.copy() for l, v in self.objetivo_q.items()}
        self.pinza = {"izquierda": 1.0, "derecha": 1.0}
        self.pinza_enviada = {}
        self.t_ultimo_mensaje = None
        self.errores_ik = 0
        self.enviados = 0
        self._fin = threading.Event()
        self._hilo_ws = None
        self._loop = None
        self.clientes = set()

    def fijar_inicio(self, izq, der):
        """Arranca desde la pose real/ultima de los brazos (por ejemplo la que dejo una plantilla),
        no desde el reposo del modelo, para que el primer ciclo no de un tiron."""
        with self._lock:
            for lado, q in (("izquierda", izq), ("derecha", der)):
                if q is None or lado not in self.ik.cadenas:
                    continue
                q = np.asarray(q, float)
                if q.shape != (len(self.ik.cadenas[lado]),) or not np.all(np.isfinite(q)):
                    continue
                self.ik.fijar_articulaciones(lado, q)
                self.objetivo_q[lado] = self.ik.articulaciones(lado).copy()
                self.q_cmd[lado] = self.objetivo_q[lado].copy()
            self.anclas.clear()

    # ---------- protocolo ----------
    def hola(self):
        return {"type": "hola", "robot": self.robot.nombre, "glb": "", "bodies": self._nombres(),
                "efectores": {k: self.ik.efectores[v] for k, v in LADOS.items() if v in self.ik.efectores},
                "hz": self.hz}

    def _nombres(self):
        f = getattr(self.robot, "nombres_piezas", None)
        if f:
            return f()
        import mujoco
        return [mujoco.mj_id2name(self.ik.m, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(1, self.ik.m.nbody)]

    def recibir(self, msg):
        """Procesa un mensaje del visor. Devuelve una respuesta o None."""
        if not isinstance(msg, dict):
            return {"type": "error", "texto": "mensaje invalido"}
        t = msg.get("type")
        if t == "manos":
            self._manos(msg)
            return None
        if t == "cmd":
            return self._cmd(msg)
        return None

    def _manos(self, msg):
        with self._lock:
            self.t_ultimo_mensaje = time.monotonic()
            self.ultimas = msg
            for clave, lado in LADOS.items():
                m = msg.get(clave)
                if not m or lado not in self.ik.cadenas:
                    continue
                p = m.get("p")
                if not _vector3(p):
                    self.alertas.aviso(f"mano {clave}: posicion invalida, se ignora")
                    continue
                if "pinza" in m:
                    try:
                        self.pinza[lado] = float(min(1.0, max(0.0, float(m["pinza"]))))
                    except (TypeError, ValueError):
                        pass
                if lado not in self.anclas:
                    self.anclas[lado] = (np.asarray(p, float), self.ik.pos_efector(lado))
                mano_ref, ef_ref = self.anclas[lado]
                objetivo = ef_ref + (np.asarray(p, float) - mano_ref) * float(self.cfg["escala"])
                err, ok = self.ik.ik(lado, objetivo)
                if not ok:
                    self.errores_ik += 1
                    if self.errores_ik % 100 == 1:
                        self.alertas.aviso(f"{lado}: la mano esta fuera del alcance del robot (error {err * 100:.0f} cm)",
                                           pista="acerca la mano o recalibra con 'calibrar'")
                self.objetivo_q[lado] = self.ik.articulaciones(lado).copy()

    def _cmd(self, msg):
        c = msg.get("cmd")
        with self._lock:
            if c == "calibrar":
                self.anclas.clear()
                for clave, lado in LADOS.items():
                    m = self.ultimas.get(clave)
                    if m and _vector3(m.get("p")) and lado in self.ik.cadenas:
                        self.anclas[lado] = (np.asarray(m["p"], float), self.ik.pos_efector(lado))
                return {"type": "aviso", "texto": "calibrado"}
            if c == "reset":
                self.ik.reposo()
                self.anclas.clear()
                for l in self.ik.cadenas:
                    self.objetivo_q[l] = self.ik.articulaciones(l).copy()
                return {"type": "aviso", "texto": "brazos en reposo"}
        if c == "grabar":
            if self.grabador is None:
                return {"type": "error", "texto": "no hay grabador"}
            eid = self.grabador.iniciar(str(msg.get("tarea", "sin_nombre"))[:80], self.robot.nombre,
                                        str(msg.get("operador", ""))[:80])
            return {"type": "grabando", "episodio": eid}
        if c == "parar":
            meta = self.grabador.parar() if self.grabador else None
            return {"type": "grabado", "meta": meta}
        return {"type": "error", "texto": f"comando desconocido: {c}"}

    # ---------- ciclo de control ----------
    def paso(self, dt=None):
        """Un ciclo: suaviza hacia el objetivo y manda al robot. Devuelve False si no se pudo enviar."""
        dt = dt or 1.0 / self.hz
        vmax = float(self.cfg["vel_art_max"]) * dt
        alfa = float(self.cfg["suavizado"])
        with self._lock:
            for l in self.q_cmd:
                delta = (self.objetivo_q[l] - self.q_cmd[l]) * alfa
                self.q_cmd[l] = self.q_cmd[l] + np.clip(delta, -vmax, vmax)
            izq = self.q_cmd["izquierda"].tolist()
            der = self.q_cmd["derecha"].tolist()
            pinza = dict(self.pinza)
        if self.seguridad.parado:
            return False
        try:
            self.robot.brazos(izq, der)
            for lado, v in pinza.items():
                if abs(self.pinza_enviada.get(lado, -1) - v) > 0.02:
                    self.robot.mano(lado, v, "pinza")
                    self.pinza_enviada[lado] = v
            self.enviados += 1
        except NoSoportado:
            raise
        except ErrorAndamio as e:
            self.alertas.error(f"teleop: fallo enviando al robot: {e}", pista=e.pista)
            return False
        if self.grabador is not None and self.grabador.activo:
            self.grabador.trama({"qpos": izq + der},
                                {"izquierda": izq, "derecha": der, "pinza": pinza,
                                 "manos": {k: v for k, v in self.ultimas.items() if k in ("left", "right", "head")}})
        return True

    def trama(self):
        f = getattr(self.robot, "poses", None)
        if f:
            p, q = f()
        else:
            p, q = np.round(self.ik.d.xpos[1:], 4).tolist(), np.round(self.ik.d.xquat[1:], 4).tolist()
        return {"type": "estado", "t": round(time.time(), 4), "p": p, "q": q,
                "grabando": bool(self.grabador and self.grabador.activo),
                "n": self.grabador.n if self.grabador else 0}

    # ---------- servidor ----------
    def _pin_correcto(self, ws):
        try:
            req = getattr(ws, "request", None)
            ruta = req.path if req is not None else getattr(ws, "path", "")
            pin = (parse_qs(urlsplit(ruta).query).get("pin") or [""])[0]
        except Exception:
            return False
        return hmac.compare_digest(pin.encode(), self.pin.encode())

    async def _manejar(self, ws, *_):
        if not self._pin_correcto(ws):
            self.alertas.aviso("teleop: conexion rechazada (PIN incorrecto)",
                               pista="agrega ?pin=... a la URL del visor; el PIN sale al iniciar la teleoperacion")
            await ws.close(1008, "pin incorrecto")
            return
        if self.clientes:
            await ws.close(1013, "ya hay un visor conectado")
            return
        self.clientes.add(ws)
        try:
            await ws.send(json.dumps(self.hola()))
        except Exception:
            self.clientes.discard(ws)
            return

        async def enviar():
            while True:
                try:
                    await ws.send(json.dumps(self.trama()))
                except Exception:
                    return
                await asyncio.sleep(1.0 / self.hz)

        tarea = asyncio.create_task(enviar())
        try:
            async for crudo in ws:
                try:
                    r = self.recibir(json.loads(crudo))
                except Exception as e:
                    r = {"type": "error", "texto": str(e)[:200]}
                if r:
                    await ws.send(json.dumps(r))
        except Exception:
            pass
        finally:
            tarea.cancel()
            self.clientes.discard(ws)

    def _servir(self):
        import websockets

        async def principal():
            async with websockets.serve(self._manejar, self.host, self.puerto, max_size=2 ** 22, ping_interval=20):
                while not self._fin.is_set():
                    await asyncio.sleep(0.1)

        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(principal())
        except OSError as e:
            self.alertas.error(f"teleop: no se pudo abrir el puerto {self.puerto}: {e}",
                               pista="otro programa usa el puerto; cambia teleop.puerto")
            self._fin.set()

    def detener(self):
        self._fin.set()

    def correr(self, duracion=0.0):
        """Sirve el websocket y controla el robot hasta que pase `duracion` s (0 = hasta detener)."""
        self.seguridad.revisar_antes("brazos")
        self._hilo_ws = threading.Thread(target=self._servir, daemon=True, name="andamio-teleop-ws")
        self._hilo_ws.start()
        self.alertas.info(f"teleop listo: en el visor usa  ws://<IP de este equipo>:{self.puerto}/?pin={self.pin}  "
                          "y pulsa calibrar")
        t0 = time.monotonic()
        siguiente = t0
        ultimo_aviso = 0.0
        fallos = 0
        try:
            while not self._fin.is_set():
                if duracion and time.monotonic() - t0 >= duracion:
                    break
                if self.seguridad.parado:
                    raise ErrorSeguridad("parada de emergencia durante la teleoperacion")
                self.seguridad.comprobar_alto()
                ok = self.paso()
                fallos = 0 if ok else fallos + 1
                if fallos >= int(self.cfg.get("fallos_seguidos", 25)):
                    raise ErrorSeguridad("la teleoperacion no puede enviar al robot",
                                         pista="revisa la conexion con el robot")
                ahora = time.monotonic()
                if (self.t_ultimo_mensaje is None or ahora - self.t_ultimo_mensaje > 2.0) and ahora - ultimo_aviso > 10:
                    ultimo_aviso = ahora
                    self.alertas.aviso("el visor no envia manos; los brazos se quedan quietos",
                                       pista="revisa que las gafas esten conectadas al puerto del puente")
                siguiente += 1.0 / self.hz
                espera = siguiente - time.monotonic()
                if espera > 0:
                    time.sleep(espera)
                else:
                    siguiente = time.monotonic()
        finally:
            self._fin.set()
            if self._hilo_ws is not None:
                self._hilo_ws.join(timeout=2.0)


def _vector3(p):
    try:
        return len(p) == 3 and all(np.isfinite(float(v)) for v in p)
    except (TypeError, ValueError):
        return False
