import math
import time

import pytest

from andamio.autonomia import NoEncontrado, acercarse, buscar, mirar
from andamio.nucleo.errores import NoSoportado
from andamio.vision import OjoSimulado, _distancia_tamano


def preparar(entorno, objetivos):
    ojo = OjoSimulado(entorno.robot, entorno.cfg, entorno.alertas, objetivos=objetivos, hz=20)
    ojo.iniciar()
    entorno.ctx.ojo = ojo
    entorno.ej.correr({"nombre": "p", "pasos": [{"preparar": "caminar"}]})
    time.sleep(0.15)
    return ojo


def distancia(entorno, o):
    x, y, _ = entorno.robot.pose
    return math.hypot(o["x"] - x, o["y"] - y)


def test_sin_ojo_explica_que_hacer(entorno):
    entorno.ctx.ojo = None
    with pytest.raises(NoSoportado) as e:
        buscar(entorno.ctx, {"objeto": "persona"})
    assert "--ojo" in e.value.pista


def test_mirar_guarda_lo_que_ve(entorno):
    ojo = preparar(entorno, [{"clase": "persona", "x": 2.0, "y": 0.0}])
    v = mirar(entorno.ctx, {"objeto": "persona"})
    assert v["visto"] and v["lado"] == "centro" and abs(v["distancia"] - 2.0) < 0.1
    ojo.cerrar()


def test_buscar_gira_hasta_ver_y_centra(entorno):
    o = {"clase": "persona", "x": 0.0, "y": 2.0}          # a 90 grados a la izquierda: no se ve al inicio
    ojo = preparar(entorno, [o])
    d = buscar(entorno.ctx, {"objeto": "persona", "max_s": 15, "wz": 0.6})
    assert abs(d["cx"]) < 0.15
    yaw = entorno.robot.pose[2]
    assert abs(yaw - math.pi / 2) < 0.35
    assert entorno.robot.llamadas("enviar_velocidad")[-1] == (0.0, 0.0, 0.0)
    ojo.cerrar()


def test_acercarse_llega_a_la_distancia_y_frena(entorno):
    o = {"clase": "persona", "x": 2.2, "y": 0.4}
    ojo = preparar(entorno, [o])
    acercarse(entorno.ctx, {"objeto": "persona", "distancia": 1.0, "vx": 0.4, "max_s": 20})
    assert 0.6 < distancia(entorno, o) <= 1.1
    assert entorno.robot.llamadas("enviar_velocidad")[-1] == (0.0, 0.0, 0.0)
    ojo.cerrar()


def test_nunca_se_acerca_a_menos_del_minimo(entorno):
    o = {"clase": "persona", "x": 1.5, "y": 0.0}
    ojo = preparar(entorno, [o])
    acercarse(entorno.ctx, {"objeto": "persona", "distancia": 0.0, "vx": 0.4, "max_s": 20})
    assert distancia(entorno, o) >= 0.4
    ojo.cerrar()


def test_si_lo_pierde_frena_y_falla(entorno):
    o = {"clase": "persona", "x": 3.0, "y": 0.0}
    ojo = preparar(entorno, [o])
    t0 = time.monotonic()
    ojo.objetivos.clear()                                  # la persona desaparece
    with pytest.raises(NoEncontrado):
        acercarse(entorno.ctx, {"objeto": "persona", "perdido_s": 0.5})
    assert time.monotonic() - t0 < 3
    assert entorno.robot.llamadas("enviar_velocidad")[-1] == (0.0, 0.0, 0.0)
    ojo.cerrar()


def test_buscar_se_rinde_al_tiempo_maximo(entorno):
    ojo = preparar(entorno, [])
    with pytest.raises(NoEncontrado):
        buscar(entorno.ctx, {"objeto": "persona", "max_s": 1})
    ojo.cerrar()


def test_parada_corta_el_comportamiento(entorno):
    import threading
    from andamio.nucleo.errores import ErrorSeguridad
    o = {"clase": "persona", "x": 6.0, "y": 0.0}
    ojo = preparar(entorno, [o])
    threading.Timer(0.6, lambda: entorno.seg.parada("prueba")).start()
    with pytest.raises(ErrorSeguridad):
        acercarse(entorno.ctx, {"objeto": "persona", "distancia": 1.0, "max_s": 20})
    ojo.cerrar()


def test_plantilla_buscar_persona_de_punta_a_punta(entorno):
    o = {"clase": "persona", "x": 1.0, "y": 2.0}
    ojo = preparar(entorno, [o])
    from andamio.aplicacion import resolver_plantilla
    r = entorno.ej.correr(resolver_plantilla("buscar_persona"), {"distancia": 1.0, "velocidad": 0.4})
    assert r["ok"], r
    assert distancia(entorno, o) <= 1.15
    ojo.cerrar()


def test_distancia_por_tamano_razonable():
    # persona de cuerpo entero que ocupa media imagen de alto con camara de 70 grados
    d = _distancia_tamano("persona", 300, 120, 100, 240, 640, 480, 70.0)
    assert 2.5 < d < 5.5
    # persona cortada (toca el borde de abajo): usa el ancho
    d2 = _distancia_tamano("persona", 200, 0, 300, 480, 640, 480, 70.0)
    assert 0.3 < d2 < 1.2
    assert _distancia_tamano("cosa_rara", 0, 0, 10, 10, 640, 480, 70) is None


def test_detector_carga_y_no_inventa_en_imagen_vacia():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from andamio.vision import Detector, MODELO_YOLO
    if not MODELO_YOLO.exists():
        pytest.skip("sin modelo")
    assert Detector().detectar(np.full((480, 640, 3), 127, np.uint8)) == []


def test_mirar_y_si_en_plantilla(entorno):
    ojo = preparar(entorno, [{"clase": "botella", "x": 1.5, "y": 0.0}])
    r = entorno.ej.correr({"nombre": "m", "pasos": [
        {"mirar": {"objeto": "botella", "guardar_en": "visto"}},
        {"si": {"cuando": "visto.n > 0", "entonces": [{"decir": "veo una botella al ${visto.lado}"}],
                "si_no": [{"decir": "nada"}]}}]})
    assert r["ok"], r
    assert entorno.robot.dicho[-1] == "veo una botella al centro"
    ojo.cerrar()
