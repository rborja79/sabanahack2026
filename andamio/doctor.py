"""Diagnostico: revisa el entorno y dice que arreglar.

    python -m andamio.doctor                 # revision general
    python -m andamio.doctor --robot x2      # agrega red, ROS y SDK del X2
    python -m andamio.doctor --probar-claude # hace una llamada real al modelo de voz (cuesta centavos)
"""
import argparse
import importlib
import json
import os
import pathlib
import platform
import shutil
import socket
import subprocess
import sys

from . import config as _config
from .aplicacion import cargar_env

OK, AVISO, FALLO = "OK", "AVISO", "FALLO"


class Informe:
    def __init__(self):
        self.filas = []

    def agregar(self, nivel, nombre, detalle="", pista=""):
        self.filas.append({"nivel": nivel, "nombre": nombre, "detalle": detalle, "pista": pista})

    @property
    def fallos(self):
        return [f for f in self.filas if f["nivel"] == FALLO]


def _tcp(host, puerto, espera=1.5):
    try:
        with socket.create_connection((host, puerto), timeout=espera):
            return True
    except OSError:
        return False


def _ping(host):
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", "1000", host]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", host]
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return None


def _modulo(inf, nombre, importar=None, requerido=True, pista=""):
    try:
        m = importlib.import_module(importar or nombre)
        inf.agregar(OK, f"python: {nombre}", getattr(m, "__version__", ""))
        return m
    except ImportError:
        inf.agregar(FALLO if requerido else AVISO, f"python: {nombre}", "no instalado", pista or f"pip install {nombre}")
        return None


