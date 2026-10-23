import sys
import time
import types

import pytest

from andamio.nucleo.errores import ErrorConexion, ErrorRobot
from andamio.robots import x2_ros2
from andamio.robots.x2_ros2 import DESDE_X2, MODOS_X2, RobotX2


class TransporteFalso:
    def __init__(self):
        self.accion = "PASSIVE_DEFAULT"
        self.vel, self.superior, self.llamadas = [], [], []
        self.acepta = True
        self.cae = False
        self.bat = 80.0
        self.tts_ok = True

    def iniciar(self): self.llamadas.append("iniciar")
    def cerrar(self): self.llamadas.append("cerrar")

    def registrar_fuente(self, *a):
        self.llamadas.append(("fuente", a))
        return True

    def accion_actual(self):
        if self.cae:
            raise ErrorConexion("sin red")
        return self.accion

    def fijar_accion(self, nombre):
        self.llamadas.append(("accion", nombre))
        if self.acepta:
            self.accion = nombre
        return self.acepta, "" if self.acepta else "transicion invalida"

    def publicar_velocidad(self, *v): self.vel.append(v)
    def publicar_tren_superior(self, *a): self.superior.append(a)
    def publicar_pinza_hal(self, *a): self.llamadas.append(("hal", a))
    def movimiento(self, area, mid):
        self.llamadas.append(("mov", area, mid))
        return True
    def hablar(self, t):
        self.llamadas.append(("tts", t))
        return self.tts_ok
    def bateria(self): return self.bat


@pytest.fixture
def x2(cfg, alertas):
    cfg["x2"]["espera_modo_s"] = 1.0
    t = TransporteFalso()
    r = RobotX2(cfg, alertas, transporte=t)
    r.conectar()
    yield r, t
    r.cerrar()


def test_los_siete_modos_estan_mapeados():
    assert set(MODOS_X2) == {"pasivo", "amortiguado", "fijo", "estable", "caminar", "cabeza", "tren_superior"}
    assert MODOS_X2["tren_superior"] == "UPPERBODY_REMOTE_SPLIT" and MODOS_X2["fijo"] == "JOINT_DEFAULT"
    assert DESDE_X2["STAND_DEFAULT"] == "estable"


def test_conectar_registra_la_fuente_y_lee_el_modo(x2):
    r, t = x2
    assert ("fuente", ("node.andamio", 40, 1000)) in t.llamadas
    est = r.estado()
    assert est["conectado"] and est["modo"] == "pasivo" and est["bateria"] == 80.0


def test_cambio_de_modo_espera_confirmacion(x2):
    r, t = x2
    r.cambiar_modo("fijo")
    assert t.accion == "JOINT_DEFAULT" and r.estado()["modo"] == "fijo"


def test_estable_y_caminar_se_alternan_solos(x2):
    r, t = x2
    t.accion = "STAND_DEFAULT"
    r.cambiar_modo("caminar")
    assert not [l for l in t.llamadas if isinstance(l, tuple) and l[0] == "accion"]


def test_rechazo_del_robot_da_error_con_pista(x2):
    r, t = x2
    t.acepta = False
    with pytest.raises(ErrorRobot) as e:
        r.cambiar_modo("caminar")
    assert "transicion invalida" in str(e.value) and e.value.pista


def test_el_robot_no_llega_al_modo(x2):
    r, t = x2
    t.fijar_accion = lambda n: (True, "")        # acepta pero no cambia
    with pytest.raises(ErrorRobot) as e:
        r.cambiar_modo("fijo")
    assert "no llego" in str(e.value)


def test_preparar_recorre_la_ruta(x2):
    r, t = x2
    r.preparar("estable")
    acciones = [l[1] for l in t.llamadas if isinstance(l, tuple) and l[0] == "accion"]
    assert acciones == ["JOINT_DEFAULT", "STAND_DEFAULT"]


