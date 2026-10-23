"""Adaptador del AgiBot X2 (AimDK, ROS 2 Humble).

Se divide en dos capas:

  * TransporteROS: lo unico que toca rclpy y aimdk_msgs (servicios, topics, QoS).
  * RobotX2: la logica (modos, umbrales, tren superior a 50 Hz con limite de velocidad,
    manos, gestos) sobre cualquier transporte. Asi se prueba sin robot ni ROS.

Reglas del manual que respeta:
  * SDK y firmware deben coincidir; el codigo corre en la unidad de desarrollo (10.0.1.41) o
    en un contenedor sobre ella, nunca en PC1 (10.0.1.40, control de movimiento).
  * Velocidades: minimo 0.2 m/s adelante/lateral y 0.1 rad/s de giro; 0 se manda como 0.
  * La orden de velocidad se repite a 50 Hz (la seguridad la mantiene); el robot se frena solo
    si pasan 200 ms sin ordenes.
  * Una fuente de entrada registrada (ADD o, si ya existe, ENABLE) con prioridad y timeout.
  * Los servicios entre equipos fallan a veces: se reintentan hasta 8 veces con 0.25 s.
  * No lanzar muchos nodos seguidos con el robot de pie (congestiona DDS): un solo nodo.
"""
import threading
import time

from ..nucleo.errores import ErrorConexion, ErrorRobot, ErrorSeguridad, NoSoportado
from ..nucleo.robot import Robot
from ..nucleo.validacion import finito, lista_finita

MODOS_X2 = {
    "pasivo": "PASSIVE_DEFAULT",
    "amortiguado": "DAMPING_DEFAULT",
    "fijo": "JOINT_DEFAULT",
    "estable": "STAND_DEFAULT",
    "caminar": "LOCOMOTION_DEFAULT",
    "cabeza": "HEAD_ONLY",
    "tren_superior": "UPPERBODY_REMOTE_SPLIT",
}
DESDE_X2 = {v: k for k, v in MODOS_X2.items()}
GESTOS_X2 = {"levantar": 1001, "saludar": 1002, "apretar_mano": 1003, "beso": 1004}
AREA = {"izquierda": 1, "derecha": 2}
# Mitad de recorrido de cada articulacion de la mano dexterosa (ejemplo oficial); la derecha es el espejo.
MANO_MITAD = {
    "izquierda": [-0.6, 0.8, -0.4, 0.1, 0.7, 0.7, -0.1, 0.7, -0.1, 0.7],
    "derecha": [0.6, -0.8, 0.4, -0.1, 0.7, 0.7, 0.1, 0.7, 0.1, 0.7],
}
SUB_PINZA, SUB_ARTICULAR = 1, 2


