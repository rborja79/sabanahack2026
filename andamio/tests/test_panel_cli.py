import json
import urllib.request
import urllib.error

import pytest

from andamio.aplicacion import Aplicacion, listar_plantillas
from andamio.panel import Panel
from andamio import __main__ as cli, doctor


@pytest.fixture
def panel(tmp_path):
    app = Aplicacion("falso", confirmo=False, oido="panel", consola=False)
    app.seguridad.iniciar()
    p = Panel(app, puerto=0, abrir=False)
    p.iniciar()
    yield app, p
    p.cerrar()
    app.seguridad.cerrar()


def pedir(p, ruta, metodo="GET", token=None, cuerpo=None, host=None):
    req = urllib.request.Request(f"http://127.0.0.1:{p.puerto}{ruta}", method=metodo,
                                 data=json.dumps(cuerpo or {}).encode() if metodo == "POST" else None)
    if token:
        req.add_header("X-Token", token)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_estado_y_pagina(panel):
    app, p = panel
    codigo, cuerpo = pedir(p, "/api/estado")
    est = json.loads(cuerpo)
    assert codigo == 200 and est["robot"] == "falso" and est["parado"] is False
    assert "caminar.yaml" in est["plantillas"]
    codigo, cuerpo = pedir(p, "/")
    assert codigo == 200 and p.token.encode() in cuerpo


def test_ordenes_exigen_token(panel):
    app, p = panel
    assert pedir(p, "/api/parar", "POST")[0] == 403
    assert pedir(p, "/api/parar", "POST", token="falso")[0] == 403
    assert not app.seguridad.parado
    assert pedir(p, "/api/parar", "POST", token=p.token)[0] == 200
    assert app.seguridad.parado
    pedir(p, "/api/reanudar", "POST", token=p.token)
    assert not app.seguridad.parado


def test_rechaza_host_ajeno_contra_dns_rebinding(panel):
    _, p = panel
    assert pedir(p, "/api/estado", host="malo.example.com")[0] == 403


def test_voz_por_el_panel_llega_al_oido(panel):
    app, p = panel
    pedir(p, "/api/voz", "POST", token=p.token, cuerpo={"texto": "camina"})
    assert app.cola_voz.escuchar(0.5) == "camina"


def test_confirmar_por_el_panel(panel):
    import threading
    app, p = panel
    resultado = []
    t = threading.Thread(target=lambda: resultado.append(app.seguridad.confirmar("de pie?", timeout=3)))
    t.start()
    for _ in range(50):
        if json.loads(pedir(p, "/api/estado")[1])["pendiente"]:
            break
        import time; time.sleep(0.05)
    pedir(p, "/api/confirmar", "POST", token=p.token)
    t.join(3)
    assert resultado == [True]


def test_correr_plantilla_desde_el_panel(panel):
    import time
    app, p = panel
    app.seguridad.auto_confirmar = True
    codigo, cuerpo = pedir(p, "/api/correr", "POST", token=p.token, cuerpo={"plantilla": "saludar.yaml"})
    assert json.loads(cuerpo)["ok"]
    for _ in range(100):
        if app.ultimo:
            break
        time.sleep(0.05)
    assert app.ultimo["ok"] and app.robot.llamadas("gesto") == [("saludar", "derecha")]


def test_plantilla_inexistente_desde_el_panel(panel):
    _, p = panel
    codigo, cuerpo = pedir(p, "/api/correr", "POST", token=p.token, cuerpo={"plantilla": "nada.yaml"})
    r = json.loads(cuerpo)
    assert r["ok"] is False and "nada.yaml" in r["error"] and "disponibles" in r["error"]


# ----------------------------------------------------------------- CLI
def test_todas_las_plantillas_validan_con_el_robot_sim():
    from .conftest import requiere_modelo
    requiere_modelo()
    app = Aplicacion("sim", consola=False, seco=True)
    for n in listar_plantillas():
        assert app.validar(n) == [], n


def test_cli_listar(capsys):
    assert cli.principal(["--listar"]) == 0
    assert "caminar.yaml" in capsys.readouterr().out


def test_cli_ejecuta_con_robot_falso(capsys):
    assert cli.principal(["saludar", "--robot", "falso", "--confirmo"]) == 0


def test_cli_codigo_de_salida_si_falla():
    assert cli.principal(["caminar", "--robot", "falso", "--confirmo", "--param", "velocidad=\"rapido\""]) == 1


def test_cli_plantilla_que_no_existe(capsys):
    assert cli.principal(["nadaquever", "--robot", "falso"]) == 2
    assert "disponibles" in capsys.readouterr().err


def test_cli_no_permite_confirmar_solo_con_robot_real(capsys):
    assert cli.principal(["saludar", "--robot", "x2", "--confirmo"]) == 2


def test_cli_validar_plantilla_mala(tmp_path, capsys):
    f = tmp_path / "m.yaml"
    f.write_text("pasos:\n  - {caminr: {}}\n")
    assert cli.principal([str(f), "--validar"]) == 1


def test_cli_parametro_mal_formado(capsys):
    assert cli.principal(["saludar", "--param", "sinigual"]) == 2


def test_doctor_no_se_cae_y_encuentra_fallos():
    inf = doctor.revisar("x2")
    assert any(f["nombre"].startswith("SDK AimDK") for f in inf.filas)
    inf = doctor.revisar("general")
    assert inf.filas and doctor.principal(["--robot", "general", "--json"]) in (0, 1)


def test_doctor_remoto_sin_servidor():
    inf = doctor.revisar("remoto")
    assert any(f["nivel"] == "FALLO" for f in inf.filas)


def test_modelo_incompleto_se_detecta(tmp_path):
    from andamio.robots.sim_mujoco import mallas_faltantes
    (tmp_path / "meshes").mkdir()
    (tmp_path / "meshes" / "a.stl").write_bytes(b"x")
    (tmp_path / "meshes" / "vacio.stl").write_bytes(b"")
    xml = tmp_path / "m.xml"
    xml.write_text('<mujoco><compiler meshdir="meshes/"/><asset><mesh name="a" file="a.stl"/>'
                   '<mesh name="b" file="falta.stl"/><mesh name="c" file="vacio.stl"/></asset></mujoco>')
    assert sorted(mallas_faltantes(xml)) == ["meshes/falta.stl", "meshes/vacio.stl"]
