import pytest

from andamio.nucleo.errores import ErrorPlantilla


def plantilla(*pasos):
    return {"nombre": "m", "pasos": list(pasos)}


def test_medios_llegan_al_robot(entorno):
    r = entorno.ej.correr(plantilla({"expresion": "feliz"}, {"luces": {"modo": "respirar", "color": "azul"}},
                                    {"video": {"archivo": "intro.mp4", "repetir": True}},
                                    {"audio": "hola.wav"}))
    assert r["ok"], r
    rb = entorno.robot
    assert rb.llamadas("expresion") == [(90, False)]
    assert rb.llamadas("luces") == [(1, (0, 0, 255))]
    assert rb.llamadas("video") == [("/var/tmp/andamio_medios/intro.mp4", True)]
    assert rb.llamadas("audio") == [("/var/tmp/andamio_medios/hola.wav",)]


@pytest.mark.parametrize("paso", [{"expresion": "bailar"}, {"luces": {"modo": "disco"}},
                                  {"luces": {"color": [300, 0, 0]}}, {"video": {"archivo": "../etc/passwd"}},
                                  {"audio": {"archivo": ""}}])
def test_medios_validan(entorno, paso):
    r = entorno.ej.correr(plantilla(paso))
    assert not r["ok"]
    assert not any(entorno.robot.llamadas(m) for m in ("video", "audio", "expresion", "luces"))


def test_robot_sin_medios_falla_con_pista(entorno):
    from andamio.robots.d1 import RobotD1
    assert not RobotD1.capacidades & {"medios"}


def test_x2_audio_solo_wav():
    from andamio.nucleo.errores import ErrorRobot
    from andamio.robots.x2_ros2 import RobotX2

    class T:
        def reproducir_audio(self, *a):
            return True, ""
    r = RobotX2.__new__(RobotX2)
    r.t = T()
    with pytest.raises(ErrorRobot):
        r.audio("/var/tmp/x.mp3")
    r.audio("/var/tmp/x.wav")


def test_clases_propias_de_yolo():
    from andamio import config
    from andamio.nucleo.errores import ErrorConfiguracion
    with pytest.raises(ErrorConfiguracion):
        c = config.cargar(entorno={})
        c["vision"]["clases"] = "taza"
        config._validar(c)


def test_detector_con_clases_que_no_cuadran():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from andamio.nucleo.errores import ErrorRobot
    from andamio.vision import Detector, MODELO_YOLO
    if not MODELO_YOLO.exists():
        pytest.skip("sin modelo")
    d = Detector(clases=["a", "b"])
    with pytest.raises(ErrorRobot):
        d.detectar(np.full((480, 640, 3), 127, np.uint8))