class TransporteROS:
    """Capa fina sobre rclpy. Ver los ejemplos oficiales (py_examples) para cada llamada."""

    def __init__(self, cfg, alertas):
        self.cfg = cfg
        self.alertas = alertas
        self.node = None
        self._bateria = None
        self._t_bateria = 0.0
        self._hilo = None
        self._ejecutor = None
        self._seq = 0

    # ---------- arranque ----------
    def iniciar(self, espera_s=10.0):
        try:
            import rclpy
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from aimdk_msgs import msg as M
            from aimdk_msgs import srv as S
        except ImportError as e:
            raise ErrorConexion(f"falta {e.name}: no se puede hablar con el X2",
                                pista="source /opt/ros/humble/setup.bash y source ~/aimdk/install/local_setup.bash "
                                      "(el SDK debe estar compilado en esta maquina o contenedor)")
        self.rclpy, self.M, self.S = rclpy, M, S
        if not rclpy.ok():
            rclpy.init()
        self.node = rclpy.create_node("andamio")
        mejor_esfuerzo = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                                    durability=DurabilityPolicy.VOLATILE)
        local = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                           durability=DurabilityPolicy.TRANSIENT_LOCAL)
        n = self.node
        self.pub_vel = n.create_publisher(M.McLocomotionVelocity, "/aima/mc/locomotion/velocity", mejor_esfuerzo)
        self.pub_sup = n.create_publisher(M.UpperBodyCommandArray, "/mc/upper_body_command", mejor_esfuerzo)
        self.pub_mano = n.create_publisher(M.HandCommandArray, "/aima/hal/joint/hand/command", mejor_esfuerzo)
        tipo_pmu = _tipo_pmu()
        if tipo_pmu is not None:
            n.create_subscription(tipo_pmu, "/aima/hal/pmu/stat", self._al_pmu, local)
        else:
            self.alertas.aviso("no se encontro el mensaje PmuState: no se leera la bateria",
                               pista="revisa los paquetes de mensajes del SDK (hal/msg/PmuState)")
        base = "/aimdk_5Fmsgs/srv/"
        self.cl = {
            "get_accion": n.create_client(S.GetMcAction, base + "GetMcAction"),
            "set_accion": n.create_client(S.SetMcAction, base + "SetMcAction"),
            "fuente": n.create_client(S.SetMcInputSource, base + "SetMcInputSource"),
            "preset": n.create_client(S.SetMcPresetMotion, base + "SetMcPresetMotion"),
            "tts": n.create_client(S.PlayTts, base + "PlayTts"),
        }
        self._ejecutor = MultiThreadedExecutor(num_threads=2)
        self._ejecutor.add_node(n)
        self._hilo = threading.Thread(target=self._ejecutor.spin, daemon=True, name="andamio-ros")
        self._hilo.start()
        fin = time.monotonic() + espera_s
        for nombre in ("get_accion", "set_accion", "fuente"):
            while not self.cl[nombre].wait_for_service(timeout_sec=0.5):
                if time.monotonic() > fin:
                    raise ErrorConexion(f"el servicio {nombre} del robot no responde",
                                        pista="revisa el cable (10.0.1.2/24), ping 10.0.1.41, ROS_DOMAIN_ID y "
                                              "RMW_IMPLEMENTATION=rmw_fastrtps_cpp; el SDK debe ser de la misma "
                                              "version que el firmware")

    def suscribir_camara(self, topico_color, topico_prof, al_cuadro):
        """Camara RGB-D de la cabeza: color comprimido (JPEG) y, si se puede, profundidad cruda.
        El manual pide no suscribirse a imagenes crudas entre equipos (80 MB/s): la profundidad
        solo se usa si este proceso corre en la propia unidad de desarrollo / contenedor."""
        try:
            import cv2
            import numpy as np
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from sensor_msgs.msg import CompressedImage, Image
        except ImportError as e:
            raise ErrorConexion(f"falta {e.name} para la camara del X2",
                                pista="en el contenedor: pip install opencv-python-headless numpy "
                                      "(sensor_msgs viene con ROS 2)")
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
        estado = {"prof": None}

        def al_color(msg):
            try:
                bgr = cv2.imdecode(np.frombuffer(bytes(msg.data), np.uint8), cv2.IMREAD_COLOR)
                if bgr is not None:
                    al_cuadro(bgr, estado["prof"])
            except Exception:
                pass

        def al_prof(msg):
            try:
                tipo = {"16UC1": np.uint16, "mono16": np.uint16, "32FC1": np.float32}.get(msg.encoding)
                if tipo is None:
                    return
                img = np.frombuffer(bytes(msg.data), tipo).reshape(msg.height, msg.width)
                estado["prof"] = img.astype(np.float32) * (1000.0 if tipo is np.float32 else 1.0)
            except Exception:
                pass

        self.node.create_subscription(CompressedImage, topico_color, al_color, qos)
        if topico_prof:
            self.node.create_subscription(Image, topico_prof, al_prof, qos)

    def _al_pmu(self, msg):
        try:
            self._bateria = float(msg.battery_remaining_capacity_percentage)
            self._t_bateria = time.monotonic()
        except Exception:
            pass

    def cerrar(self):
        try:
            if self._ejecutor:
                self._ejecutor.shutdown(timeout_sec=1.0)
            if self.node:
                self.node.destroy_node()
            if self.rclpy.ok():
                self.rclpy.shutdown()
        except Exception:
            pass

    # ---------- servicios con reintento ----------
    def _llamar(self, cliente, req, poner_hora, intentos=8, espera=0.25):
        for _ in range(intentos):
            poner_hora(req, self.node.get_clock().now().to_msg())
            listo = threading.Event()
            fut = cliente.call_async(req)
            fut.add_done_callback(lambda f: listo.set())
            if listo.wait(espera):
                try:
                    return fut.result()
                except Exception as e:
                    raise ErrorConexion(f"la llamada al servicio fallo: {e}")
            fut.cancel()
        raise ErrorConexion("el servicio no respondio tras 8 intentos",
                            pista="posible perdida de red o robot ocupado; revisa el cable y prueba de nuevo")

    def accion_actual(self):
        req = self.S.GetMcAction.Request()
        req.request = self.M.CommonRequest()
        r = self._llamar(self.cl["get_accion"], req, lambda q, t: setattr(q.request.header, "stamp", t))
        return r.info.action_desc

    def fijar_accion(self, nombre):
        req = self.S.SetMcAction.Request()
        req.header = self.M.RequestHeader()
        req.source = self.cfg["fuente"]
        cmd = self.M.McActionCommand()
        cmd.action_desc = nombre
        req.command = cmd
        r = self._llamar(self.cl["set_accion"], req, lambda q, t: setattr(q.header, "stamp", t))
        ok = r.response.status.value == self.M.CommonState.SUCCESS
        return ok, getattr(r.response, "message", "")

    def registrar_fuente(self, nombre, prioridad, timeout_ms):
        acciones = (self.M.McInputAction.INPUTACTION_ADD, self.M.McInputAction.INPUTACTION_ENABLE)
        for accion in acciones:                   # ADD; si ya existe, ENABLE
            req = self.S.SetMcInputSource.Request()
            req.action.value = accion
            req.input_source.name = nombre
            req.input_source.priority = int(prioridad)
            req.input_source.timeout = int(timeout_ms)
            try:
                r = self._llamar(self.cl["fuente"], req, lambda q, t: setattr(q.request.header, "stamp", t))
            except ErrorConexion:
                continue
            if r.response.header.code == 0:
                return True
        return False

    # ---------- topics ----------
    def _cabecera(self, nombre="andamio"):
        h = self.M.MessageHeader()
        now = self.node.get_clock().now().nanoseconds
        h.stamp.sec, h.stamp.nanosec = now // 1_000_000_000, now % 1_000_000_000
        h.frame_id = nombre
        h.sequence = self._seq
        self._seq += 1
        return h

    def publicar_velocidad(self, vx, vy, wz):
        m = self.M.McLocomotionVelocity()
        m.header = self._cabecera("mc_locomotion")
        m.source = self.cfg["fuente"]
        m.forward_velocity, m.lateral_velocity, m.angular_velocity = float(vx), float(vy), float(wz)
        self.pub_vel.publish(m)

    def publicar_tren_superior(self, sub_modo, cabeza, brazos, manos):
        m = self.M.UpperBodyCommandArray()
        m.header = self._cabecera("mc_upper_body")
        m.source = self.cfg["fuente"]
        m.hand_sub_mode = int(sub_modo)
        m.head_pos = [float(v) for v in cabeza]
        m.arm_pos = [float(v) for v in brazos]
        m.hand_pos = [float(v) for v in manos]
        self.pub_sup.publish(m)

    def publicar_pinza_hal(self, izq, der):
        m = self.M.HandCommandArray()
        m.header = self.M.MessageHeader()
        manos = []
        for nombre, v in (("left_hand", izq), ("right_hand", der)):
            h = self.M.HandCommand()
            h.name, h.position = nombre, float(v)
            h.velocity = h.acceleration = h.deceleration = h.effort = 1.0
            manos.append(h)
        m.left_hand_type = self.M.HandType(value=self.M.HandType.CLAW)
        m.right_hand_type = self.M.HandType(value=self.M.HandType.CLAW)
        m.left_hands, m.right_hands = [manos[0]], [manos[1]]
        self.pub_mano.publish(m)

    def movimiento(self, area, motion_id):
        req = self.S.SetMcPresetMotion.Request()
        req.header = self.M.RequestHeader()
        req.input_source.name = self.cfg["fuente"]
        req.input_source.priority = int(self.cfg["prioridad"])
        req.input_source.timeout = int(self.cfg["timeout_ms"])
        mo, ar = self.M.McPresetMotion(), self.M.McControlArea()
        mo.value, ar.value = int(motion_id), int(area)
        req.motion, req.area, req.interrupt = mo, ar, False
        r = self._llamar(self.cl["preset"], req, lambda q, t: setattr(q.header, "stamp", t))
        return r.response.header.code == 0 or r.response.state.value == self.M.CommonState.RUNNING

    def hablar(self, texto):
        req = self.S.PlayTts.Request()
        req.tts_req.text = texto
        req.tts_req.domain = "andamio"
        req.tts_req.trace_id = "andamio"
        req.tts_req.is_interrupted = True
        req.tts_req.priority_weight = 0
        req.tts_req.priority_level.value = self.M.TtsPriorityLevel.INTERACTION_L6
        r = self._llamar(self.cl["tts"], req, lambda q, t: setattr(q.header.header, "stamp", t))
        return bool(r.tts_resp.is_success)

    # ---------- medios (servicios del computador de interaccion, PC3) ----------
    def _cliente(self, nombre, tipo, srv):
        if nombre not in self.cl:
            self.cl[nombre] = self.node.create_client(tipo, "/aimdk_5Fmsgs/srv/" + srv)
        return self.cl[nombre]

    def reproducir_video(self, ruta, modo, prioridad=5):
        req = self.S.PlayVideo.Request()
        req.video_path, req.mode, req.priority = str(ruta), int(modo), int(prioridad)
        r = self._llamar(self._cliente("video", self.S.PlayVideo, "PlayVideo"), req,
                         lambda q, t: setattr(q.header.header, "stamp", t))
        return bool(r.success), str(getattr(r, "message", ""))

    def reproducir_audio(self, ruta, prioridad=8):
        import os
        req = self.S.PlayAudioFile.Request()
        req.file.pkg_name = "andamio"
        req.file.file_name = os.path.basename(ruta)
        req.file.file_path = os.path.dirname(ruta) + "/"
        req.file.priority = int(prioridad)
        req.file.priority_weight = 0
        r = self._llamar(self._cliente("audio", self.S.PlayAudioFile, "PlayAudioFile"), req,
                         lambda q, t: setattr(q.request.header, "stamp", t), intentos=5, espera=1.0)
        exito = getattr(self.M, "CommonState", None)
        valor = r.reponse.status.value            # (sic) asi se llama el campo en el SDK
        return (valor == exito.SUCCESS) if exito is not None else valor == 1, str(r.reponse.message)

    def expresion(self, emocion_id, modo, prioridad=10):
        req = self.S.PlayEmoji.Request()
        req.emotion_id, req.mode, req.priority = int(emocion_id), int(modo), int(prioridad)
        r = self._llamar(self._cliente("emoji", self.S.PlayEmoji, "PlayEmoji"), req,
                         lambda q, t: setattr(q.header.header, "stamp", t))
        return bool(r.success), str(getattr(r, "message", ""))

    def luces(self, modo, r_, g, b, prioridad=6):
        req = self.S.SetPmuLed.Request()
        req.led_strip_mode, req.r, req.g, req.b = int(modo), int(r_), int(g), int(b)
        req.priority, req.reset_priority, req.trace_id = int(prioridad), False, "andamio"
        r = self._llamar(self._cliente("led", self.S.SetPmuLed, "SetPmuLed"), req,
                         lambda q, t: setattr(q.request.header, "stamp", t))
        return r.status_code == 0, f"0x{r.status_code:X}"

    def bateria(self):
        if self._bateria is None or time.monotonic() - self._t_bateria > 15:
            return None
        return self._bateria


