"""Seguridad: limites, vigilante, parada de emergencia y confirmaciones.

Reglas que aplica:
  * Las velocidades se recortan a los limites configurados y a los del robot.
  * El movimiento por velocidad lo mantiene un hilo que reenvia a ritmo fijo y, cuando
    se acaba el tiempo, hay una parada o algo falla, manda ceros. El robot X2 se frena solo
    si pasan 200 ms sin ordenes, asi que no se puede mandar una sola vez y olvidarse.
  * Antes de cada accion se revisa conexion, bateria y modo. Un modo desconocido NO pasa.
  * Un vigilante lee el estado cada segundo: sin conexion, modo inesperado o con bateria
    critica, para. Si el propio vigilante falla, para.
  * La parada de emergencia es un evento que bloquea todo hasta reanudar a mano.
  * 'interrumpir' (por ejemplo "para" por voz) frena y corta la orden en curso sin ser una
    emergencia.
"""
import math
import sys
import threading
import time
from contextlib import contextmanager

from .errores import ErrorSeguridad, NoSoportado
from .validacion import finito

_CAPACIDAD_DE = {"caminar": "caminar", "brazos": "brazos", "cabeza": "cabeza",
                 "manos": "manos", "gestos": "gestos"}


class Interrumpido(ErrorSeguridad):
    """Una orden en curso fue cortada a proposito (por ejemplo, 'para' por voz)."""


class ControlVelocidad(threading.Thread):
    """Reenvia la velocidad pedida a ritmo fijo y la pone en cero al vencer."""

    def __init__(self, robot, hz, alertas, max_fallos, al_fallar, esta_parado=None):
        super().__init__(daemon=True, name="andamio-velocidad")
        self.robot = robot
        self.periodo = 1.0 / max(1, hz)
        self.alertas = alertas
        self.max_fallos = max_fallos
        self.al_fallar = al_fallar
        self.esta_parado = esta_parado or (lambda: False)
        self._lock = threading.Lock()
        self._sp = (0.0, 0.0, 0.0)
        self._hasta = 0.0
        self._ceros = 0
        self._fin = threading.Event()
        self._fallos = 0
        self.ultimo_envio = (0.0, 0.0, 0.0)
        self.envios = 0

    def fijar(self, vx, vy, wz, hasta):
        with self._lock:
            if self.esta_parado():
                return
            self._sp = (vx, vy, wz)
            self._hasta = hasta
            self._ceros = 0

    def cero(self):
        with self._lock:
            self._sp = (0.0, 0.0, 0.0)
            self._ceros = max(self._ceros, int(0.5 / self.periodo))

    def activo(self):
        with self._lock:
            return self._sp != (0.0, 0.0, 0.0)

    def terminar(self):
        self._fin.set()

    def run(self):
        siguiente = time.monotonic()
        while not self._fin.is_set():
            ahora = time.monotonic()
            with self._lock:
                if self._sp != (0.0, 0.0, 0.0) and (ahora >= self._hasta or self.esta_parado()):
                    self._sp = (0.0, 0.0, 0.0)
                    self._ceros = int(0.5 / self.periodo)
                sp, ceros = self._sp, self._ceros
            if sp != (0.0, 0.0, 0.0) or ceros > 0:
                try:
                    self.robot.enviar_velocidad(*sp)
                    self.ultimo_envio = sp
                    self.envios += 1
                    self._fallos = 0
                except NoSoportado:
                    self.cero()
                except Exception as e:  # cualquier fallo de red o del robot
                    self._fallos += 1
                    self.alertas.error(f"fallo enviando velocidad ({self._fallos}/{self.max_fallos}): {e}")
                    if self._fallos >= self.max_fallos:
                        self.alertas.critico("demasiados fallos seguidos enviando velocidad, se detiene todo")
                        with self._lock:
                            self._sp = (0.0, 0.0, 0.0)
                            self._ceros = 0
                        self._fallos = 0
                        try:
                            self.al_fallar()
                        except Exception:
                            pass
                if sp == (0.0, 0.0, 0.0):
                    with self._lock:
                        self._ceros = max(0, self._ceros - 1)
            siguiente += self.periodo
            espera = siguiente - time.monotonic()
            if espera > 0:
                self._fin.wait(espera)
            else:
                siguiente = time.monotonic()