def test_umbrales_de_velocidad_del_manual(x2):
    r, t = x2
    r.enviar_velocidad(0.2, 0.0, 0.0)
    r.enviar_velocidad(0.0, 0.0, 0.0)
    for malo in [(0.1, 0, 0), (0, 0.15, 0), (0, 0, 0.05), (1.5, 0, 0)]:
        with pytest.raises(ErrorRobot):
            r.enviar_velocidad(*malo)
    assert t.vel == [(0.2, 0.0, 0.0), (0.0, 0.0, 0.0)]


def test_emergencia_manda_ceros_y_amortiguar_cambia_modo(x2):
    r, t = x2
    r.emergencia("detener")
    assert t.vel[-5:] == [(0.0, 0.0, 0.0)] * 5
    r.emergencia("amortiguar")
    assert t.accion == "DAMPING_DEFAULT"


def test_tren_superior_limita_la_velocidad_de_los_brazos(x2):
    r, t = x2
    r.cfg["vel_brazo"] = 0.8
    r.brazos([1.0] * 7, [-1.0] * 7)
    time.sleep(0.5)
    ult = r._sup.brazos
    assert 0.2 < ult[0] < 0.6                         # 0.8 rad/s * 0.5 s ~ 0.4
    pasos = [abs(b[2][0] - a[2][0]) for a, b in zip(t.superior, t.superior[1:])]
    assert max(pasos) <= 0.8 / 50 + 1e-9
    assert all(len(a[2]) == 14 for a in t.superior)


def test_el_tren_superior_se_publica_continuo_a_50hz(x2):
    r, t = x2
    r.brazos([0.0] * 7, [0.0] * 7)
    time.sleep(0.5)
    assert 18 <= len(t.superior) <= 32


def test_brazos_exige_siete_valores(x2):
    r, _ = x2
    with pytest.raises(ErrorRobot):
        r.brazos([0] * 6, [0] * 7)


def test_limites_articulares_recortan(x2):
    r, t = x2
    r.limites_brazo = [(-0.5, 0.5)] * 14
    r.brazos([3.0] * 7, [0.0] * 7)
    assert r._sup.brazos_obj[0] == 0.5 and r._sup.brazos_obj[7] == 0.0


def test_pinza_sub_modo_1_y_apertura(x2):
    r, t = x2
    r.mano("izquierda", 0.25, "pinza")
    time.sleep(0.1)
    sub, cab, brazos, manos = t.superior[-1]
    assert sub == 1 and manos == [0.25, 1.0]


def test_mano_dexterosa_manda_20_articulaciones(x2):
    r, t = x2
    r.mano("izquierda", 1.0, "mano")
    r.mano("derecha", 0.0, "mano")
    time.sleep(0.1)
    sub, _, _, manos = t.superior[-1]
    assert sub == 2 and len(manos) == 20
    assert all(v == 0 for v in manos[:10])           # izquierda abierta = ceros
    assert manos[10] == pytest.approx(0.6 * 2 * 0.8, abs=1e-3)    # derecha cerrada, espejo, factor 0.8


def test_manos_por_hal(x2):
    r, t = x2
    r.cfg["manos_via"] = "hal"
    r.mano("derecha", 0.5, "pinza")
    assert ("hal", (1.0, 0.5)) in t.llamadas
    with pytest.raises(Exception):
        r.mano("derecha", 0.5, "mano")


def test_no_se_mezclan_tipos_de_mano(x2):
    r, _ = x2
    r.mano("izquierda", 1.0, "pinza")
    with pytest.raises(ErrorRobot):
        r.mano("derecha", 1.0, "mano")


def test_gestos_usan_los_ids_del_manual(x2):
    r, t = x2
    r.gesto("saludar", "derecha")
    r.gesto("apretar_mano", "izquierda")
    assert ("mov", 2, 1002) in t.llamadas and ("mov", 1, 1003) in t.llamadas
    with pytest.raises(ErrorRobot):
        r.gesto("bailar")


