"""Crea el robot pedido por nombre."""
from .nucleo.errores import ErrorAndamio

ROBOTS = ("falso", "sim", "x2", "x2sim", "d1", "remoto")


def crear_robot(nombre, cfg, alertas, modelo=""):
    if nombre == "falso":
        from .robots.falso import RobotFalso
        return RobotFalso(cfg, alertas)
    if nombre == "sim":
        from .robots.sim_mujoco import RobotSim
        return RobotSim(cfg, alertas, modelo=modelo)
    if nombre == "x2":
        from .robots.x2_ros2 import RobotX2
        return RobotX2(cfg, alertas)
    if nombre == "x2sim":
        from .robots.x2_ros2 import RobotX2Sim
        return RobotX2Sim(cfg, alertas)
    if nombre == "d1":
        from .robots.d1 import RobotD1
        return RobotD1(cfg, alertas)
    if nombre == "remoto":
        from .robots.remoto import RobotRemoto
        return RobotRemoto(cfg, alertas)
    raise ErrorAndamio(f"robot desconocido: {nombre}", pista=f"opciones: {', '.join(ROBOTS)}")