class Seguridad:
    def __init__(self, robot, alertas, cfg, auto_confirmar=False):
        self.robot = robot
        self.alertas = alertas
        self.cfg = cfg["seguridad"] if "seguridad" in cfg else cfg
        self.auto_confirmar = auto_confirmar
        self._parada = threading.Event()
        self._alto = threading.Event()
        self._conf = threading.Event()
        self._pendiente = None
        self._modos_esperados = None
        self._superior = 0
        self._lock_sup = threading.Lock()
        self._fallos_estado = 0
        self._ultimo_aviso_bateria = 0.0
        self._aviso_bat_none = False
        self._fin_vigilante = threading.Event()
        self._lock_inicio = threading.Lock()
        self.control = ControlVelocidad(robot, self.cfg["hz_control"], alertas,
                                        self.cfg["fallos_seguidos"], self.parada_interna,
                                        esta_parado=lambda: self._parada.is_set())
        self.vigilante = threading.Thread(target=self._vigilar, daemon=True, name="andamio-vigilante")
        self._iniciado = False

    # ---------- ciclo de vida ----------
    def iniciar(self):
        with self._lock_inicio:
            if not self._iniciado:
                self.control.start()
                self.vigilante.start()
                self._iniciado = True

    def cerrar(self):
        try:
            self.control.cero()
            time.sleep(min(0.3, self.control.periodo * 6))
        finally:
            self.control.terminar()
            self._fin_vigilante.set()

    # ---------- parada ----------
    @property
    def parado(self):
        return self._parada.is_set()

    def parada_interna(self):
        self.parada("fallo de comunicacion con el robot")

    def parada(self, motivo="parada solicitada"):
        primera = not self._parada.is_set()
        self._parada.set()
        self._alto.set()
        self.control.cero()
        if primera:
            self.alertas.critico(f"PARADA DE EMERGENCIA: {motivo}",
                                 pista="revisa el robot; para seguir hay que reanudar a mano")
        try:
            self.robot.emergencia(self.cfg.get("emergencia", "detener"))
        except Exception as e:
            self.alertas.error(f"el robot no pudo ejecutar la emergencia: {e}")

    def reanudar(self):
        if self._parada.is_set():
            self._parada.clear()
            self._alto.clear()
            self.alertas.aviso("parada levantada, se puede volver a ordenar")

    # ---------- interrupcion (no es emergencia) ----------
    @property
    def alto(self):
        return self._alto.is_set()

    def interrumpir(self):
        """Frena y corta lo que se este ejecutando. Quien ejecuta debe llamar a limpiar_alto() para seguir."""
        self._alto.set()
        self.control.cero()

    def limpiar_alto(self):
        if not self._parada.is_set():
            self._alto.clear()

    def comprobar_alto(self):
        if self._alto.is_set():
            if self._parada.is_set():
                raise ErrorSeguridad("parada de emergencia activa")
            raise Interrumpido("orden interrumpida")

    # ---------- limites ----------
    def limitar_velocidad(self, vx, vy, wz, avisar=True):
        lim = (min(self.cfg["vx_max"], self.robot.vel_max[0]),
               min(self.cfg["vy_max"], self.robot.vel_max[1]),
               min(self.cfg["wz_max"], self.robot.vel_max[2]))
        salida = []
        for v, tope, minimo, nombre in zip((vx, vy, wz), lim, self.robot.vel_min, ("vx", "vy", "wz")):
            v = finito(v, nombre)
            if abs(v) < 0.005:
                salida.append(0.0)
                continue
            a = min(abs(v), tope)
            if a < minimo:
                if tope < minimo:
                    raise ErrorSeguridad(
                        f"el limite de {nombre} ({tope}) es menor que el minimo que acepta el robot ({minimo})",
                        pista="sube el limite en config.yaml")
                if avisar:
                    self.alertas.aviso(f"{nombre}={v} es menor que el minimo del robot, se sube a {minimo}")
                a = minimo
            if a < abs(v) - 1e-9 and avisar:
                self.alertas.aviso(f"{nombre} recortado de {abs(v):.2f} a {a:.2f}")
            salida.append(math.copysign(a, v))
        return tuple(salida)

    # ---------- revisiones ----------
    def esperar_modos(self, modos):
        """Declara en que modos debe estar el robot; si sale de ellos mientras se mueve, se para."""
        self._modos_esperados = set(modos) if modos else None

    @contextmanager
    def tren_superior_activo(self):
        """Mientras se mueven brazos/teleop, el vigilante tambien exige el modo esperado."""
        with self._lock_sup:
            self._superior += 1
        try:
            yield
        finally:
            with self._lock_sup:
                self._superior -= 1

    def _hay_movimiento(self):
        return self.control.activo() or self._superior > 0

    @staticmethod
    def _bateria(est):
        """Devuelve la bateria como float finito, o None si no se conoce o es invalida."""
        bat = est.get("bateria")
        if bat is None or isinstance(bat, bool):
            return None
        try:
            bat = float(bat)
        except (TypeError, ValueError):
            return None
        return bat if math.isfinite(bat) else None

    def revisar_antes(self, accion):
        if self.parado:
            raise ErrorSeguridad("hay una parada de emergencia activa",
                                 pista="levanta la parada (reanudar) cuando el robot este seguro")
        cap = _CAPACIDAD_DE.get(accion)
        if cap and not self.robot.tiene(cap):
            raise NoSoportado(f"el robot {self.robot.nombre} no soporta '{accion}'")
        try:
            est = self.robot.estado()
        except Exception as e:
            raise ErrorSeguridad(f"no se pudo leer el estado del robot: {e}",
                                 pista="corre el diagnostico: python -m andamio.doctor")
        if not est.get("conectado", True):
            raise ErrorSeguridad("el robot no esta conectado")
        bat = self._bateria(est)
        if accion in ("caminar", "brazos", "gestos"):
            if bat is None:
                if not self._aviso_bat_none:
                    self._aviso_bat_none = True
                    self.alertas.aviso("no se pudo leer la bateria, se sigue bajo tu responsabilidad",
                                       pista="mira la bateria a ojo: debe estar sobre 50%")
            elif bat < self.cfg["bateria_min"]:
                raise ErrorSeguridad(f"bateria {bat:.0f}% por debajo del minimo ({self.cfg['bateria_min']}%)",
                                     pista="cargar o cambiar bateria antes de mover el robot")
        permitidos = getattr(self.robot, "modos_para", {}).get(accion)
        modo = est.get("modo")
        if permitidos and modo not in permitidos:
            crudo = est.get("modo_x2")
            extra = f" (el robot reporta '{crudo}')" if crudo else ""
            raise ErrorSeguridad(
                f"para '{accion}' el robot debe estar en {sorted(permitidos)} y esta en '{modo}'{extra}",
                pista="agrega un paso 'preparar' antes en la plantilla; si el modo es desconocido o el robot se cayo, revisalo")
        return est

    # ---------- movimiento ----------
    def mover(self, vx, vy, wz, duracion):
        self.comprobar_alto()
        self.revisar_antes("caminar")
        vx, vy, wz = self.limitar_velocidad(vx, vy, wz)
        duracion = finito(duracion, "duracion")
        if not (0 < duracion <= 60):
            raise ErrorSeguridad(f"duracion fuera de rango (0 a 60 s): {duracion}")
        if (vx, vy, wz) == (0.0, 0.0, 0.0):
            self.control.cero()
            time.sleep(min(duracion, 1.0))
            return
        fin = time.monotonic() + duracion
        try:
            self.control.fijar(vx, vy, wz, fin)
            while time.monotonic() < fin:
                if self.parado:
                    raise ErrorSeguridad("movimiento interrumpido por parada de emergencia")
                if self._alto.is_set():
                    raise Interrumpido("movimiento interrumpido")
                time.sleep(0.02)
        finally:
            self.control.cero()
        time.sleep(min(0.2, self.control.periodo * 4))

    def mover_continuo(self, vx, vy, wz, vence_s=0.35):
        """Para comportamientos en ciclo cerrado: fija una velocidad que caduca sola en `vence_s`
        si nadie la renueva (hombre muerto). Revisa todo en cada llamada. Devuelve lo que se envia."""
        self.comprobar_alto()
        if self.parado:
            raise ErrorSeguridad("parada de emergencia activa")
        self.revisar_antes("caminar")
        vx, vy, wz = self.limitar_velocidad(vx, vy, wz, avisar=False)
        vence_s = min(max(finito(vence_s, "vence_s"), 0.05), 1.0)
        if (vx, vy, wz) == (0.0, 0.0, 0.0):
            self.control.cero()
        else:
            self.control.fijar(vx, vy, wz, time.monotonic() + vence_s)
        return vx, vy, wz

    def detener(self):
        self.control.cero()

    # ---------- confirmaciones ----------
    @property
    def pendiente(self):
        return self._pendiente

    def confirmar_ahora(self):
        self._conf.set()

    def _terminal_interactiva(self):
        try:
            return sys.stdin is not None and sys.stdin.isatty()
        except Exception:
            return False

    def _leer_terminal(self):
        """Lee una linea de la terminal sin bloquear ni dejar hilos colgados. True si confirman."""
        try:
            from .consola import leer_linea
            linea = leer_linea(0.1)
            return linea is not None and linea.strip().lower() in ("s", "si", "y", "yes")
        except Exception:
            return False

    def confirmar(self, texto, timeout=180):
        if self.auto_confirmar:
            return True
        self._pendiente = texto
        self._conf.clear()
        self.alertas.aviso(f"CONFIRMA: {texto}",
                           pista="escribe 's' y Enter en la terminal o pulsa Confirmar en el panel")
        fin = time.monotonic() + timeout
        interactiva = self._terminal_interactiva()
        try:
            while time.monotonic() < fin:
                if self._conf.is_set():
                    return True
                if interactiva:
                    if self._leer_terminal():
                        return True
                elif self._conf.wait(0.1):
                    return True
                if self.parado:
                    break
        finally:
            self._pendiente = None
        raise ErrorSeguridad("no hubo confirmacion a tiempo",
                             pista="repite la plantilla y confirma cuando el robot este listo")

    # ---------- vigilante ----------
    def _vigilar(self):
        periodo = float(self.cfg.get("vigilar_cada_s", 1.0))
        while not self._fin_vigilante.wait(periodo):
            try:
                self._vigilar_una_vez()
            except Exception as e:           # si el vigilante falla, no se puede garantizar nada: parar
                self.alertas.critico(f"fallo el vigilante de seguridad: {e}")
                self.parada("fallo interno del vigilante")

    def _vigilar_una_vez(self):
        if self.parado:
            return
        try:
            est = self.robot.estado()
            self._fallos_estado = 0
        except Exception as e:
            self._fallos_estado += 1
            self.alertas.aviso(f"no se pudo leer el estado ({self._fallos_estado}/3): {e}")
            if self._fallos_estado >= 3:
                self.parada("se perdio la comunicacion con el robot")
            return
        if not est.get("conectado", True):
            self.parada("el robot reporta que no esta conectado")
            return
        bat = self._bateria(est)
        if bat is not None:
            if bat <= self.cfg["bateria_critica"]:
                self.parada(f"bateria critica ({bat:.0f}%)")
                return
            if bat < self.cfg["bateria_min"] and time.monotonic() - self._ultimo_aviso_bateria > 30:
                self._ultimo_aviso_bateria = time.monotonic()
                self.alertas.aviso(f"bateria baja ({bat:.0f}%)")
        esperados = self._modos_esperados
        modo = est.get("modo")
        if esperados and modo not in esperados and self._hay_movimiento():
            self.parada(f"el robot salio del modo esperado: esta en '{modo}' ({est.get('modo_x2', '?')})")
