import asyncio
import json
import socket
import threading
import time

import numpy as np
import pytest

from andamio.grabador import Grabador
from andamio.nucleo.errores import ErrorSeguridad
from andamio.robots.sim_mujoco import RobotSim
from andamio.teleop import Teleop

from .conftest import requiere_modelo


def libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def tele(cfg, alertas, tmp_path):
    from andamio.nucleo.seguridad import Seguridad
    requiere_modelo()
    robot = RobotSim(cfg, alertas)
    robot.conectar()
    robot.preparar("tren_superior")
    seg = Seguridad(robot, alertas, cfg, auto_confirmar=True)
    seg.iniciar()
    cfg["teleop"]["puerto"] = libre()
    g = Grabador(tmp_path)
    t = Teleop(robot, seg, alertas, cfg, g)
    yield t
    t.detener()
    seg.cerrar()


def manos(dx=0.0, dz=0.0, pinza=1.0):
    return {"type": "manos", "right": {"p": [0.3 + dx, 1.2, -0.3 + dz], "pinza": pinza}}


def test_la_mano_mueve_la_muneca_del_robot(tele):
    inicio = tele.ik.pos_efector("derecha").copy()
    tele.recibir(manos())
    tele.recibir(manos(dx=0.05, dz=0.08))
    for _ in range(80):
        tele.paso()
    fin = tele.robot.modelo.pos_efector("derecha")
    delta = fin - inicio
    assert delta[0] > 0.02 or delta[2] > 0.03
    assert np.linalg.norm(delta) > 0.03


def test_el_ancla_hace_que_el_primer_mensaje_no_mueva_nada(tele):
    antes = tele.q_cmd["derecha"].copy()
    tele.recibir(manos())
    for _ in range(20):
        tele.paso()
    assert np.allclose(tele.q_cmd["derecha"], antes, atol=1e-2)


def test_limite_de_velocidad_articular(tele):
    tele.recibir(manos())
    tele.recibir(manos(dx=0.3, dz=0.3))
    previo = tele.q_cmd["derecha"].copy()
    tele.paso()
    assert np.max(np.abs(tele.q_cmd["derecha"] - previo)) <= tele.cfg["vel_art_max"] / tele.hz + 1e-9


def test_pinza_llega_al_robot(tele):
    tele.recibir(manos(pinza=0.2))
    tele.paso()
    assert tele.robot.manos_actuales["derecha"][0] == pytest.approx(0.2)


def test_mensajes_malos_no_tumban(tele):
    for m in (None, 3, {"type": "manos", "right": {"p": "x"}}, {"type": "manos", "right": {"p": [1, 2]}},
              {"type": "manos", "right": {"p": [float("nan"), 0, 0]}}, {"type": "cmd", "cmd": "bailar"}, {"type": "otro"}):
        tele.recibir(m)
    assert tele.recibir({"type": "cmd", "cmd": "bailar"})["type"] == "error"
    tele.paso()


def test_calibrar_y_reset(tele):
    tele.recibir(manos())
    r = tele.recibir({"type": "cmd", "cmd": "calibrar"})
    assert r["texto"] == "calibrado" and "derecha" in tele.anclas
    tele.recibir(manos(dx=0.1))
    r = tele.recibir({"type": "cmd", "cmd": "reset"})
    assert tele.anclas == {}


def test_mano_fuera_de_alcance_avisa_sin_romper(tele, alertas):
    tele.recibir(manos())
    tele.recibir(manos(dx=5.0))
    assert alertas.conteo["aviso"] >= 1
    for _ in range(20):
        tele.paso()
    assert np.all(np.isfinite(tele.q_cmd["derecha"]))


def test_no_envia_con_parada_activa(tele):
    tele.seguridad.parada("x")
    assert tele.paso() is False


def test_graba_episodios(tele, tmp_path):
    r = tele.recibir({"type": "cmd", "cmd": "grabar", "tarea": "demo"})
    assert r["type"] == "grabando"
    tele.recibir(manos())
    for _ in range(5):
        tele.paso()
    r = tele.recibir({"type": "cmd", "cmd": "parar"})
    assert r["meta"]["tramas"] == 5
    carpeta = next(tmp_path.iterdir())
    lineas = (carpeta / "tramas.jsonl").read_text().splitlines()
    assert len(lineas) == 5 and "qpos" in json.loads(lineas[0])["obs"]


