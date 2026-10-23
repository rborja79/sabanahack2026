import time

import pytest

from andamio.nucleo.errores import ErrorSeguridad, NoSoportado
from andamio.robots.falso import RobotFalso


def poner_de_pie(e):
    e.robot.preparar("estable")


def test_recorta_velocidad_al_limite(entorno):
    vx, vy, wz = entorno.seg.limitar_velocidad(5.0, -5.0, 9.0)
    assert (vx, vy, wz) == (0.4, -0.3, 0.6)
    assert entorno.alertas.conteo["aviso"] >= 3


def test_velocidad_bajo_el_minimo_sube_al_minimo(entorno):
    entorno.robot.vel_min = (0.2, 0.2, 0.1)
    assert entorno.seg.limitar_velocidad(0.05, 0.0, 0.0)[0] == 0.2
    assert entorno.seg.limitar_velocidad(0.003, 0.0, 0.0)[0] == 0.0


def test_rechaza_nan_e_infinito(entorno):
    with pytest.raises(ErrorSeguridad):
        entorno.seg.limitar_velocidad(float("nan"), 0, 0)
    with pytest.raises(ErrorSeguridad):
        entorno.seg.limitar_velocidad(float("inf"), 0, 0)
    with pytest.raises(ErrorSeguridad):
        entorno.seg.limitar_velocidad("rapido", 0, 0)


def test_limite_menor_que_el_minimo_del_robot_es_error(entorno):
    entorno.robot.vel_min = (0.5, 0.5, 0.5)
    with pytest.raises(ErrorSeguridad):
        entorno.seg.limitar_velocidad(0.3, 0, 0)


def test_mover_envia_y_termina_en_cero(entorno):
    poner_de_pie(entorno)
    entorno.seg.mover(0.3, 0, 0, 0.3)
    envios = entorno.robot.llamadas("enviar_velocidad")
    assert any(a == (0.3, 0.0, 0.0) for a in envios)
    assert envios[-1] == (0.0, 0.0, 0.0)
    assert entorno.robot.pose[0] > 0.02


def test_el_robot_recibe_ordenes_repetidas(entorno):
    poner_de_pie(entorno)
    entorno.seg.mover(0.3, 0, 0, 0.5)
    n = sum(1 for a in entorno.robot.llamadas("enviar_velocidad") if a[0] == 0.3)
    assert n >= 15            # a 100 Hz durante 0.5 s: el robot real se frena si pasan 200 ms sin ordenes


def test_duracion_fuera_de_rango(entorno):
    poner_de_pie(entorno)
    for d in (0, -1, 61, "x"):
        with pytest.raises(ErrorSeguridad):
            entorno.seg.mover(0.3, 0, 0, d)


def test_no_camina_con_bateria_baja(entorno):
    poner_de_pie(entorno)
    entorno.robot.fijar_bateria(40)
    with pytest.raises(ErrorSeguridad) as e:
        entorno.seg.mover(0.3, 0, 0, 0.2)
    assert "bateria" in str(e.value) and e.value.pista


def test_no_camina_en_modo_incorrecto(entorno):
    with pytest.raises(ErrorSeguridad) as e:
        entorno.seg.mover(0.3, 0, 0, 0.2)
    assert "preparar" in e.value.pista


def test_bateria_critica_dispara_parada(entorno):
    poner_de_pie(entorno)
    entorno.robot.fijar_bateria(25)
    t = time.monotonic()
    while not entorno.seg.parado and time.monotonic() - t < 2:
        time.sleep(0.02)
    assert entorno.seg.parado
    assert entorno.robot.llamadas("emergencia")
    with pytest.raises(ErrorSeguridad):
        entorno.seg.mover(0.3, 0, 0, 0.2)


def test_parada_interrumpe_un_movimiento_en_curso(entorno):
    poner_de_pie(entorno)
    import threading
    threading.Timer(0.15, lambda: entorno.seg.parada("prueba")).start()
    t0 = time.monotonic()
    with pytest.raises(ErrorSeguridad):
        entorno.seg.mover(0.3, 0, 0, 5.0)
    assert time.monotonic() - t0 < 1.5
    assert entorno.robot.llamadas("emergencia")


def test_reanudar_levanta_la_parada(entorno):
    poner_de_pie(entorno)
    entorno.seg.parada("x")
    entorno.seg.reanudar()
    entorno.seg.mover(0.3, 0, 0, 0.1)


def test_salir_del_modo_esperado_mientras_camina_para(entorno):
    poner_de_pie(entorno)
    entorno.seg.esperar_modos({"estable", "caminar"})
    import threading

    def caida():
        time.sleep(0.15)
        entorno.robot.forzar_modo("amortiguado")
    threading.Thread(target=caida).start()
    with pytest.raises(ErrorSeguridad):
        entorno.seg.mover(0.3, 0, 0, 3.0)
    assert entorno.seg.parado


def test_perdida_de_conexion_detiene(entorno):
    poner_de_pie(entorno)
    import threading
    threading.Timer(0.1, entorno.robot.desconectar_cable).start()
    with pytest.raises(ErrorSeguridad):
        entorno.seg.mover(0.3, 0, 0, 3.0)
    assert entorno.seg.parado


def test_fallos_de_envio_seguidos_paran(entorno):
    poner_de_pie(entorno)
    entorno.robot._fallas["enviar_velocidad"] = 1000
    with pytest.raises(ErrorSeguridad):
        entorno.seg.mover(0.3, 0, 0, 3.0)
    assert entorno.seg.parado
    assert entorno.alertas.hubo("critico")


def test_capacidad_no_soportada(cfg, alertas):
    from andamio.nucleo.seguridad import Seguridad

    class Mudo(RobotFalso):
        capacidades = frozenset({"caminar"})
    r = Mudo(cfg, alertas)
    r.conectar()
    s = Seguridad(r, alertas, cfg, True)
    with pytest.raises(NoSoportado):
        s.revisar_antes("brazos")


def test_confirmacion_por_panel(cfg, alertas):
    import threading
    r = RobotFalso(cfg, alertas)
    r.conectar()
    from andamio.nucleo.seguridad import Seguridad
    s = Seguridad(r, alertas, cfg, auto_confirmar=False)
    threading.Timer(0.2, s.confirmar_ahora).start()
    assert s.confirmar("de pie?", timeout=3)


def test_confirmacion_sin_respuesta_falla(cfg, alertas):
    r = RobotFalso(cfg, alertas)
    from andamio.nucleo.seguridad import Seguridad
    s = Seguridad(r, alertas, cfg, auto_confirmar=False)
    with pytest.raises(ErrorSeguridad):
        s.confirmar("de pie?", timeout=0.3)
