"""Leer una linea de la terminal sin bloquear para siempre, en Mac/Linux (select) y en Windows (msvcrt)."""
import os
import sys
import time

_buffer = []


def leer_linea(timeout):
    """Devuelve la linea escrita (sin salto) o None si no se termino ninguna antes de `timeout` segundos."""
    if sys.stdin is None:
        time.sleep(min(timeout, 0.2))
        return None
    try:
        interactiva = sys.stdin.isatty()
    except Exception:
        interactiva = False
    if not interactiva:
        time.sleep(min(timeout, 0.2))
        return None
    if os.name == "nt":
        return _windows(timeout)
    import select
    listo, _, _ = select.select([sys.stdin], [], [], timeout)
    if listo:
        return sys.stdin.readline().rstrip("\r\n")
    return None


def _windows(timeout):
    import msvcrt
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        while msvcrt.kbhit():
            c = msvcrt.getwche()
            if c in ("\r", "\n"):
                msvcrt.putwch("\n")
                linea = "".join(_buffer)
                _buffer.clear()
                return linea
            if c == "\b":
                if _buffer:
                    _buffer.pop()
                    msvcrt.putwch(" ")
                    msvcrt.putwch("\b")
            else:
                _buffer.append(c)
        time.sleep(0.03)
    return None