def revisar(robot="general", probar_claude=False, cfg=None):
    cargar_env()
    cfg = cfg or _config.cargar()
    inf = Informe()

    v = sys.version_info
    inf.agregar(OK if v >= (3, 9) else FALLO, "python", f"{v.major}.{v.minor}.{v.micro} en {platform.system()} {platform.machine()}",
                "se necesita Python 3.9 o mas")
    _modulo(inf, "pyyaml", "yaml", pista="pip install pyyaml")
    _modulo(inf, "numpy")
    mj = _modulo(inf, "mujoco", requerido=robot in ("sim", "x2", "x2sim", "remoto"), pista="pip install mujoco")
    _modulo(inf, "websockets", requerido=False, pista="pip install websockets (necesario para el visor de las gafas)")
    ant = _modulo(inf, "anthropic", requerido=False, pista="pip install anthropic (sin el, la voz usa solo palabras clave)")

    # modelo cinematico
    try:
        from .robots.sim_mujoco import buscar_modelo
        from .cinematica import Modelo
        ruta = buscar_modelo()
        if mj is not None:
            m = Modelo(ruta)
            n = {l: len(c) for l, c in m.cadenas.items()}
            ok = all(v == 7 for v in n.values())
            inf.agregar(OK if ok else AVISO, "modelo del robot", f"{pathlib.Path(ruta).name}: brazos {n}",
                        "" if ok else "el X2 tiene 7 articulaciones por brazo; revisa que sea el MJCF correcto")
    except Exception as e:
        inf.agregar(AVISO, "modelo del robot", str(e), getattr(e, "pista", "") or "copia el MJCF del X2 en robots/")

    # voz
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if clave:
        inf.agregar(OK, "clave de Claude", "definida (ANTHROPIC_API_KEY)")
        if probar_claude and ant is not None:
            try:
                c = ant.Anthropic(timeout=float(cfg["voz"]["timeout_s"]), max_retries=0)
                c.messages.create(model=cfg["voz"]["modelo"], max_tokens=5, messages=[{"role": "user", "content": "hola"}])
                inf.agregar(OK, "modelo de voz", f"{cfg['voz']['modelo']} responde")
            except Exception as e:
                inf.agregar(FALLO, "modelo de voz", f"{cfg['voz']['modelo']}: {e}",
                            "cambia voz.modelo en config.yaml (ANDAMIO_VOZ__MODELO) por un modelo disponible en tu cuenta")
    else:
        inf.agregar(AVISO, "clave de Claude", "no hay ANTHROPIC_API_KEY", "ponla en .env; sin ella la voz usa palabras clave")
    inf.agregar(OK if _tcp("api.anthropic.com", 443, 3) else AVISO, "internet (api.anthropic.com)",
                "", "sin internet la voz funciona con palabras clave")
    try:
        import sounddevice as sd
        entradas = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        inf.agregar(OK if entradas else AVISO, "microfono", f"{len(entradas)} entrada(s)", "" if entradas else "conecta un microfono o usa --oido panel")
    except Exception:
        inf.agregar(AVISO, "microfono", "sounddevice no disponible", "usa --oido panel (microfono del navegador) o pip install sounddevice faster-whisper")

    # seguridad
    s = cfg["seguridad"]
    inf.agregar(OK if s["bateria_min"] >= 50 else AVISO, "limite de bateria", f"{s['bateria_min']}%", "el evento exige bateria sobre 50%")
    inf.agregar(OK if s["vx_max"] <= 0.5 else AVISO, "velocidad maxima", f"vx {s['vx_max']} m/s", "para pruebas iniciales usa 0.4 o menos")
    try:
        d = pathlib.Path(__file__).resolve().parents[1] / "datos"
        d.mkdir(exist_ok=True)
        (d / ".prueba").write_text("x")
        (d / ".prueba").unlink()
        inf.agregar(OK, "carpeta datos/", "se puede escribir")
    except OSError as e:
        inf.agregar(FALLO, "carpeta datos/", str(e), "las grabaciones no se podran guardar")

    if robot == "x2sim":
        inf.agregar(OK if platform.machine() in ("x86_64", "AMD64") else FALLO, "procesador x86_64",
                    platform.machine(), "el simulador oficial de AgiBot solo corre en x86_64 (no en Mac Apple Silicon)")
        pantalla = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        inf.agregar(OK if pantalla else AVISO, "pantalla para la ventana de MuJoCo", pantalla or "sin DISPLAY",
                    "en WSL2 hace falta Windows 11 (WSLg); comprueba con: echo $DISPLAY")
        carpeta = pathlib.Path(os.environ.get("X2_SIM", str(pathlib.Path.home() / "x2_simulation")))
        faltan = [d for d in ("aimdk", "sim_mujoco", "mc") if not (carpeta / d).is_dir()]
        inf.agregar(OK if not faltan else FALLO, f"simulador oficial en {carpeta}", "completo" if not faltan else f"faltan {faltan}",
                    "corre ./andamio/instalar/sim_oficial.sh preparar CARPETA_CON_LO_DESCARGADO")
        inf.agregar(OK if pathlib.Path("/agibot/data/var").is_dir() else FALLO, "/agibot/data/var", "",
                    "sudo mkdir -p /agibot/data/var && sudo chown $USER -R /agibot")
        en_marcha = subprocess.run(["tmux", "has-session", "-t", "x2sim"], capture_output=True).returncode == 0 \
            if shutil.which("tmux") else False
        inf.agregar(OK if en_marcha else AVISO, "simulador y control de movimiento", "corriendo" if en_marcha else "apagados",
                    "./andamio/instalar/sim_oficial.sh iniciar")
    if robot in ("x2", "x2sim"):
        x = cfg["x2"]
        if robot == "x2":
            r = _ping(x["ip_dev"])
            inf.agregar(OK if r else (AVISO if r is None else FALLO), f"red: unidad de desarrollo {x['ip_dev']}",
                        "responde" if r else "no responde",
                        "cable Gigabit al robot, tu IP 10.0.1.2/24 (en WSL2 usa red espejo); el Wi-Fi solo para depurar")
        inf.agregar(OK if shutil.which("ros2") else AVISO, "ROS 2 (ros2)", "", "source /opt/ros/humble/setup.bash")
        inf.agregar(OK if os.environ.get("RMW_IMPLEMENTATION") == "rmw_fastrtps_cpp" else AVISO, "RMW_IMPLEMENTATION",
                    os.environ.get("RMW_IMPLEMENTATION", "(sin definir)"), "export RMW_IMPLEMENTATION=rmw_fastrtps_cpp")
        try:
            importlib.import_module("rclpy")
            importlib.import_module("aimdk_msgs")
            inf.agregar(OK, "SDK AimDK (aimdk_msgs)", "importa")
        except ImportError as e:
            inf.agregar(FALLO, "SDK AimDK (aimdk_msgs)", f"falta {e.name}",
                        "compila el SDK en esta maquina o en el contenedor (colcon build) y haz source install/local_setup.bash; "
                        "o usa --robot remoto contra un servidor corriendo junto al robot")
        if robot == "x2" and _ping(x["ip_mc"]):
            inf.agregar(AVISO, f"PC1 {x['ip_mc']}", "alcanzable", "no se desarrolla ni se ejecuta nada en PC1")
    if robot == "d1":
        d1 = cfg["d1"]
        r = _ping(d1["ip_robot"])
        inf.agregar(OK if r else (AVISO if r is None else FALLO), f"red: D1 {d1['ip_robot']}", "responde" if r else "no responde",
                    f"tu IP debe ser {d1['ip_local']} en la red del robot")
        raiz = d1["sdk"] or os.environ.get("D1_SDK", "")
        arq = platform.machine().replace("amd64", "x86_64").replace("arm64", "aarch64")
        lib = pathlib.Path(raiz) / "lib" / "zsl-1" / arq if raiz else None
        if lib and lib.is_dir():
            inf.agregar(OK, "SDK del D1", str(lib))
        else:
            inf.agregar(FALLO, "SDK del D1", "no se encuentra", "d1.sdk (o D1_SDK) debe ser la carpeta con lib/ del SDK; solo Linux, Python 3.10")
        inf.agregar(OK if v[:2] == (3, 10) else AVISO, "python 3.10 para el SDK del D1", f"{v.major}.{v.minor}", "la libreria .so es para CPython 3.10")
    if robot == "remoto":
        r = cfg["remoto"]
        okp = _tcp(r["host"], int(r["puerto"]))
        inf.agregar(OK if okp else FALLO, f"servidor del robot {r['host']}:{r['puerto']}", "acepta conexiones" if okp else "no responde",
                    "arranca python -m andamio.servidor_robot dentro del contenedor y publica el puerto")
        inf.agregar(OK if (r["token"] or os.environ.get("ANDAMIO_TOKEN")) else FALLO, "token del servidor", "",
                    "define ANDAMIO_TOKEN (igual en los dos lados)")
    return inf


def imprimir(inf):
    color = {OK: "\033[32m", AVISO: "\033[33m", FALLO: "\033[31m"}
    tty = sys.stdout.isatty()
    for f in inf.filas:
        n = f"{color[f['nivel']]}{f['nivel']:<5}\033[0m" if tty else f"{f['nivel']:<5}"
        print(f"{n}  {f['nombre']}" + (f"  - {f['detalle']}" if f["detalle"] else ""))
        if f["pista"] and f["nivel"] != OK:
            print(f"       -> {f['pista']}")
    print(f"\n{len(inf.fallos)} fallo(s), {sum(1 for f in inf.filas if f['nivel'] == AVISO)} aviso(s)")


def principal(argv=None):
    ap = argparse.ArgumentParser(prog="python -m andamio.doctor")
    ap.add_argument("--robot", default="general", choices=["general", "sim", "x2", "x2sim", "d1", "remoto"])
    ap.add_argument("--probar-claude", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    inf = revisar(a.robot, a.probar_claude)
    if a.json:
        print(json.dumps(inf.filas, ensure_ascii=False, indent=1))
    else:
        imprimir(inf)
    return 1 if inf.fallos else 0


if __name__ == "__main__":
    sys.exit(principal())
