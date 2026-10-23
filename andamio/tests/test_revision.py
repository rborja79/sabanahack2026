"""Pruebas de las correcciones de la revision de seguridad."""
import threading
import time

import pytest

from andamio import config
from andamio.nucleo.errores import ErrorConfiguracion, ErrorSeguridad
from andamio.nucleo.validacion import finito, lista_finita
from andamio.nucleo.voz import Entendedor, OidoCola, es_alto


def plantilla(*pasos, **extra):
    return {"nombre": "t", "pasos": list(pasos), **extra}


# ---------- validacion ----------
@pytest.mark.parametrize("malo", [float("nan"), float("inf"), True, "abc", None])
def test_finito_rechaza_basura(malo):
    with pytest.raises(ErrorSeguridad):
        finito(malo, "x")


def test_lista_finita():
    assert lista_finita([0, 1.5], 2, "q") == [0.0, 1.5]
    with pytest.raises(ErrorSeguridad):
        lista_finita([0, float("nan")], 2, "q")
    with pytest.raises(ErrorSeguridad):
        lista_finita([0], 2, "q")


# ---------- modos ----------
def test_modo_desconocido_o_none_se_rechaza(entorno):
    entorno.robot.forzar_modo(None)
    with pytest.raises(ErrorSeguridad):
        entorno.seg.revisar_antes("caminar")


def test_pasivo_pide_confirmacion(entorno):
    entorno.seg.auto_confirmar = False
    entorno.seg.confirmar_ahora()          # no debe bloquear: deja el permiso listo
    r = entorno.ej.correr(plantilla({"preparar": "pasivo"}))
    assert isinstance(r, dict)


def test_parada_durante_preparar_aborta(entorno):
    entorno.seg.parada("prueba")
    r = entorno.ej.correr(plantilla({"preparar": "caminar"}))
    assert not r["ok"]
    assert entorno.robot.llamadas("cambiar_modo") == []


# ---------- velocidades efectivas ----------
def test_distancia_usa_velocidad_efectiva(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "caminar"}, {"caminar": {"vx": 5.0, "duracion": 0.1}}))
    vels = [v for v in entorno.robot.llamadas("enviar_velocidad") if v[0]]
    assert vels and max(abs(v[0]) for v in vels) <= entorno.cfg["seguridad"]["vx_max"] + 1e-9


# ---------- condiciones ----------
def test_condicion_con_nombre_sin_comillas_falla(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "caminar"},
                                    {"si": {"cuando": "estado.modo == caminar", "entonces": [{"decir": "x"}]}}))
    assert not r["ok"]


def test_condicion_con_comillas_funciona(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "caminar"},
                                    {"si": {"cuando": "estado.modo == 'caminar'", "entonces": [{"decir": "ok"}]}}))
    assert r["ok"] and "ok" in entorno.robot.dicho


def test_reintentos_debe_ser_entero(entorno):
    from andamio.nucleo.errores import ErrorPlantilla
    with pytest.raises(ErrorPlantilla):
        entorno.ej.correr(plantilla({"decir": "x", "reintentos": True}))


# ---------- config ----------
def test_config_rechaza_nan():
    with pytest.raises(ErrorConfiguracion):
        config.cargar(entorno={"ANDAMIO_SEGURIDAD__VX_MAX": "nan"})


def test_config_rechaza_clave_desconocida():
    with pytest.raises(ErrorConfiguracion):
        config.cargar(entorno={"ANDAMIO_SEGURIDAD__NO_EXISTE": "1"})


def test_config_bateria_critica_menor_que_minima():
    with pytest.raises(ErrorConfiguracion):
        config.cargar(entorno={"ANDAMIO_SEGURIDAD__BATERIA_CRITICA": "90"})


# ---------- voz ----------
CMDS = {"parar": {"descripcion": "parar", "palabras": ["para"]},
        "adelante": {"descripcion": "adelante", "palabras": ["adelante", "camina"]},
        "atras": {"descripcion": "atras", "palabras": ["atras"]}}


def entender(texto, alertas):
    return Entendedor(CMDS, alertas, cliente=None).por_reglas(texto)


def test_es_alto():
    assert es_alto("por favor pare ya") and es_alto("STOP") and not es_alto("camina")


def test_alto_siempre_funciona_aunque_la_plantilla_no_tenga_parar(alertas):
    e = Entendedor({"adelante": CMDS["adelante"]}, alertas)
    assert e.por_reglas("pare").accion == "parar"


def test_negacion_lejana_cancela(alertas):
    assert entender("no creo que sea buena idea que camines adelante", alertas).accion is None


def test_dos_comandos_distintos_es_ambiguo(alertas):
    assert entender("adelante y atras", alertas).accion is None


def test_cola_voz_llama_gancho_al_instante():
    vistos = []
    o = OidoCola(al_poner=vistos.append)
    o.poner("para")
    assert vistos == ["para"]


def test_para_por_voz_corta_un_comando_en_curso(entorno):
    cola = OidoCola(al_poner=lambda t: es_alto(t) and entorno.seg.interrumpir())
    entorno.ctx.oido = cola
    entorno.ctx.entendedor = None
    plan = {"nombre": "v", "requiere": ["caminar"],
            "comandos": {"adelante": {"descripcion": "adelante", "palabras": ["adelante"],
                                      "pasos": [{"caminar": {"vx": 0.3, "duracion": 6}}]},
                         "parar": {"descripcion": "parar", "palabras": ["para"], "pasos": [{"parar": {}}]}},
            "pasos": [{"preparar": "caminar"}, {"voz_bucle": {"escuchar_s": 0.1}}]}

    def hablar():
        cola.poner("adelante")
        time.sleep(0.6)
        cola.poner("para")
        time.sleep(0.5)
        cola.poner("salir")

    hilo = threading.Thread(target=hablar)
    t0 = time.monotonic()
    hilo.start()
    entorno.ej.correr(plan)
    hilo.join()
    assert time.monotonic() - t0 < 4.0
    assert entorno.robot.llamadas("enviar_velocidad")[-1] == (0.0, 0.0, 0.0)


# ---------- aplicacion: una sola plantilla a la vez ----------
def test_dos_plantillas_a_la_vez_se_rechazan(tmp_path):
    from andamio.aplicacion import Aplicacion
    from andamio.nucleo.errores import ErrorAndamio
    lenta = tmp_path / "lenta.yaml"
    lenta.write_text("nombre: lenta\npasos:\n  - esperar: 1.5\n", encoding="utf-8")
    app = Aplicacion(robot="falso", consola=False)
    try:
        app.ejecutar_en_hilo(str(lenta))
        with pytest.raises(ErrorAndamio):
            app.ejecutar_en_hilo(str(lenta))
        app._hilo.join(10)
        assert app.corriendo is None
    finally:
        app.cerrar()