def _tipo_pmu():
    try:
        from aimdk_msgs.msg import PmuState
        return PmuState
    except ImportError:
        pass
    try:
        from hal.msg import PmuState
        return PmuState
    except ImportError:
        return None


class _TrenSuperior(threading.Thread):
    """Publica el comando del tren superior a 50 Hz, acercandose al objetivo con limite de velocidad."""

    def __init__(self, transporte, alertas, vel_brazo, vel_cabeza, hz=50):
        super().__init__(daemon=True, name="andamio-tren-superior")
        self.t, self.alertas = transporte, alertas
        self.dt = 1.0 / hz
        self.vel_brazo, self.vel_cabeza = vel_brazo, vel_cabeza
        self._lock = threading.Lock()
        self.brazos_obj = [0.0] * 14
        self.brazos = [0.0] * 14
        self.cabeza_obj = [0.0, 0.0]
        self.cabeza = [0.0, 0.0]
        self.sub_modo = SUB_PINZA
        self.manos = [1.0, 1.0]
        self.limites = None            # lista de 14 (min, max) si se conocen
        self.limites_cabeza = [(-1.0, 1.0), (-0.5, 0.5)]
        self._fin = threading.Event()
        self._fallos = 0
        self.publicados = 0
        self.al_fallar = None

    def fijar(self, brazos=None, cabeza=None, sub_modo=None, manos=None):
        # todo numero se valida ANTES de tocar el estado: un NaN haria correr el brazo a velocidad maxima
        try:
            if brazos is not None:
                brazos = lista_finita(brazos, 14, "brazos")
            if cabeza is not None:
                cabeza = lista_finita(cabeza, 2, "cabeza")
            if manos is not None:
                manos = lista_finita(manos, len(manos), "manos")
        except ErrorSeguridad as e:
            raise ErrorRobot(str(e), pista="el comando tiene valores invalidos; no se envio nada")
        with self._lock:
            if brazos is not None:
                self.brazos_obj = [self._recortar(i, v) for i, v in enumerate(brazos)]
            if cabeza is not None:
                self.cabeza_obj = [min(max(v, lo), hi) for v, (lo, hi) in zip(cabeza, self.limites_cabeza)]
            if sub_modo is not None:
                self.sub_modo = sub_modo
            if manos is not None:
                self.manos = list(manos)

    def _recortar(self, i, v):
        if self.limites:
            lo, hi = self.limites[i]
            return min(max(float(v), lo), hi)
        return float(v)

    def terminar(self):
        self._fin.set()

    def congelar(self):
        """Deja los objetivos donde estan los brazos ahora (para la parada de emergencia)."""
        with self._lock:
            self.brazos_obj = list(self.brazos)
            self.cabeza_obj = list(self.cabeza)

    def run(self):
        siguiente = time.monotonic()
        while not self._fin.is_set():
            with self._lock:
                paso = self.vel_brazo * self.dt
                self.brazos = [a + max(-paso, min(paso, b - a)) for a, b in zip(self.brazos, self.brazos_obj)]
                pc = self.vel_cabeza * self.dt
                self.cabeza = [a + max(-pc, min(pc, b - a)) for a, b in zip(self.cabeza, self.cabeza_obj)]
                datos = (self.sub_modo, list(self.cabeza), list(self.brazos), list(self.manos))
            try:
                self.t.publicar_tren_superior(*datos)
                self.publicados += 1
                self._fallos = 0
            except Exception as e:
                self._fallos += 1
                self.alertas.error(f"fallo publicando el tren superior ({self._fallos}/3): {e}")
                if self._fallos >= 3 and self.al_fallar:
                    self.al_fallar()
                    self._fallos = 0
            siguiente += self.dt
            espera = siguiente - time.monotonic()
            if espera > 0:
                self._fin.wait(espera)
            else:
                siguiente = time.monotonic()


