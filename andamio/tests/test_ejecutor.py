import pytest

from andamio.nucleo.ejecutor import PasoFallido, validar
from andamio.nucleo.errores import ErrorPlantilla, ErrorSeguridad


def plantilla(*pasos, **extra):
    return {"nombre": "t", "pasos": list(pasos), **extra}


def test_plantilla_basica(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "caminar"}, {"caminar": {"vx": 0.3, "duracion": 0.2}}, {"decir": "hola"}))
    assert r["ok"], r
    assert entorno.robot.dicho == ["hola"]
    assert entorno.robot.pose[0] > 0
    assert entorno.robot.llamadas("enviar_velocidad")[-1] == (0.0, 0.0, 0.0)


def test_preparar_pasa_por_los_modos_intermedios(entorno):
    entorno.ej.correr(plantilla({"preparar": "caminar"}))
    assert [a[0] for a in entorno.robot.llamadas("cambiar_modo")] == ["fijo", "estable", "caminar"]


def test_alias_de_modo(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "brazos"}))
    assert r["ok"] and entorno.robot.estado()["modo"] == "tren_superior"


def test_parametros_y_sobrescritura(entorno):
    p = plantilla({"preparar": "caminar"}, {"caminar": {"vx": "${v}", "duracion": 0.2}}, parametros={"v": 0.2})
    entorno.ej.correr(p, {"v": 0.35})
    assert (0.35, 0.0, 0.0) in entorno.robot.llamadas("enviar_velocidad")


def test_variable_sin_definir_es_error_de_plantilla(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "caminar"}, {"caminar": {"vx": "${no_existe}", "duracion": 1}}))
    assert not r["ok"] and "no_existe" in r["causa"]


def test_reintentos_recuperan_un_fallo(entorno):
    entorno.robot._fallas["cambiar_modo"] = 1
    r = entorno.ej.correr(plantilla({"preparar": "estable", "reintentos": 2}))
    assert r["ok"], r
    assert r["pasos"][0]["intentos"] == 2


def test_sin_reintentos_aborta_y_para(entorno):
    entorno.robot._fallas["cambiar_modo"] = 1
    r = entorno.ej.correr(plantilla({"preparar": "estable"}, {"decir": "no deberia llegar"}))
    assert not r["ok"]
    assert entorno.robot.dicho == []


def test_en_fallo_continuar(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "estable"}, {"gesto": {"nombre": "inventado"}, "en_fallo": "continuar"}, {"registrar": "sigue"}))
    assert r["ok"], r
    assert r["pasos"][1]["ok"] is False


def test_en_fallo_continuar_no_salta_la_seguridad(entorno):
    r = entorno.ej.correr(plantilla({"gesto": {"nombre": "saludar"}, "en_fallo": "continuar"}, {"registrar": "no debe llegar"}))
    assert not r["ok"] and len(r["pasos"]) == 1


def test_en_fallo_parar_activa_la_parada(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "estable"}, {"gesto": {"nombre": "inventado"}, "en_fallo": "parar"}))
    assert not r["ok"] and entorno.seg.parado


def test_error_de_seguridad_nunca_se_reintenta(entorno):
    entorno.robot.fijar_bateria(10)
    entorno.robot.forzar_modo("estable")
    r = entorno.ej.correr(plantilla({"caminar": {"vx": 0.3, "duracion": 1}, "reintentos": 5}))
    assert not r["ok"]
    assert len(entorno.robot.llamadas("enviar_velocidad")) <= 3


def test_modo_seco_no_envia_nada(entorno):
    entorno.ctx.seco = True
    r = entorno.ej.correr(plantilla({"preparar": "caminar"}, {"caminar": {"vx": 0.3, "duracion": 5}}))
    assert r["ok"]
    assert entorno.robot.llamadas("cambiar_modo") == [] and entorno.robot.llamadas("enviar_velocidad") == []


def test_repetir_y_condicional(entorno):
    p = plantilla({"preparar": "estable"},
                  {"repetir": {"veces": 3, "pasos": [{"decir": "tic"}]}},
                  {"si": {"cuando": "estado.bateria >= 60", "entonces": [{"decir": "buena"}], "si_no": [{"decir": "baja"}]}})
    entorno.ej.correr(p)
    assert entorno.robot.dicho == ["tic", "tic", "tic", "buena"]


def test_condicion_falsa(entorno):
    entorno.robot.fijar_bateria(55)
    entorno.ej.correr(plantilla({"si": {"cuando": "estado.bateria >= 60", "entonces": [{"decir": "a"}], "si_no": [{"decir": "b"}]}}))
    assert entorno.robot.dicho == ["b"]


