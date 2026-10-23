import socket
import threading
import time

import pytest

from andamio.nucleo.errores import ErrorConexion, ErrorRobot, ErrorSeguridad
from andamio.nucleo.seguridad import Seguridad
from andamio.robots.falso import RobotFalso
from andamio.robots.remoto import RobotRemoto
from andamio.servidor_robot import ServidorRobot


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor(cfg, alertas):
    real = RobotFalso(cfg, alertas)
    real.conectar()
    p = puerto_libre()
    srv = ServidorRobot(real, alertas, cfg, "secreto-de-prueba-123", host="127.0.0.1", puerto=p)
    threading.Thread(target=srv.servir, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", p), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.02)
    yield srv, real, p
    srv.cerrar()


def cliente(cfg, alertas, p, token="secreto-de-prueba-123"):
    c = RobotRemoto(cfg, alertas, host="127.0.0.1", puerto=p, token=token)
    c.timeout = 2.0
    return c


def test_conecta_y_copia_las_capacidades(servidor, cfg, alertas):
    srv, real, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    assert c.tiene("caminar") and c.nombre == "remoto:falso"
    assert c.grafo["estable"] == real.grafo["estable"]
    assert c.estado()["modo"] == "pasivo"
    c.cerrar()


def test_token_incorrecto(servidor, cfg, alertas):
    _, _, p = servidor
    c = cliente(cfg, alertas, p, "malo")
    with pytest.raises(ErrorConexion) as e:
        c.conectar()
    assert "token" in str(e.value)


def test_servidor_sin_token_no_arranca(cfg, alertas):
    with pytest.raises(ErrorConexion):
        ServidorRobot(RobotFalso(cfg, alertas), alertas, cfg, "")


def test_un_solo_cliente_a_la_vez(servidor, cfg, alertas):
    _, _, p = servidor
    a = cliente(cfg, alertas, p)
    a.conectar()
    b = cliente(cfg, alertas, p)
    with pytest.raises(ErrorConexion) as e:
        b.conectar()
    assert "otro computador" in str(e.value)
    a.cerrar()


def test_errores_del_robot_llegan_con_su_clase_y_pista(servidor, cfg, alertas):
    srv, real, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    with pytest.raises(ErrorRobot) as e:
        c.cambiar_modo("caminar")             # desde pasivo no se puede
    assert "rechaza" in str(e.value) and e.value.pista
    c.cerrar()


def test_seguridad_local_sobre_robot_remoto_camina(servidor, cfg, alertas):
    srv, real, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    seg = Seguridad(c, alertas, cfg, auto_confirmar=True)
    seg.iniciar()
    c.preparar("estable")
    seg.mover(0.3, 0, 0, 0.5)
    seg.cerrar()
    assert real.pose[0] > 0.05
    time.sleep(0.2)
    assert real.llamadas("enviar_velocidad")[-1] == (0.0, 0.0, 0.0)
    c.cerrar()


def test_el_servidor_frena_si_el_cliente_se_calla(servidor, cfg, alertas):
    srv, real, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    c.preparar("estable")
    c.enviar_velocidad(0.3, 0, 0)             # una sola orden y luego silencio
    time.sleep(0.15)
    assert (0.3, 0.0, 0.0) in real.llamadas("enviar_velocidad")
    time.sleep(0.8)
    assert real.llamadas("enviar_velocidad")[-1] == (0.0, 0.0, 0.0)
    antes = len(real.llamadas("enviar_velocidad"))
    time.sleep(0.3)
    assert len(real.llamadas("enviar_velocidad")) == antes        # dejo de repetir
    c.cerrar()


def test_si_se_cae_el_cliente_el_servidor_frena(servidor, cfg, alertas):
    srv, real, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    c.preparar("estable")
    c.enviar_velocidad(0.3, 0, 0)
    time.sleep(0.1)
    c.cerrar()
    time.sleep(0.8)
    assert real.llamadas("enviar_velocidad")[-1] == (0.0, 0.0, 0.0)
    assert srv._cliente is None


def test_el_servidor_recorta_aunque_el_cliente_no(servidor, cfg, alertas):
    srv, real, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    c.preparar("estable")
    c.enviar_velocidad(5.0, 0, 0)
    time.sleep(0.1)
    assert max(a[0] for a in real.llamadas("enviar_velocidad")) == 0.4
    c.cerrar()


def test_el_servidor_rechaza_metodos_no_permitidos(servidor, cfg, alertas):
    _, _, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    from andamio.nucleo.errores import ErrorAndamio
    with pytest.raises(ErrorAndamio):
        c._rpc("__class__")
    with pytest.raises(ErrorAndamio):
        c._rpc("desconectar_cable")
    c.cerrar()


def test_error_asincrono_de_velocidad_se_levanta_en_la_siguiente_orden(servidor, cfg, alertas):
    srv, real, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    c.enviar_velocidad(0.3, 0, 0)            # el falso esta en pasivo: no puede caminar
    time.sleep(0.2)
    with pytest.raises(ErrorRobot):
        c.enviar_velocidad(0.3, 0, 0)
    c.cerrar()


def test_servidor_inalcanzable_da_pista(cfg, alertas):
    c = RobotRemoto(cfg, alertas, host="127.0.0.1", puerto=puerto_libre(), token="x")
    with pytest.raises(ErrorConexion) as e:
        c.conectar()
    assert "servidor" in e.value.pista


def test_sin_token_pide_token(cfg, alertas):
    c = RobotRemoto(cfg, alertas, host="127.0.0.1", puerto=1, token="")
    with pytest.raises(ErrorConexion) as e:
        c.conectar()
    assert "ANDAMIO_TOKEN" in e.value.pista


def test_tras_perder_la_conexion_las_ordenes_fallan_limpio(servidor, cfg, alertas):
    srv, real, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    srv.cerrar()
    time.sleep(0.2)
    with pytest.raises(ErrorConexion):
        for _ in range(5):
            c.estado()
            time.sleep(0.1)


def test_vision_remota(servidor, cfg, alertas):
    from andamio.nucleo.errores import NoSoportado
    from andamio.vision import OjoRemoto, OjoSimulado
    srv, real, p = servidor
    c = cliente(cfg, alertas, p)
    c.conectar()
    with pytest.raises(NoSoportado):
        c.ver_remoto()                                   # el servidor arranco sin ojo
    srv.ojo = OjoSimulado(real, cfg, alertas, objetivos=[{"clase": "persona", "x": 2.0, "y": 0.0}], hz=20)
    srv.ojo.iniciar()
    time.sleep(0.2)
    dets = c.ver_remoto()
    assert dets and dets[0]["clase"] == "persona" and abs(dets[0]["distancia"] - 2.0) < 0.1
    ojo = OjoRemoto(c, cfg, alertas, hz=10)
    ojo.iniciar()
    time.sleep(0.6)
    assert ojo.ver("persona")
    ojo.cerrar()
    srv.ojo.cerrar()
    c.cerrar()
