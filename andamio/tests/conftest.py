import pytest

from andamio import config
from andamio.nucleo.alertas import Alertas
from andamio.nucleo.ejecutor import Contexto, Ejecutor
from andamio.nucleo.seguridad import Seguridad
from andamio.robots.falso import RobotFalso


class Entorno:
    pass


@pytest.fixture
def cfg():
    c = config.cargar(entorno={})
    c["seguridad"]["hz_control"] = 100
    c["seguridad"]["vigilar_cada_s"] = 0.05
    return c


@pytest.fixture
def alertas():
    return Alertas(consola=False)


@pytest.fixture
def entorno(cfg, alertas):
    e = Entorno()
    e.cfg, e.alertas = cfg, alertas
    e.robot = RobotFalso(cfg, alertas)
    e.robot.conectar()
    e.seg = Seguridad(e.robot, alertas, cfg, auto_confirmar=True)
    e.seg.iniciar()
    e.ctx = Contexto(e.robot, e.seg, alertas, cfg)
    e.ej = Ejecutor(e.ctx)
    yield e
    e.seg.cerrar()
    e.robot.cerrar()


def requiere_modelo():
    """Salta la prueba si en esta maquina no hay un modelo MuJoCo completo (por ejemplo, en un Mac
    sin sim/mujoco_menagerie y con el MJCF del X2 a medio descargar)."""
    pytest.importorskip("mujoco")
    from andamio.nucleo.errores import ErrorRobot
    from andamio.robots.sim_mujoco import buscar_modelo
    try:
        return buscar_modelo()
    except ErrorRobot as e:
        pytest.skip(f"sin modelo MuJoCo: {e}")
