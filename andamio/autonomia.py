"""Comportamientos autonomos (nivel 1, reactivos): mirar -> decidir -> actuar, varias veces por segundo.

  mirar      una foto: guarda que se ve (para usar en 'si')
  buscar     gira en el sitio hasta ver el objeto y lo deja centrado
  acercarse  camina hacia el objeto corrigiendo el rumbo hasta quedar a cierta distancia

Reglas de seguridad propias, ademas de las de siempre (limites, PARAR, bateria, modos):
  * la velocidad caduca sola en 0,35 s si el ciclo se cuelga (hombre muerto);
  * si deja de ver el objeto mas de `perdido_s` segundos, frena y falla;
  * tiempo maximo por paso (`max_s`);
  * no avanza si el objeto no esta mas o menos al frente, ni si no sabe la distancia;
  * nunca se acerca a menos de `distancia_min` (0,5 m por defecto), aunque la plantilla pida menos.
"""
import math
import time

from .nucleo.errores import ErrorAndamio, ErrorPlantilla, NoSoportado

HZ = 10
DISTANCIA_MIN = 0.5


class NoEncontrado(ErrorAndamio):
    """El comportamiento no logro su objetivo (no vio el objeto, lo perdio o se acabo el tiempo)."""


def _ojo(ctx):
    if ctx.ojo is None:
        raise NoSoportado("este paso necesita un ojo (camara)",
                          pista="agrega --ojo camara (webcam), --ojo simulado, o --ojo x2 / remoto con el robot")
    return ctx.ojo