def test_validacion_detecta_errores(entorno):
    problemas = validar({"pasos": [{"caminr": {}}, {"caminar": {"vx": 1, "rapido": 2}}, {"preparar": "x", "decir": "y"},
                                   {"repetir": {"veces": 2}}, {"si": {"cuando": "tonteria"}}]}, entorno.robot)
    assert len(problemas) >= 5
    assert any("caminr" in p for p in problemas)
    assert any("rapido" in p for p in problemas)


def test_plantilla_invalida_no_ejecuta_nada(entorno):
    with pytest.raises(ErrorPlantilla):
        entorno.ej.correr({"pasos": [{"nada": 1}]})
    assert entorno.robot.registro == [(t, m, a) for (t, m, a) in entorno.robot.registro if m == "conectar"]


def test_requiere_capacidad(entorno):
    entorno.robot.capacidades = frozenset({"caminar"})
    with pytest.raises(ErrorPlantilla):
        entorno.ej.correr(plantilla({"decir": "x"}, requiere=["brazos"]))


def test_yaml_roto(tmp_path, entorno):
    f = tmp_path / "mala.yaml"
    f.write_text("pasos: [\n  - {a: ")
    with pytest.raises(ErrorPlantilla):
        entorno.ej.correr(f)


def test_plantilla_inexistente(entorno):
    with pytest.raises(ErrorPlantilla):
        entorno.ej.correr("/no/existe.yaml")


def test_parada_de_emergencia_aborta_la_plantilla(entorno):
    import threading
    threading.Timer(0.2, lambda: entorno.seg.parada("prueba")).start()
    r = entorno.ej.correr(plantilla({"preparar": "caminar"}, {"caminar": {"vx": 0.3, "duracion": 5}}, {"decir": "no"}))
    assert not r["ok"] and "decir" not in str(r["pasos"])
    assert entorno.robot.dicho == []


def test_brazos_se_interpolan_y_respetan_velocidad(entorno):
    entorno.ej.correr(plantilla({"preparar": "tren_superior"},
                                {"brazos": {"izq": [0.3] * 7, "der": [0.0] * 7, "segundos": 0.3}}))
    llamadas = entorno.robot.llamadas("brazos")
    assert len(llamadas) >= 5
    assert llamadas[-1][0] == [0.3] * 7
    pasos = [abs(b[0][0] - a[0][0]) for a, b in zip(llamadas, llamadas[1:])]
    assert max(pasos) < 0.1


def test_brazos_con_datos_malos(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "tren_superior"}, {"brazos": {"izq": [0] * 3, "der": [0] * 7}}))
    assert not r["ok"]


def test_mano_valida_rango_y_lado(entorno):
    assert entorno.ej.correr(plantilla({"preparar": "tren_superior"}, {"mano": {"lado": "ambas", "cerrar": True}}))["ok"]
    assert entorno.robot.manos_actuales["izquierda"][0] == 0.0
    assert not entorno.ej.correr(plantilla({"mano": {"lado": "ambas", "valor": 2}}))["ok"]
    assert not entorno.ej.correr(plantilla({"mano": {"lado": "centro", "valor": 1}}))["ok"]


def test_distancia_se_estima_por_tiempo(entorno):
    r = entorno.ej.correr(plantilla({"preparar": "caminar"}, {"caminar": {"vx": 0.4, "distancia": 0.1}}))
    assert r["ok"]
    assert entorno.alertas.conteo["aviso"] >= 1


def test_girar_calcula_duracion(entorno):
    entorno.ej.correr(plantilla({"preparar": "caminar"}, {"girar": {"grados": 20, "wz": 0.6}}))
    assert abs(entorno.robot.pose[2] - 0.349) < 0.12


def test_cierre_siempre_detiene(entorno):
    entorno.ej.correr(plantilla({"preparar": "caminar"}, {"caminar": {"vx": 0.3, "duracion": 0.2}}, {"gesto": {"nombre": "no"}}))
    import time
    time.sleep(0.2)
    assert entorno.robot.llamadas("enviar_velocidad")[-1] == (0.0, 0.0, 0.0)


def test_grabar_guarda_episodio(entorno, tmp_path):
    from andamio.grabador import Grabador
    entorno.ctx.grabador = Grabador(tmp_path)
    r = entorno.ej.correr(plantilla({"grabar": {"tarea": "x", "pasos": [{"esperar": 0.05}]}}))
    assert r["ok"]
    carpetas = list(tmp_path.iterdir())
    assert len(carpetas) == 1 and (carpetas[0] / "manifiesto.json").exists()
