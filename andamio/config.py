"""Configuracion con valores por defecto, un archivo opcional y variables de entorno.

Orden de prioridad: variables de entorno > archivo config.yaml > valores por defecto.
Las variables de entorno usan el formato ANDAMIO_SECCION__CLAVE=valor, por ejemplo
ANDAMIO_X2__IP_DEV=10.0.1.41
"""
import copy
import math
import os
import pathlib

try:
    import yaml
except ImportError:  # el nucleo funciona sin yaml solo para configuracion
    yaml = None

from .nucleo.errores import ErrorConfiguracion

RAIZ = pathlib.Path(__file__).resolve().parent

DEFECTO = {
    "seguridad": {
        "vx_max": 0.4,           # m/s, el robot admite hasta 1.0 en el X2
        "vy_max": 0.3,
        "wz_max": 0.6,           # rad/s
        "bateria_min": 50,       # el evento pide mas de 50%
        "bateria_critica": 30,   # por debajo se detiene todo
        "hz_control": 50,        # el robot se frena si pasan 200 ms sin ordenes
        "fallos_seguidos": 3,    # envios fallidos antes de parar
        "emergencia": "detener", # detener | amortiguar (amortiguar puede tumbar un humanoide)
        "vigilar_cada_s": 1.0,
        "confirmar_pies": True,
    },
    "x2": {
        "ip_dev": "10.0.1.41",
        "ip_mc": "10.0.1.40",        # no se desarrolla ni se ejecuta aqui
        "fuente": "node.andamio",
        "prioridad": 40,
        "timeout_ms": 1000,
        "modelo": "ultra_n",         # ultra (v1.3.0) | ultra_n (v1.4.0) | edu
        "manos_via": "mc",           # mc (tren superior) | hal (requiere detener el modulo mc)
        "espera_modo_s": 12,
        "modelo_xml": "",            # MJCF para limites articulares; vacio = buscar en robots/
        "vel_brazo": 0.8,            # rad/s maximos de cada articulacion de los brazos
        "vel_cabeza": 1.0,
        "cabeza_yaw_max": 1.0,       # rad, si el modelo no da limites
        "cabeza_pitch_max": 0.5,
        "mano_cierre_factor": 0.8,   # fraccion del "doble de la mitad" que se usa como mano cerrada
    },
    "d1": {
        "ip_robot": "192.168.234.1",
        "ip_local": "192.168.234.15",
        "puerto": 43988,
        "sdk": "",                   # carpeta del SDK descomprimido (la que tiene lib/)
        "acrobacias": False,
    },
    "remoto": {
        "host": "10.0.1.41",
        "puerto": 8790,
        "token": "",
        "timeout_s": 4.0,
    },
    "sim": {"modelo": ""},
    "vision": {
        "ojo": "ninguno",        # ninguno | camara | simulado | x2 | remoto (o --ojo en la linea de comandos)
        "camara": 0,             # indice de la webcam (0 = la del portatil)
        "fov_h": 70.0,           # campo de vision horizontal en grados (webcam ~70; ajusta para el X2)
        "hz": 8.0,               # detecciones por segundo como maximo
        "confianza": 0.45,       # minimo para aceptar una deteccion
        "modelo": "",            # vacio = vision/modelos/yolo11n.onnx del repo
        "topico_color": "/aima/hal/sensor/rgbd_head_front/rgb_image/compressed",
        "topico_profundidad": "/aima/hal/sensor/rgbd_head_front/depth_image",
        "escala_profundidad": 0.001,   # 16UC1 en milimetros -> metros (sin verificar en el X2)
        "objetivos_simulados": [{"clase": "persona", "x": 3.0, "y": 1.5}],
    },
    "voz": {
        "modelo": "claude-haiku-4-5",
        "oido": "texto",             # texto | panel | whisper
        "timeout_s": 6.0,
        "idioma": "es",
    },
    "panel": {"host": "127.0.0.1", "puerto": 8780},
    "teleop": {"host": "0.0.0.0", "puerto": 8765, "suavizado": 0.25, "vel_art_max": 1.5, "escala": 1.0,
               "pin": "", "fallos_seguidos": 25},   # pin vacio = se genera uno cada vez
}