def test_correr_exige_modo_correcto(cfg, alertas):
    from andamio.nucleo.seguridad import Seguridad
    requiere_modelo()
    robot = RobotSim(cfg, alertas)
    robot.conectar()
    seg = Seguridad(robot, alertas, cfg, True)
    t = Teleop(robot, seg, alertas, cfg)
    with pytest.raises(ErrorSeguridad):
        t.correr(0.1)


def test_websocket_de_punta_a_punta(tele):
    import websockets

    hilo = threading.Thread(target=tele.correr, args=(4.0,), daemon=True)
    hilo.start()
    recibidos = []

    async def cliente():
        for _ in range(50):
            try:
                ws = await websockets.connect(f"ws://127.0.0.1:{tele.puerto}/?pin={tele.pin}")
                break
            except OSError:
                await asyncio.sleep(0.1)
        async with ws:
            recibidos.append(json.loads(await ws.recv()))
            await ws.send(json.dumps(manos()))
            await ws.send(json.dumps({"type": "cmd", "cmd": "calibrar"}))
            await ws.send(json.dumps({"type": "cmd", "cmd": "nada"}))
            vistos = set()
            fin = time.monotonic() + 2
            while time.monotonic() < fin and not {"estado", "aviso", "error"} <= vistos:
                m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                recibidos.append(m)
                vistos.add(m["type"])

    asyncio.run(cliente())
    tele.detener()
    hilo.join(5)
    tipos = {m["type"] for m in recibidos}
    assert {"hola", "estado", "aviso", "error"} <= tipos
    hola = recibidos[0]
    assert "right" in hola["efectores"] and hola["hz"] == 50
    est = next(m for m in recibidos if m["type"] == "estado")
    assert len(est["p"]) == len(hola["bodies"]) and len(est["q"][0]) == 4


def test_puerto_ocupado_se_informa(tele, alertas):
    s = socket.socket()
    s.bind(("0.0.0.0", tele.puerto))
    s.listen()
    try:
        t0 = time.monotonic()
        tele.correr(3.0)
        assert time.monotonic() - t0 < 2.5
        assert alertas.hubo("error")
    finally:
        s.close()


def _conectar(tele, query):
    import websockets

    async def f():
        for _ in range(50):
            try:
                ws = await websockets.connect(f"ws://127.0.0.1:{tele.puerto}/{query}")
                break
            except OSError:
                await asyncio.sleep(0.1)
        try:
            return json.loads(await asyncio.wait_for(ws.recv(), 2))["type"]
        except Exception as e:
            return type(e).__name__
        finally:
            await ws.close()

    return asyncio.run(f())


def test_pin_incorrecto_o_ausente_se_rechaza(tele):
    hilo = threading.Thread(target=tele.correr, args=(3.0,), daemon=True)
    hilo.start()
    assert _conectar(tele, "") == "ConnectionClosedError"
    assert _conectar(tele, "?pin=mal") == "ConnectionClosedError"
    assert _conectar(tele, f"?pin={tele.pin}") == "hola"
    tele.detener()
    hilo.join(5)


def test_un_solo_visor_a_la_vez(tele):
    import websockets
    hilo = threading.Thread(target=tele.correr, args=(4.0,), daemon=True)
    hilo.start()

    async def f():
        for _ in range(50):
            try:
                a = await websockets.connect(f"ws://127.0.0.1:{tele.puerto}/?pin={tele.pin}")
                break
            except OSError:
                await asyncio.sleep(0.1)
        await a.recv()
        b = await websockets.connect(f"ws://127.0.0.1:{tele.puerto}/?pin={tele.pin}")
        try:
            await asyncio.wait_for(b.recv(), 2)
            return "acepto"
        except websockets.exceptions.ConnectionClosed:
            return "rechazado"
        finally:
            await a.close()

    assert asyncio.run(f()) == "rechazado"
    tele.detener()
    hilo.join(5)


def test_fijar_inicio_parte_de_la_pose_de_la_plantilla(tele):
    q = tele.q_cmd["derecha"] + 0.1
    tele.fijar_inicio(None, q)
    assert np.allclose(tele.q_cmd["derecha"], tele.objetivo_q["derecha"])
    assert not tele.anclas
    tele.fijar_inicio(None, [float("nan")] * len(q))      # se ignora
    assert np.all(np.isfinite(tele.q_cmd["derecha"]))
