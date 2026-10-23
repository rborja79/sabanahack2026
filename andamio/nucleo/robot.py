"""Interfaz comun de robot.

Todas las plantillas hablan con esta interfaz. Cada robot (falso, simulado, X2, D1,
remoto) la implementa. Lo que no soporte lo declara con NoSoportado.

Modos comunes (cada robot los traduce a los suyos):
    pasivo        motores sin fuerza (cero torque). El robot se cae si nadie lo sostiene.
    amortiguado   articulaciones con resistencia.
    fijo          de pie con las articulaciones fijas por posicion.
    estable       de pie con equilibrio automatico.
    caminar       locomocion. En el X2 se activa solo desde estable.
    cabeza        solo la cabeza responde.
    tren_superior cabeza, brazos y manos responden (los piernas se quedan en equilibrio).
"""
from .errores import NoSoportado
from .modos import GRAFO, REQUIEREN_CONFIRMACION

MODOS = ("pasivo", "amortiguado", "fijo", "estable", "caminar", "cabeza", "tren_superior")


class Robot:
    nombre = "base"
    capacidades = frozenset()           # caminar, brazos, cabeza, manos, hablar, gestos
    vel_min = (0.0, 0.0, 0.0)           # abajo de esto el robot ignora o rechaza la orden
    vel_max = (1.0, 1.0, 1.0)
    grafo = GRAFO                       # transiciones de modo permitidas
    confirmaciones = REQUIEREN_CONFIRMACION   # modos que piden que un humano confirme antes de entrar
    # que modos aceptan cada accion; None significa que no se revisa
    modos_para = {
        "caminar": {"estable", "caminar"},
        "brazos": {"tren_superior"},
        "cabeza": {"tren_superior", "cabeza"},
        "manos": {"tren_superior"},
        "gestos": {"estable", "caminar"},
    }

    def __init__(self, config=None, alertas=None):
        self.config = config or {}
        self.alertas = alertas

    # ---------- ciclo de vida ----------
    def conectar(self):
        raise NoSoportado(f"{self.nombre} no implementa conectar()")

    def cerrar(self):
        pass

    def __enter__(self):
        self.conectar()
        return self

    def __exit__(self, *exc):
        self.cerrar()
        return False

    # ---------- estado ----------
    def estado(self):
        """Devuelve {'conectado': bool, 'modo': str|None, 'bateria': float|None, ...}."""
        raise NoSoportado(f"{self.nombre} no implementa estado()")

    def modos(self):
        return list(MODOS)

    # ---------- modos ----------
    def cambiar_modo(self, modo):
        raise NoSoportado(f"{self.nombre} no cambia de modo")

    def preparar(self, modo):
        """Lleva al robot al modo pedido pasando por los intermedios necesarios."""
        self.cambiar_modo(modo)

    # ---------- movimiento ----------
    def enviar_velocidad(self, vx, vy, wz):
        raise NoSoportado(f"{self.nombre} no camina")

    def detener(self):
        """Velocidad cero. Debe ser seguro llamarlo siempre."""
        try:
            self.enviar_velocidad(0.0, 0.0, 0.0)
        except NoSoportado:
            pass

    def emergencia(self, nivel="detener"):
        self.detener()

    def gestos(self):
        return []

    def gesto(self, nombre, lado="derecha"):
        raise NoSoportado(f"{self.nombre} no hace gestos")

    # ---------- tren superior ----------
    def brazos(self, izq, der):
        raise NoSoportado(f"{self.nombre} no mueve brazos")

    def cabeza(self, yaw, pitch):
        raise NoSoportado(f"{self.nombre} no mueve la cabeza")

    def mano(self, lado, valor, tipo="pinza"):
        raise NoSoportado(f"{self.nombre} no tiene manos")

    # ---------- interaccion ----------
    def hablar(self, texto):
        raise NoSoportado(f"{self.nombre} no habla")

    # ---------- utilidades ----------
    def tiene(self, capacidad):
        return capacidad in self.capacidades