def _num(a, clave, defecto, lo=None, hi=None):
    v = a.get(clave, defecto)
    if isinstance(v, bool):
        raise ErrorPlantilla(f"'{clave}' debe ser un numero")
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ErrorPlantilla(f"'{clave}' debe ser un numero y llego {v!r}")
    if not math.isfinite(v) or (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ErrorPlantilla(f"'{clave}' fuera de rango: {v} (va de {lo} a {hi})")
    return v


def _mejor(ojo, clase, minimo):
    dets = ojo.ver(clase, minimo)
    if not dets:
        return None
    # el mas cercano si se sabe la distancia; si no, el de mayor confianza
    con_d = [d for d in dets if d.get("distancia")]
    return min(con_d, key=lambda d: d["distancia"]) if con_d else dets[0]


def _lado(cx):
    return "izquierda" if cx < -0.2 else "derecha" if cx > 0.2 else "centro"


def _giro(cx, seg, ganancia=1.0, tol=0.12):
    """Velocidad de giro para centrar: cx>0 (a la derecha) => wz<0. Con zona muerta, para no oscilar
    alrededor del minimo que acepta el robot."""
    if abs(cx) < tol:
        return 0.0
    wz_max = min(seg.cfg["wz_max"], seg.robot.vel_max[2])
    wz = -ganancia * cx * wz_max
    minimo = seg.robot.vel_min[2]
    if abs(wz) < minimo:
        wz = math.copysign(minimo, wz)
    return max(-wz_max, min(wz_max, wz))


def _decidir(ojo, texto, alertas=None):
    ojo.decision = texto
    clave = texto.split("(")[0].strip()
    if alertas is not None and clave != getattr(ojo, "_ultima_decision", None):
        ojo._ultima_decision = clave
        alertas.info(f"autonomia: {texto}")


def _frenar(seg):
    seg.detener()
    time.sleep(min(0.2, seg.control.periodo * 4))      # deja salir los ceros antes de seguir


def mirar(ctx, a):
    a = a or {}
    ojo = _ojo(ctx)
    clase = a.get("objeto")
    minimo = _num(a, "confianza", ctx.cfg.get("vision", {}).get("confianza", 0.45), 0, 1)
    time.sleep(0.3)                                   # deja llegar un cuadro fresco
    d = _mejor(ojo, clase, minimo)
    visto = {"n": len(ojo.ver(clase, minimo)), "visto": d is not None,
             "distancia": (d or {}).get("distancia") or -1, "lado": _lado(d["cx"]) if d else "ninguno",
             "clase": (d or {}).get("clase", "")}
    ctx.variables[str(a.get("guardar_en", "visto"))] = visto
    ctx.alertas.info(f"mirar: {'veo ' + visto['clase'] + ' a la ' + visto['lado'] if d else 'no veo ' + (clase or 'nada')}"
                     + (f" a {visto['distancia']:.1f} m" if d and visto["distancia"] > 0 else ""))
    return visto


def buscar(ctx, a):
    a = a or {}
    ojo, seg = _ojo(ctx), ctx.seguridad
    clase = a.get("objeto", "persona")
    minimo = _num(a, "confianza", ctx.cfg.get("vision", {}).get("confianza", 0.45), 0, 1)
    max_s = _num(a, "max_s", 25, 1, 120)
    wz = abs(_num(a, "wz", 0.3, 0.05, 2.0))
    sentido = str(a.get("sentido", "izquierda"))
    if sentido not in ("izquierda", "derecha"):
        raise ErrorPlantilla("'sentido' debe ser izquierda o derecha")
    wz = wz if sentido == "izquierda" else -wz
    seguidos, t0 = 0, time.monotonic()
    try:
        while True:
            if time.monotonic() - t0 > max_s:
                raise NoEncontrado(f"no encontre '{clase}' en {max_s:.0f} s",
                                   pista="mejora la luz, acercate, baja 'confianza' o sube 'max_s'")
            d = _mejor(ojo, clase, minimo)
            seguidos = seguidos + 1 if d else 0
            if d and seguidos >= 3:
                if abs(d["cx"]) < 0.15:
                    seg.mover_continuo(0, 0, 0)
                    _decidir(ojo, f"encontre {clase} al frente" +
                             (f" a {d['distancia']:.1f} m" if d.get("distancia") else ""), ctx.alertas)
                    return d
                giro = _giro(d["cx"], seg)
                _decidir(ojo, f"centrando {clase} ({_lado(d['cx'])})", ctx.alertas)
                seg.mover_continuo(0, 0, giro)
            elif d:
                seg.mover_continuo(0, 0, 0)             # lo vi: espera a confirmarlo antes de seguir girando
                _decidir(ojo, f"creo ver {clase}...", ctx.alertas)
            else:
                _decidir(ojo, f"buscando {clase}: giro a la {sentido}", ctx.alertas)
                seg.mover_continuo(0, 0, wz)
            time.sleep(1.0 / HZ)
    finally:
        _frenar(seg)


def acercarse(ctx, a):
    a = a or {}
    ojo, seg = _ojo(ctx), ctx.seguridad
    clase = a.get("objeto", "persona")
    minimo = _num(a, "confianza", ctx.cfg.get("vision", {}).get("confianza", 0.45), 0, 1)
    objetivo = max(DISTANCIA_MIN, _num(a, "distancia", 1.0, 0, 10))
    vx_max = _num(a, "vx", 0.3, 0.05, 1.0)
    max_s = _num(a, "max_s", 30, 1, 120)
    perdido_s = _num(a, "perdido_s", 1.5, 0.2, 10)
    t0 = time.monotonic()
    ultimo_visto = time.monotonic()
    sin_distancia = 0
    try:
        while True:
            ahora = time.monotonic()
            if ahora - t0 > max_s:
                raise NoEncontrado(f"no llegue a '{clase}' en {max_s:.0f} s", pista="sube 'max_s' o acercate tu")
            d = _mejor(ojo, clase, minimo)
            if d is None:
                seg.mover_continuo(0, 0, 0)
                if ahora - ultimo_visto > perdido_s:
                    raise NoEncontrado(f"perdi de vista a '{clase}'",
                                       pista="usa un paso 'buscar' antes, o sube 'perdido_s'")
                _decidir(ojo, f"no veo {clase}, espero", ctx.alertas)
                time.sleep(1.0 / HZ)
                continue
            ultimo_visto = ahora
            dist = d.get("distancia")
            if not dist:
                sin_distancia += 1
                seg.mover_continuo(0, 0, _giro(d["cx"], seg))
                if sin_distancia > 3 * HZ:
                    raise NoEncontrado(f"veo '{clase}' pero no se a que distancia esta",
                                       pista="este objeto no tiene tamano conocido; usa la camara con profundidad (x2)")
                time.sleep(1.0 / HZ)
                continue
            sin_distancia = 0
            if dist <= objetivo:
                seg.mover_continuo(0, 0, 0)
                _decidir(ojo, f"llegue: {clase} a {dist:.1f} m", ctx.alertas)
                return d
            wz = _giro(d["cx"], seg)
            if abs(d["cx"]) < 0.35:
                vx = min(vx_max, max(seg.robot.vel_min[0], 0.6 * (dist - objetivo)))
            else:
                vx = 0.0                                 # primero me giro, luego avanzo
            _decidir(ojo, (f"avanzando hacia {clase} ({dist:.1f} m)" if vx else f"girando hacia {clase} ({_lado(d['cx'])})"),
                     ctx.alertas)
            seg.mover_continuo(vx, 0, wz)
            time.sleep(1.0 / HZ)
    finally:
        _frenar(seg)