def test_hablar_error(x2):
    r, t = x2
    t.tts_ok = False
    with pytest.raises(ErrorRobot):
        r.hablar("hola")


def test_perder_el_robot_marca_desconectado(x2):
    r, t = x2
    t.cae = True
    for _ in range(3):
        r._leer_modo()
    assert not r.estado()["conectado"]


def test_conectar_sin_red_falla_con_pista(cfg, alertas):
    t = TransporteFalso()
    t.cae = True
    r = RobotX2(cfg, alertas, transporte=t)
    with pytest.raises(ErrorConexion):
        r.conectar()


# ---------------------------------------------------------------- capa ROS con rclpy simulado
class Msg:
    """Mensaje generico: acepta cualquier atributo y lo anida."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        v = Msg()
        self.__dict__[n] = v
        return v


def instalar_ros_falso(monkeypatch):
    publicados, servicios = [], {}

    class Futuro:
        def __init__(self, r): self._r = r
        def add_done_callback(self, f): f(self)
        def result(self): return self._r
        def cancel(self): pass

    class Cliente:
        def __init__(self, nombre): self.nombre = nombre
        def wait_for_service(self, timeout_sec=0): return True
        def call_async(self, req):
            servicios.setdefault(self.nombre, []).append(req)
            r = Msg()
            r.response.header.code = 0
            r.response.status.value = 1
            r.response.state.value = 400
            r.info.action_desc = "STAND_DEFAULT"
            r.tts_resp.is_success = True
            return Futuro(r)

    class Pub:
        def __init__(self, t): self.t = t
        def publish(self, m): publicados.append((self.t, m))

    class Reloj:
        def now(self):
            class N:
                nanoseconds = 5_000_000_123
                def to_msg(s): return Msg()
            return N()

    class Nodo:
        def create_publisher(self, tipo, topic, qos): return Pub(topic)
        def create_subscription(self, *a): pass
        def create_client(self, tipo, nombre): return Cliente(nombre)
        def get_clock(self): return Reloj()
        def destroy_node(self): pass

    class Ejecutor:
        def __init__(self, num_threads=1): pass
        def add_node(self, n): pass
        def spin(self): pass
        def shutdown(self, timeout_sec=0): pass

    rclpy = types.ModuleType("rclpy")
    rclpy.ok = lambda: True
    rclpy.init = lambda: None
    rclpy.shutdown = lambda: None
    rclpy.create_node = lambda n: Nodo()
    ejec = types.ModuleType("rclpy.executors"); ejec.MultiThreadedExecutor = Ejecutor
    qos = types.ModuleType("rclpy.qos")
    qos.QoSProfile = lambda **kw: kw
    qos.ReliabilityPolicy = Msg(BEST_EFFORT=1)
    qos.DurabilityPolicy = Msg(VOLATILE=1, TRANSIENT_LOCAL=2)

    def modulo(nombre, nombres):
        m = types.ModuleType(nombre)
        for n in nombres:
            setattr(m, n, type(n, (Msg,), {}))
        return m

    msg = modulo("aimdk_msgs.msg", ["McLocomotionVelocity", "UpperBodyCommandArray", "HandCommandArray", "HandCommand",
                                     "HandType", "CommonRequest", "RequestHeader", "McActionCommand", "MessageHeader",
                                     "McPresetMotion", "McControlArea", "PmuState"])
    msg.CommonState = Msg(SUCCESS=1, RUNNING=400)
    msg.McInputAction = Msg(INPUTACTION_ADD=1001, INPUTACTION_ENABLE=2001)
    msg.TtsPriorityLevel = Msg(INTERACTION_L6=6)
    msg.HandType.CLAW = 2

    def srv_tipo(nombre):
        return type(nombre, (), {"Request": Msg})
    srv = types.ModuleType("aimdk_msgs.srv")
    for n in ("GetMcAction", "SetMcAction", "SetMcInputSource", "SetMcPresetMotion", "PlayTts"):
        setattr(srv, n, srv_tipo(n))
    pkg = types.ModuleType("aimdk_msgs"); pkg.msg, pkg.srv = msg, srv
    for nombre, m in {"rclpy": rclpy, "rclpy.executors": ejec, "rclpy.qos": qos, "aimdk_msgs": pkg,
                      "aimdk_msgs.msg": msg, "aimdk_msgs.srv": srv}.items():
        monkeypatch.setitem(sys.modules, nombre, m)
    return publicados, servicios


def test_transporte_ros_completo_con_rclpy_simulado(monkeypatch, cfg, alertas):
    publicados, servicios = instalar_ros_falso(monkeypatch)
    t = x2_ros2.TransporteROS({**cfg["x2"]}, alertas)
    t.iniciar(espera_s=1)
    assert t.registrar_fuente("node.andamio", 40, 1000)
    assert t.accion_actual() == "STAND_DEFAULT"
    ok, _ = t.fijar_accion("JOINT_DEFAULT")
    assert ok
    t.publicar_velocidad(0.3, 0.0, 0.1)
    t.publicar_tren_superior(1, [0.0, 0.1], [0.0] * 14, [0.5, 0.5])
    t.publicar_pinza_hal(0.5, 0.5)
    assert t.movimiento(2, 1002)
    assert t.hablar("hola")
    temas = [p[0] for p in publicados]
    assert temas == ["/aima/mc/locomotion/velocity", "/mc/upper_body_command", "/aima/hal/joint/hand/command"]
    vel = publicados[0][1]
    assert (vel.forward_velocity, vel.lateral_velocity, vel.angular_velocity) == (0.3, 0.0, 0.1)
    assert vel.source == "node.andamio"
    sup = publicados[1][1]
    assert sup.hand_sub_mode == 1 and len(sup.arm_pos) == 14 and sup.head_pos == [0.0, 0.1]
    assert set(servicios) >= {"/aimdk_5Fmsgs/srv/GetMcAction", "/aimdk_5Fmsgs/srv/SetMcAction",
                              "/aimdk_5Fmsgs/srv/SetMcInputSource", "/aimdk_5Fmsgs/srv/SetMcPresetMotion",
                              "/aimdk_5Fmsgs/srv/PlayTts"}
    t.cerrar()


def test_transporte_ros_sin_sdk_da_pista(monkeypatch, cfg, alertas):
    for n in ("rclpy", "aimdk_msgs", "aimdk_msgs.msg", "aimdk_msgs.srv", "rclpy.executors", "rclpy.qos"):
        monkeypatch.setitem(sys.modules, n, None)
    t = x2_ros2.TransporteROS({**cfg["x2"]}, alertas)
    with pytest.raises(ErrorConexion) as e:
        t.iniciar()
    assert "source" in e.value.pista


def test_x2sim_sin_bateria_ni_pc3(cfg, alertas):
    from andamio.robots.x2_ros2 import RobotX2Sim
    from andamio.fabrica import ROBOTS
    assert "x2sim" in ROBOTS
    cfg["x2"]["espera_modo_s"] = 1.0
    t = TransporteFalso()
    t.bat = None                       # el simulador no publica bateria
    r = RobotX2Sim(cfg, alertas, transporte=t)
    r.conectar()
    try:
        assert r.estado()["bateria"] == 100.0
        r.hablar("hola")               # sin servicio de voz: se anuncia, no falla
        r.video("intro.mp4")
        r.luces(1, (0, 0, 255))
        r.expresion(90)
        assert not any(isinstance(c, tuple) and c[0] == "tts" for c in t.llamadas)
        assert any("diria: hola" in a["mensaje"] for a in alertas.recientes(20))
    finally:
        r.cerrar()