def _mezclar(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _mezclar(base[k], v)
        else:
            base[k] = v
    return base


def _convertir(texto, ejemplo):
    if isinstance(ejemplo, bool):
        return texto.strip().lower() in ("1", "true", "si", "yes", "on")
    if isinstance(ejemplo, int):
        return int(texto)
    if isinstance(ejemplo, float):
        return float(texto)
    return texto


def cargar(ruta=None, entorno=None):
    cfg = copy.deepcopy(DEFECTO)
    ruta = pathlib.Path(ruta) if ruta else RAIZ / "config.yaml"
    if ruta.exists() and yaml is not None:
        with open(ruta, encoding="utf-8") as fh:
            _mezclar(cfg, yaml.safe_load(fh) or {})
    entorno = os.environ if entorno is None else entorno
    for clave, valor in entorno.items():
        if not clave.startswith("ANDAMIO_") or "__" not in clave:
            continue
        seccion, _, campo = clave[len("ANDAMIO_"):].lower().partition("__")
        if seccion not in cfg or campo not in cfg[seccion]:
            raise ErrorConfiguracion(f"variable desconocida: {clave}",
                                     pista="el formato es ANDAMIO_SECCION__CLAVE; mira andamio/config.yaml.ejemplo")
        try:
            cfg[seccion][campo] = _convertir(valor, cfg[seccion][campo])
        except ValueError:
            raise ErrorConfiguracion(f"{clave}={valor!r} no es un valor valido", pista="revisa el tipo del valor")
    _validar(cfg)
    return cfg


def _numero(cfg, seccion, clave, minimo, maximo, estricto_min=False):
    v = cfg[seccion][clave]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ErrorConfiguracion(f"{seccion}.{clave} debe ser un numero finito y es {v!r}",
                                 pista="revisa config.yaml y las variables ANDAMIO_*")
    if v < minimo or v > maximo or (estricto_min and v == minimo):
        raise ErrorConfiguracion(f"{seccion}.{clave}={v} fuera de rango ({minimo} a {maximo})",
                                 pista="revisa config.yaml y las variables ANDAMIO_*")


def _validar(cfg):
    for k in ("vx_max", "vy_max"):
        _numero(cfg, "seguridad", k, 0.0, 3.0, True)
    _numero(cfg, "seguridad", "wz_max", 0.0, 3.0, True)
    _numero(cfg, "seguridad", "bateria_min", 0, 100)
    _numero(cfg, "seguridad", "bateria_critica", 0, 100)
    _numero(cfg, "seguridad", "hz_control", 5, 200)
    _numero(cfg, "seguridad", "fallos_seguidos", 1, 100)
    _numero(cfg, "seguridad", "vigilar_cada_s", 0.01, 10)
    if cfg["seguridad"]["bateria_critica"] >= cfg["seguridad"]["bateria_min"]:
        raise ErrorConfiguracion("seguridad.bateria_critica debe ser menor que bateria_min")
    if cfg["seguridad"]["emergencia"] not in ("detener", "amortiguar"):
        raise ErrorConfiguracion("seguridad.emergencia debe ser 'detener' o 'amortiguar'")
    _numero(cfg, "x2", "vel_brazo", 0.0, 3.0, True)
    _numero(cfg, "x2", "vel_cabeza", 0.0, 3.0, True)
    _numero(cfg, "x2", "mano_cierre_factor", 0.0, 1.0, True)
    _numero(cfg, "teleop", "vel_art_max", 0.0, 3.0, True)
    _numero(cfg, "teleop", "suavizado", 0.0, 1.0, True)
    _numero(cfg, "teleop", "escala", 0.0, 3.0, True)
    _numero(cfg, "vision", "fov_h", 20.0, 180.0)
    _numero(cfg, "vision", "hz", 0.5, 60.0)
    _numero(cfg, "vision", "confianza", 0.05, 0.99)
    _numero(cfg, "vision", "escala_profundidad", 0.0, 10.0, True)
    if cfg["vision"]["ojo"] not in ("ninguno", "camara", "simulado", "x2", "remoto"):
        raise ErrorConfiguracion("vision.ojo debe ser ninguno, camara, simulado, x2 o remoto")
