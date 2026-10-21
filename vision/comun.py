"""Piezas compartidas por los modulos de vision."""
import json
import numpy as np

# Caja de trabajo frente al robot, en metros. La imagen se mapea aqui dentro.
CAJA = {"x": (-0.45, 0.45), "y": (0.15, 0.55), "z": (0.75, 1.45)}


def interp(v, a, b):
    """Lleva v, que va de 0 a 1, al rango [a, b]."""
    return float(a + (b - a) * float(np.clip(v, 0.0, 1.0)))


def imagen_a_robot(u, v, cerca, caja=CAJA):
    """Pasa un punto normalizado de la imagen al marco del robot.

    u y v van de 0 a 1 sobre el ancho y el alto de la imagen, con el origen
    arriba a la izquierda. cerca va de 0 (lejos) a 1 (pegado a la camara).
    """
    return [round(interp(1.0 - u, *caja["x"]), 4),
            round(interp(cerca, *caja["y"]), 4),
            round(interp(1.0 - v, *caja["z"]), 4)]


def camara_por_defecto(ancho, alto):
    """Matriz intrinseca aproximada cuando no hay calibracion."""
    f = 0.9 * max(ancho, alto)
    return np.array([[f, 0, ancho / 2], [0, f, alto / 2], [0, 0, 1]], float)


def cargar_calibracion(ruta):
    """Lee K y los coeficientes de distorsion de un JSON de calibracion."""
    with open(ruta) as f:
        d = json.load(f)
    return np.asarray(d["K"], float), np.asarray(d.get("dist", [0] * 5), float)


class Suavizado:
    """Filtro exponencial para que el objetivo no tiemble."""

    def __init__(self, alfa=0.35):
        self.alfa = alfa
        self.valor = None

    def __call__(self, p):
        p = np.asarray(p, float)
        self.valor = p if self.valor is None else self.alfa * p + (1 - self.alfa) * self.valor
        return self.valor.tolist()