class RobotX2(Robot):
    nombre = "x2"
    capacidades = frozenset({"caminar", "brazos", "cabeza", "manos", "hablar", "gestos", "medios"})
    vel_min = (0.2, 0.2, 0.1)
    vel_max = (1.0, 1.0, 1.0)

    def __init__(self, config=None, alertas=None, transporte=None):
        super().__init__(config, alertas)
        cfg = (config or {}).get("x2", {})
        from ..config import DEFECTO
        self.cfg = {**DEFECTO["x2"], **cfg}
        self.t = transporte or TransporteROS(self.cfg, alertas)
        self.cfg_vision = {**DEFECTO["vision"], **(config or {}).get("vision", {})}
        self._modo = None
        self._modo_raw = None
        self._bateria = None
        self._t_estado = 0.0
        self._fallos_poll = 0
        self._fin = threading.Event()
        self._hilo = None
        self._sup = None
        self._lock = threading.RLock()
        self._ult_vel = (0.0, 0.0, 0.0)
        self.limites_brazo = None
        self._tipo_mano = None            # "pinza" | "mano"
        self._apertura = {"izquierda": 1.0, "derecha": 1.0}

    # ---------- ciclo de vida ----------
    def conectar(self):
        self.t.iniciar()
        if not self.t.registrar_fuente(self.cfg["fuente"], self.cfg["prioridad"], self.cfg["timeout_ms"]):
            self.alertas.aviso("no se pudo registrar la fuente de entrada; el robot puede ignorar las ordenes",
                               pista="el servicio SetMcInputSource rechazo ADD y ENABLE; revisa version del SDK")
        self._leer_modo(fatal=True)
        self._hilo = threading.Thread(target=self._sondear, daemon=True, name="andamio-x2-estado")
        self._hilo.start()
        self._cargar_limites()
        self.alertas.info(f"X2 conectado, modo: {self._modo_raw}")

    def suscribir_camara(self, al_cuadro):
        """Usado por vision.OjoX2. Profundidad en milimetros (32FC1 en metros se pasa a mm)."""
        if not hasattr(self.t, "suscribir_camara"):
            raise NoSoportado("este transporte no tiene camara")
        self.t.suscribir_camara(self.cfg_vision["topico_color"], self.cfg_vision["topico_profundidad"], al_cuadro)

    def _cargar_limites(self):
        try:
            from ..cinematica import Modelo
            from .sim_mujoco import buscar_modelo
            m = Modelo(buscar_modelo(self.cfg.get("modelo_xml", "")))
            self.limites_brazo = m.limites("izquierda") + m.limites("derecha")
            if len(self.limites_brazo) != 14:
                self.limites_brazo = None
        except Exception:
            self.limites_brazo = None
        if self.limites_brazo is None:
            self.alertas.aviso("sin limites articulares del modelo; solo se limita la velocidad de los brazos",
                               pista="copia el MJCF del X2 en robots/ para recortar a los limites")

    def cerrar(self):
        self._fin.set()
        if self._sup:
            self._sup.terminar()
        try:
            self.detener()
        except Exception:
            pass
        self.t.cerrar()

    # ---------- estado ----------
    def _leer_modo(self, fatal=False):
        try:
            raw = self.t.accion_actual()
        except ErrorConexion:
            self._fallos_poll += 1
            if fatal:
                raise
            return
        self._fallos_poll = 0
        with self._lock:
            self._modo_raw = raw
            self._modo = DESDE_X2.get(raw)
            self._t_estado = time.monotonic()

    def _sondear(self):
        while not self._fin.wait(1.0):
            self._leer_modo()

    def estado(self):
        with self._lock:
            edad = time.monotonic() - self._t_estado
            return {"conectado": edad < 4.0 and self._fallos_poll < 3, "modo": self._modo,
                    "modo_x2": self._modo_raw, "bateria": self.t.bateria(), "edad_s": round(edad, 1)}

    # ---------- modos ----------
    def cambiar_modo(self, modo):
        if modo not in MODOS_X2:
            raise ErrorRobot(f"modo desconocido: {modo}")
        self._leer_modo(fatal=True)
        actual = self._modo
        if actual == modo or (actual in ("estable", "caminar") and modo in ("estable", "caminar")):
            return                                     # el manual: estable y caminar se alternan solos
        ok, msg = self.t.fijar_accion(MODOS_X2[modo])
        if not ok:
            raise ErrorRobot(f"el robot rechazo el cambio a {MODOS_X2[modo]}: {msg}",
                             pista="los cambios de modo siguen un diagrama; usa 'preparar' para pasar por los intermedios")
        fin = time.monotonic() + float(self.cfg["espera_modo_s"])
        while time.monotonic() < fin:
            self._leer_modo()
            if self._modo == modo or (self._modo in ("estable", "caminar") and modo in ("estable", "caminar")):
                return
            time.sleep(0.3)
        raise ErrorRobot(f"el robot no llego a {MODOS_X2[modo]} en {self.cfg['espera_modo_s']} s (esta en {self._modo_raw})",
                         pista="revisa que este de pie con los pies en el suelo y que no haya alarmas en el robot")

    def preparar(self, modo):
        from ..nucleo.modos import ruta
        self._leer_modo(fatal=True)
        for m in ruta(self._modo, modo, self.grafo):
            self.cambiar_modo(m)

    # ---------- locomocion ----------
    def enviar_velocidad(self, vx, vy, wz):
        for v, minimo, n in zip((vx, vy, wz), self.vel_min, ("vx", "vy", "wz")):
            if v != 0.0 and not (minimo <= abs(v) <= 1.0):
                raise ErrorRobot(f"{n}={v} fuera de rango (el robot acepta {minimo} a 1.0 o 0)",
                                 pista="usa Seguridad.limitar_velocidad antes de enviar")
        self.t.publicar_velocidad(vx, vy, wz)
        self._ult_vel = (vx, vy, wz)

    def emergencia(self, nivel="detener"):
        if self._sup is not None:
            self._sup.congelar()                       # los brazos se quedan donde estan
        for _ in range(5):
            try:
                self.t.publicar_velocidad(0.0, 0.0, 0.0)
            except Exception:
                break
            time.sleep(0.01)
        if nivel == "amortiguar":
            if self._sup:
                self._sup.terminar()
                self._sup = None
            try:
                self.t.fijar_accion(MODOS_X2["amortiguado"])
            except Exception as e:
                if self.alertas:
                    self.alertas.error(f"no se pudo pasar a amortiguado: {e}")

    # ---------- tren superior ----------
    def _tren(self):
        if self._sup is None or not self._sup.is_alive():
            self._sup = _TrenSuperior(self.t, self.alertas, vel_brazo=float(self.cfg.get("vel_brazo", 0.8)),
                                      vel_cabeza=float(self.cfg.get("vel_cabeza", 1.0)))
            self._sup.limites = self.limites_brazo
            self._sup.limites_cabeza = [(-float(self.cfg["cabeza_yaw_max"]), float(self.cfg["cabeza_yaw_max"])),
                                        (-float(self.cfg["cabeza_pitch_max"]), float(self.cfg["cabeza_pitch_max"]))]
            self._sup.al_fallar = lambda: self.alertas.critico(
                "no se puede publicar al tren superior", pista="revisa la conexion")
            self._sup.start()
            self.alertas.aviso("tren superior: los brazos parten de la pose cero del modelo y se mueven con limite de velocidad",
                               pista="mantén libre el espacio alrededor de los brazos")
        return self._sup

    def brazos(self, izq, der):
        if len(izq) != 7 or len(der) != 7:
            raise ErrorRobot("cada brazo necesita 7 valores")
        try:
            valores = lista_finita(list(izq) + list(der), 14, "brazos")
        except ErrorSeguridad as e:
            raise ErrorRobot(str(e), pista="el comando tiene valores invalidos; no se envio nada")
        self._tren().fijar(brazos=valores)

    def cabeza(self, yaw, pitch):
        try:
            yaw, pitch = finito(yaw, "yaw"), finito(pitch, "pitch")
        except ErrorSeguridad as e:
            raise ErrorRobot(str(e), pista="el comando tiene valores invalidos; no se envio nada")
        self._tren().fijar(cabeza=[yaw, pitch])

    def mano(self, lado, valor, tipo="pinza"):
        if lado not in AREA:
            raise ErrorRobot(f"lado invalido: {lado}")
        try:
            valor = min(1.0, max(0.0, finito(valor, "valor")))
        except ErrorSeguridad as e:
            raise ErrorRobot(str(e), pista="el comando tiene valores invalidos; no se envio nada")
        if tipo not in ("pinza", "mano"):
            raise ErrorRobot(f"tipo de mano desconocido: {tipo}", pista="usa 'pinza' o 'mano'")
        if self._tipo_mano not in (None, tipo):
            raise ErrorRobot("no se pueden mezclar pinza y mano dexterosa en la misma ejecucion",
                             pista="usa un solo tipo de mano por plantilla")
        self._tipo_mano = tipo
        self._apertura[lado] = valor
        if self.cfg["manos_via"] == "hal":
            if tipo != "pinza":
                raise NoSoportado("la ruta HAL solo se implemento para pinza")
            self.t.publicar_pinza_hal(self._apertura["izquierda"], self._apertura["derecha"])
            return
        if tipo == "pinza":
            self._tren().fijar(sub_modo=SUB_PINZA, manos=[self._apertura["izquierda"], self._apertura["derecha"]])
        else:
            factor = float(self.cfg.get("mano_cierre_factor", 0.8))
            q = []
            for l in ("izquierda", "derecha"):
                esc = (1.0 - self._apertura[l]) * 2.0 * factor
                q += [round(v * esc, 4) for v in MANO_MITAD[l]]
            self._tren().fijar(sub_modo=SUB_ARTICULAR, manos=q)

    # ---------- gestos y voz ----------
    def gestos(self):
        return list(GESTOS_X2)

    def gesto(self, nombre, lado="derecha"):
        if nombre not in GESTOS_X2:
            raise ErrorRobot(f"gesto desconocido: {nombre}", pista=f"gestos: {sorted(GESTOS_X2)}")
        if not self.t.movimiento(AREA[lado], GESTOS_X2[nombre]):
            raise ErrorRobot(f"el robot rechazo el gesto '{nombre}'",
                             pista="debe estar en modo estable y el brazo libre")

    def hablar(self, texto):
        if not self.t.hablar(texto):
            raise ErrorRobot("el robot no pudo reproducir el texto")

    # ---------- medios: los archivos deben estar en el computador de interaccion (PC3, 10.0.1.42) ----------
    def _medio(self, ok_msg, que, pista):
        ok, msg = ok_msg
        if not ok:
            raise ErrorRobot(f"el robot no pudo {que}: {msg}", pista=pista)

    def video(self, ruta, repetir=False):
        self._medio(self.t.reproducir_video(ruta, 2 if repetir else 1), f"reproducir el video {ruta}",
                    "el archivo debe estar en el PC3 (10.0.1.42), legible por todos (sube con "
                    "andamio/instalar/subir_medios.sh); si la pantalla no cambia, los organizadores deben "
                    "detener task_manager")

    def audio(self, ruta):
        if not str(ruta).lower().endswith((".wav", ".pcm")):
            raise ErrorRobot("el robot solo reproduce WAV (PCM) o PCM crudo", pista="convierte el mp3 a wav")
        self._medio(self.t.reproducir_audio(ruta), f"reproducir el audio {ruta}",
                    "el archivo debe estar en el PC3 (10.0.1.42) y legible por todos; sube con subir_medios.sh")

    def expresion(self, emocion, repetir=False):
        self._medio(self.t.expresion(emocion, 2 if repetir else 1), f"mostrar la expresion {emocion}",
                    "ids del manual: 1 parpadear, 60 aburrido, 70 anormal, 80 dormido, 90 feliz, 190 muy enojado, 200 adorar")

    def luces(self, modo, color):
        r_, g, b = color
        self._medio(self.t.luces(modo, r_, g, b), "cambiar las luces",
                    "0x1024 = prioridad insuficiente: task_manager esta usando las luces")


