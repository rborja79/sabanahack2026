"""Grafo de modos y ruta para llegar de uno a otro.

El manual del X2 dice que los cambios de modo siguen un diagrama de transiciones y que
los otros se rechazan, pero el diagrama esta en una imagen. Este grafo es una suposicion
razonable basada en los ejemplos (cero torque -> fijo -> estable -> caminar). Si el robot
rechaza un paso, el driver lo avisa; ajusta GRAFO si el diagrama real es distinto.
"""
from collections import deque

GRAFO = {
    "pasivo": {"amortiguado", "fijo"},
    "amortiguado": {"pasivo", "fijo"},
    "fijo": {"pasivo", "amortiguado", "estable"},
    "estable": {"fijo", "amortiguado", "caminar", "cabeza", "tren_superior"},
    "caminar": {"estable"},
    "cabeza": {"estable"},
    "tren_superior": {"estable"},
}

# lo que pasa antes de entrar a estos modos y requiere un humano mirando
REQUIEREN_CONFIRMACION = {
    "estable": "confirma que el robot esta de pie con los pies en el suelo",
    "pasivo": "confirma que el robot esta colgado del gancho o sostenido: sin fuerza en los motores se cae",
    "amortiguado": "confirma que el robot esta colgado del gancho o sostenido: con los motores blandos puede caerse",
}


def ruta(origen, destino, grafo=None):
    """Lista de modos a recorrer, sin incluir el origen. Vacia si ya esta en destino."""
    grafo = grafo or GRAFO
    if origen == destino:
        return []
    if origen not in grafo or destino not in grafo:
        raise KeyError(f"modo desconocido: {origen!r} -> {destino!r}")
    cola = deque([[origen]])
    visto = {origen}
    while cola:
        camino = cola.popleft()
        for vecino in sorted(grafo[camino[-1]]):
            if vecino in visto:
                continue
            nuevo = camino + [vecino]
            if vecino == destino:
                return nuevo[1:]
            visto.add(vecino)
            cola.append(nuevo)
    raise KeyError(f"no hay ruta de {origen!r} a {destino!r}")
