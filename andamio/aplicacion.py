"""Arma todas las piezas (robot, seguridad, alertas, voz, grabador) y corre plantillas."""
import os
import pathlib
import threading
import time

from . import config as _config
from .fabrica import crear_robot
from .grabador import Grabador
from .nucleo.alertas import Alertas
from .nucleo.ejecutor import Contexto, Ejecutor, cargar, validar
from .nucleo.errores import ErrorAndamio, ErrorPlantilla
from .nucleo.seguridad import Seguridad
from .nucleo.voz import Entendedor, Habla, OidoCola, crear_oido, es_alto

RAIZ_REPO = pathlib.Path(__file__).resolve().parents[1]
PLANTILLAS = pathlib.Path(__file__).resolve().parent / "plantillas"


def cargar_env(ruta=None):
    """Lee un .env sencillo (CLAVE=valor) sin pisar variables ya definidas."""
    for p in ([pathlib.Path(ruta)] if ruta else [RAIZ_REPO / ".env", pathlib.Path.cwd() / ".env"]):
        if p.exists():
            for linea in p.read_text(encoding="utf-8").splitlines():
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                k, _, v = linea.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def listar_plantillas():
    return sorted(p.name for p in PLANTILLAS.glob("*.yaml"))


def resolver_plantilla(nombre):
    p = pathlib.Path(nombre)
    if p.exists():
        return p
    for cand in (PLANTILLAS / nombre, PLANTILLAS / (nombre + ".yaml")):
        if cand.exists():
            return cand
    raise ErrorPlantilla(f"no se encontro la plantilla '{nombre}'", pista="disponibles: " + ", ".join(listar_plantillas()))


class Aplicacion:
    def __init__(self, robot="falso", config=None, modelo="", seco=False, confirmo=False, oido=None,
                 archivo_alertas=None, consola=True, robot_obj=None, ojo=None):
        cargar_env()
        self.cfg = _config.cargar(config)
        self.alertas = Alertas(archivo=archivo_alertas, consola=consola)
        self.seco = seco
        self.modelo_xml = modelo
        self.robot = robot_obj or crear_robot(robot, self.cfg, self.alertas, modelo)
        self.seguridad = Seguridad(self.robot, self.alertas, self.cfg, auto_confirmar=confirmo)
        self.grabador = Grabador()
        tipo_oido = oido or self.cfg["voz"]["oido"]
        # "para" dicho por el panel debe frenar de inmediato, aunque el robot este ocupado
        # ejecutando otra orden: por eso el gancho corre en el hilo que recibe el texto.
        self.cola_voz = OidoCola(al_poner=self._alto_por_voz)
        self.oido_es_panel = tipo_oido == "panel"
        self.oido = self.cola_voz if self.oido_es_panel else crear_oido(tipo_oido, self.cfg["voz"]["idioma"])
        self.habla = Habla(self.robot, self.alertas)
        from .vision import crear_ojo
        self.ojo = crear_ojo(ojo or self.cfg["vision"]["ojo"], self.robot, self.cfg, self.alertas)
        self.ctx = Contexto(self.robot, self.seguridad, self.alertas, self.cfg, grabador=self.grabador,
                            oido=self.oido, habla=self.habla, seco=seco, fabrica_teleop=self._fabrica_teleop,
                            ojo=self.ojo)
        self.ejecutor = Ejecutor(self.ctx)
        self.corriendo = None
        self.ultimo = None
        self._hilo = None
        self._iniciada = False
        self._cerrojo = threading.Lock()

    def _alto_por_voz(self, texto):
        if self.corriendo and es_alto(texto):
            self.seguridad.interrumpir()

    def _fabrica_teleop(self, puerto):
        from .teleop import Teleop
        modelo = getattr(self.robot, "modelo", None)
        if modelo is None:
            from .cinematica import Modelo
            from .robots.sim_mujoco import buscar_modelo
            modelo = Modelo(buscar_modelo(self.modelo_xml))
        return Teleop(self.robot, self.seguridad, self.alertas, self.cfg, self.grabador, modelo=modelo, puerto=puerto)

    # ---------- ciclo de vida ----------
    def iniciar(self):
        if self._iniciada:
            return
        if not self.seco:
            self.robot.conectar()
            self.seguridad.iniciar()
            if self.ojo is not None:
                self.ojo.iniciar()
        self._iniciada = True

    def cerrar(self):
        try:
            if self.ojo is not None:
                self.ojo.cerrar()
            if not self.seco and self._iniciada:
                self.seguridad.cerrar()
        finally:
            try:
                self.robot.cerrar()
            finally:
                self.alertas.cerrar()

    # ---------- plantillas ----------
    def validar(self, nombre):
        plantilla = cargar(resolver_plantilla(nombre))
        return validar(plantilla, self.robot)

    def _reservar(self, nombre):
        with self._cerrojo:
            if self.corriendo:
                raise ErrorAndamio(f"ya se esta ejecutando '{self.corriendo}'",
                                   pista="espera a que termine o pulsa PARAR")
            self.corriendo = nombre

    def _correr(self, ruta, parametros):
        try:
            self.iniciar()
            self.ultimo = self.ejecutor.correr(ruta, parametros)
        finally:
            with self._cerrojo:
                self.corriendo = None
        return self.ultimo

    def ejecutar(self, nombre, parametros=None):
        ruta = resolver_plantilla(nombre)
        self._reservar(ruta.name)
        return self._correr(ruta, parametros)

    def ejecutar_en_hilo(self, nombre, parametros=None):
        ruta = resolver_plantilla(nombre)
        self._reservar(ruta.name)
        try:
            self._hilo = threading.Thread(target=self._seguro, args=(ruta, parametros), daemon=True,
                                          name="andamio-plantilla")
            self._hilo.start()
        except BaseException:
            with self._cerrojo:
                self.corriendo = None
            raise

    def _seguro(self, ruta, parametros):
        try:
            self._correr(ruta, parametros)
        except ErrorAndamio as e:
            self.alertas.error(f"no se pudo ejecutar: {e}", pista=e.pista)
        except Exception as e:
            self.alertas.error(f"error inesperado: {e}")
