"""Comprobaciones de numeros que llegan de plantillas, red, voz o configuracion."""
import math

from .errores import ErrorSeguridad


def finito(valor, nombre="valor"):
    """Devuelve float(valor) o levanta ErrorSeguridad si no es un numero finito (NaN, inf, texto, None, bool)."""
    if isinstance(valor, bool):
        raise ErrorSeguridad(f"{nombre} no es un numero: {valor!r}")
    try:
        v = float(valor)
    except (TypeError, ValueError):
        raise ErrorSeguridad(f"{nombre} no es un numero: {valor!r}")
    if not math.isfinite(v):
        raise ErrorSeguridad(f"{nombre} no es un numero finito: {valor!r}")
    return v


def lista_finita(valores, n, nombre="valores"):
    try:
        lista = list(valores)
    except TypeError:
        raise ErrorSeguridad(f"{nombre} debe ser una lista de {n} numeros")
    if len(lista) != n:
        raise ErrorSeguridad(f"{nombre} necesita {n} valores y llegaron {len(lista)}")
    return [finito(v, f"{nombre}[{i}]") for i, v in enumerate(lista)]