class RobotX2Sim(RobotX2):
    """El X2 del simulador oficial de AgiBot (sim_mujoco + mc en un PC x86 con Ubuntu 22.04 / WSL2).

    Habla exactamente el mismo ROS 2 que el robot real (mismo control de movimiento 'mc'), asi que
    la marcha, el equilibrio y los cambios de modo son los de verdad. Lo que el simulador no trae
    (bateria, computador de interaccion con voz/pantalla/luces) se reemplaza por avisos.
    """
    nombre = "x2sim"

    def estado(self):
        est = super().estado()
        if est.get("bateria") is None:
            est["bateria"] = 100.0           # el simulador no publica la bateria
        return est

    def _anunciar(self, texto):
        if self.alertas:
            self.alertas.info(f"[x2sim] {texto}")

    def hablar(self, texto):
        cli = self.t.cl.get("tts") if hasattr(self.t, "cl") else None
        if cli is not None and cli.service_is_ready():
            return super().hablar(texto)
        self._anunciar(f"diria: {texto}")

    def video(self, ruta, repetir=False):
        self._anunciar(f"pantalla: video {ruta}" + (" (en bucle)" if repetir else ""))

    def audio(self, ruta):
        self._anunciar(f"parlante: audio {ruta}")

    def expresion(self, emocion, repetir=False):
        self._anunciar(f"cara: expresion {emocion}")

    def luces(self, modo, color):
        self._anunciar(f"luces: modo {modo} color {tuple(color)}")
