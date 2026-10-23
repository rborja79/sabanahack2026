"""Ejecutor de plantillas.

Una plantilla es un archivo YAML con una lista de pasos. El ejecutor la valida, sustituye
parametros, corre cada paso con reintentos y deja el robot detenido pase lo que pase.

    nombre: Caminar un poco
    parametros: {velocidad: 0.3}
    pasos:
      - preparar: caminar
      - caminar: {vx: "${velocidad}", duracion: 3}
        reintentos: 1
      - decir: "Listo"
"""
import math
import pathlib
import re
import threading
import time
import traceback

try:
    import yaml
except ImportError:
    yaml = None

from .errores import ErrorAndamio, ErrorPlantilla, ErrorSeguridad, ErrorVoz, NoSoportado
from .seguridad import Interrumpido
from .validacion import finito, lista_finita
from .modos import ruta
from .voz import Entendedor, Habla, normalizar

META = {"reintentos", "en_fallo", "nombre"}
ALIAS_MODO = {"brazos": "tren_superior", "manos": "tren_superior", "de_pie": "estable"}
MODOS_ESPERADOS = {
    "caminar": {"estable", "caminar"}, "estable": {"estable", "caminar"},
    "tren_superior": {"tren_superior"}, "cabeza": {"cabeza", "tren_superior"},
}
_VAR = re.compile(r"\$\{([A-Za-z_][\w.]*)\}")
_COND = re.compile(r"^\s*([\w.]+)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$")


class PasoFallido(ErrorAndamio):
    pass


class Contexto:
    def __init__(self, robot, seguridad, alertas, cfg, grabador=None, oido=None, habla=None,
                 entendedor=None, seco=False, fabrica_teleop=None, ojo=None):
        self.robot = robot
        self.seguridad = seguridad
        self.alertas = alertas
        self.cfg = cfg
        self.grabador = grabador
        self.oido = oido
        self.habla = habla or Habla(robot, alertas)
        self.entendedor = entendedor
        self.seco = seco
        self.fabrica_teleop = fabrica_teleop
        self.ojo = ojo
        self.variables = {}
        self.comandos = {}
        self.ultimos_brazos = ([0.0] * 7, [0.0] * 7)


# ------------------------------------------------------------------ especificacion de pasos
ESPEC = {
    "preparar": None, "modo": None,
    "caminar": {"vx", "vy", "wz", "duracion", "distancia"},
    "girar": {"grados", "wz"},
    "parar": {"emergencia"},
    "esperar": None,
    "decir": None,
    "gesto": {"nombre", "lado"},
    "brazos": {"izq", "der", "pose", "segundos"},
    "cabeza": {"yaw", "pitch"},
    "mano": {"lado", "valor", "tipo", "abrir", "cerrar"},
    "escuchar": {"guardar_en", "tiempo"},
    "entender": {"de", "guardar_en"},
    "ejecutar_accion": None,
    "voz_bucle": {"turnos", "salir", "saludo", "escuchar_s"},
    "teleop": {"duracion", "grabar", "tarea", "puerto"},
    "repetir": {"veces", "pasos"},
    "si": {"cuando", "entonces", "si_no"},
    "grabar": {"tarea", "pasos"},
    "registrar": None,
    "confirmar": None,
    "mirar": {"objeto", "confianza", "guardar_en"},
    "buscar": {"objeto", "confianza", "max_s", "wz", "sentido"},
    "acercarse": {"objeto", "confianza", "distancia", "vx", "max_s", "perdido_s"},
}
POSES = {"reposo": ([0.0] * 7, [0.0] * 7)}


def _sustituir(valor, ctx, extra=None):
    """Reemplaza ${x} por el valor de la variable, conservando el tipo si es el texto completo."""
    if isinstance(valor, str):
        m = _VAR.fullmatch(valor.strip())
        if m:
            return _resolver(m.group(1), ctx, extra)
        return _VAR.sub(lambda mm: str(_resolver(mm.group(1), ctx, extra)), valor)
    if isinstance(valor, list):
        return [_sustituir(v, ctx, extra) for v in valor]
    if isinstance(valor, dict):
        return {k: (v if k in ("pasos", "entonces", "si_no") else _sustituir(v, ctx, extra))
                for k, v in valor.items()}
    return valor


def _resolver(nombre, ctx, extra=None):
    raiz, _, resto = nombre.partition(".")
    if raiz == "estado":
        est = ctx.robot.estado()
        if not resto:
            return est
        if resto not in est:
            raise ErrorPlantilla(f"el estado del robot no tiene '{resto}'", pista=f"claves: {sorted(est)}")
        return est[resto]
    fuente = dict(ctx.variables)
    if extra:
        fuente.update(extra)
    if raiz not in fuente:
        raise ErrorPlantilla(f"variable sin definir: ${{{nombre}}}",
                             pista="defínela en 'parametros' o con un paso que la guarde")
    valor = fuente[raiz]
    for parte in resto.split(".") if resto else []:
        if not isinstance(valor, dict) or parte not in valor:
            raise ErrorPlantilla(f"variable sin definir: ${{{nombre}}}")
        valor = valor[parte]
    return valor


def _numero(x, nombre):
    if isinstance(x, bool):
        raise ErrorPlantilla(f"'{nombre}' debe ser un numero y llego {x!r}")
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ErrorPlantilla(f"'{nombre}' debe ser un numero y llego {x!r}")
    if not math.isfinite(v):
        raise ErrorPlantilla(f"'{nombre}' no es finito")
    return v


# ------------------------------------------------------------------ carga y validacion
def cargar(origen):
    if isinstance(origen, dict):
        return origen
    if yaml is None:
        raise ErrorPlantilla("falta PyYAML", pista="pip install pyyaml")
    ruta_ = pathlib.Path(origen)
    if not ruta_.exists():
        raise ErrorPlantilla(f"no existe la plantilla: {ruta_}")
    try:
        with open(ruta_, encoding="utf-8") as fh:
            datos = yaml.safe_load(fh)
    except yaml.YAMLError as e:
        raise ErrorPlantilla(f"YAML invalido en {ruta_.name}: {e}")
    if not isinstance(datos, dict):
        raise ErrorPlantilla(f"{ruta_.name} debe ser un mapa con 'pasos'")
    return datos


def separar_paso(paso):
    if not isinstance(paso, dict):
        raise ErrorPlantilla(f"cada paso debe ser un mapa, llego {paso!r}")
    claves = [k for k in paso if k not in META]
    if len(claves) != 1:
        raise ErrorPlantilla(f"cada paso tiene exactamente una accion, llego {sorted(paso)}")
    nombre = claves[0]
    if nombre not in ESPEC:
        cerca = [n for n in ESPEC if n.startswith(nombre[:2])]
        raise ErrorPlantilla(f"paso desconocido: '{nombre}'", pista=f"disponibles: {sorted(ESPEC)}"
                             + (f"; quizas quisiste decir {cerca}" if cerca else ""))
    meta = {k: paso[k] for k in META if k in paso}
    return nombre, paso[nombre], meta


def validar(plantilla, robot=None):
    """Devuelve la lista de problemas; vacia si esta bien."""
    problemas = []
    if not isinstance(plantilla.get("pasos"), list) or not plantilla["pasos"]:
        problemas.append("'pasos' debe ser una lista con al menos un paso")
        return problemas
    comandos = plantilla.get("comandos") or {}
    for cid, c in comandos.items():
        if not isinstance(c, dict) or not isinstance(c.get("pasos"), list):
            problemas.append(f"comando '{cid}' necesita 'pasos'")
        else:
            problemas += _validar_pasos(c["pasos"], f"comandos.{cid}")
    problemas += _validar_pasos(plantilla["pasos"], "pasos")
    if robot is not None:
        faltan = [c for c in plantilla.get("requiere", []) if not robot.tiene(c)]
        if faltan:
            problemas.append(f"el robot '{robot.nombre}' no soporta: {faltan}")
    return problemas


def _validar_pasos(pasos, ruta_):
    problemas = []
    for i, p in enumerate(pasos):
        donde = f"{ruta_}[{i}]"
        try:
            nombre, args, meta = separar_paso(p)
        except ErrorPlantilla as e:
            problemas.append(f"{donde}: {e}")
            continue
        permitidos = ESPEC[nombre]
        if permitidos is not None and isinstance(args, dict):
            raros = set(args) - permitidos
            if raros:
                problemas.append(f"{donde} ({nombre}): claves desconocidas {sorted(raros)}; validas: {sorted(permitidos)}")
        if nombre in ("repetir", "grabar"):
            if not isinstance(args, dict) or not isinstance(args.get("pasos"), list):
                problemas.append(f"{donde} ({nombre}): falta 'pasos'")
            else:
                problemas += _validar_pasos(args["pasos"], donde + ".pasos")
        if nombre == "si":
            if not isinstance(args, dict) or "cuando" not in args:
                problemas.append(f"{donde} (si): falta 'cuando'")
            else:
                if not _COND.match(str(args["cuando"])):
                    problemas.append(f"{donde} (si): condicion invalida {args['cuando']!r}; usa por ejemplo 'estado.bateria >= 60'")
                for rama in ("entonces", "si_no"):
                    if rama in args:
                        if not isinstance(args[rama], list):
                            problemas.append(f"{donde} (si): '{rama}' debe ser una lista")
                        else:
                            problemas += _validar_pasos(args[rama], f"{donde}.{rama}")
        if "reintentos" in meta and (isinstance(meta["reintentos"], bool) or not isinstance(meta["reintentos"], int)
                                     or meta["reintentos"] < 0):
            problemas.append(f"{donde}: 'reintentos' debe ser un entero mayor o igual a 0")
        if meta.get("en_fallo") not in (None, "abortar", "continuar", "parar"):
            problemas.append(f"{donde}: 'en_fallo' debe ser abortar, continuar o parar")
    return problemas


# ------------------------------------------------------------------ ejecutor
class Ejecutor:
    def __init__(self, ctx):
        self.ctx = ctx
        self.resultados = []

    # ---------- publico ----------
    def correr(self, origen, parametros=None):
        ctx = self.ctx
        plantilla = cargar(origen)
        problemas = validar(plantilla, ctx.robot)
        if problemas:
            for p in problemas:
                ctx.alertas.error(f"plantilla: {p}")
            raise ErrorPlantilla(f"la plantilla tiene {len(problemas)} problema(s)", pista="corrige los avisos de arriba")
        ctx.variables = dict(plantilla.get("parametros") or {})
        ctx.variables.update(parametros or {})
        ctx.comandos = plantilla.get("comandos") or {}
        if ctx.entendedor is None and ctx.comandos:
            ctx.entendedor = Entendedor(ctx.comandos, ctx.alertas, ctx.cfg.get("voz"))
        nombre = plantilla.get("nombre", "sin nombre")
        ctx.alertas.info(f"plantilla: {nombre}" + (" (SECO: no se envia nada)" if ctx.seco else ""))
        self.resultados = []
        ctx.seguridad.limpiar_alto()
        t0 = time.monotonic()
        ok, causa = True, ""
        try:
            self.pasos(plantilla["pasos"])
        except KeyboardInterrupt:
            ok, causa = False, "interrumpido por el operador"
            ctx.alertas.aviso("interrumpido por el operador, se detiene el robot")
        except ErrorAndamio as e:
            ok, causa = False, str(e)
            ctx.alertas.error(f"plantilla abortada: {e}", pista=e.pista)
        except Exception as e:
            ok, causa = False, f"error inesperado: {e}"
            ctx.alertas.error(f"error inesperado: {e}", detalle=traceback.format_exc(limit=6))
        finally:
            self._cierre()
        if ok:
            ctx.alertas.info(f"plantilla terminada en {time.monotonic() - t0:.1f} s")
        return {"ok": ok, "causa": causa, "pasos": self.resultados,
                "duracion_s": round(time.monotonic() - t0, 2), "alertas": dict(ctx.alertas.conteo)}

    def _cierre(self):
        ctx = self.ctx
        if not ctx.seco:
            try:
                ctx.seguridad.detener()
            except Exception:
                pass
        if ctx.grabador is not None and ctx.grabador.activo:
            meta = ctx.grabador.parar()
            if meta:
                ctx.alertas.info(f"episodio guardado: {meta.get('episodio')} ({meta.get('tramas')} tramas)")

    def pasos(self, lista, extra=None):
        seg = self.ctx.seguridad
        for p in lista:
            if not self.ctx.seco:
                if seg.parado:
                    raise ErrorSeguridad("parada de emergencia activa")
                seg.comprobar_alto()
            self.paso(p, extra)
        if seg.parado and not self.ctx.seco:
            raise ErrorSeguridad("parada de emergencia activa")

    def paso(self, paso, extra=None):
        ctx = self.ctx
        nombre, args, meta = separar_paso(paso)
        reintentos = int(meta.get("reintentos", 0))
        en_fallo = meta.get("en_fallo", "abortar")
        ultimo = None
        for intento in range(reintentos + 1):
            try:
                if ctx.seco:
                    self._seco(nombre, args, extra)
                else:
                    getattr(self, f"_paso_{nombre}")(_sustituir_args(nombre, args, ctx, extra), extra)
                self.resultados.append({"paso": nombre, "ok": True, "intentos": intento + 1})
                return
            except (ErrorSeguridad, KeyboardInterrupt):
                self.resultados.append({"paso": nombre, "ok": False, "error": "seguridad"})
                raise
            except ErrorPlantilla:
                raise
            except ErrorAndamio as e:
                ultimo = e
                ctx.alertas.error(f"paso '{nombre}' fallo ({intento + 1}/{reintentos + 1}): {e}", pista=e.pista)
                if intento < reintentos:
                    time.sleep(0.5 * (intento + 1))
            except Exception as e:
                ultimo = e
                ctx.alertas.error(f"paso '{nombre}' fallo con un error inesperado: {e}",
                                  detalle=traceback.format_exc(limit=5))
                break
        self.resultados.append({"paso": nombre, "ok": False, "error": str(ultimo)})
        if en_fallo == "continuar":
            ctx.alertas.aviso(f"se continua tras el fallo de '{nombre}'")
            return
        if en_fallo == "parar":
            ctx.seguridad.parada(f"fallo del paso '{nombre}'")
        raise PasoFallido(f"fallo el paso '{nombre}': {ultimo}")

    # ---------- modo seco ----------
    def _seco(self, nombre, args, extra):
        self.ctx.alertas.info(f"[seco] {nombre}: {args}")
        if nombre in ("repetir", "grabar"):
            self.pasos(args["pasos"], extra)
        elif nombre == "si":
            self.pasos(args.get("entonces", []), extra)
            self.pasos(args.get("si_no", []), extra)

    # ---------- pasos ----------
    def _paso_preparar(self, a, extra):
        modo = a["modo"] if isinstance(a, dict) else a
        modo = ALIAS_MODO.get(modo, modo)
        ctx = self.ctx
        est = ctx.robot.estado()
        origen = est.get("modo")
        if origen is None:
            raise ErrorSeguridad("no se conoce el modo actual del robot",
                                 pista="revisa la conexion con el diagnostico")
        try:
            camino = ruta(origen, modo, ctx.robot.grafo)
        except KeyError as e:
            raise ErrorPlantilla(f"modo desconocido: {e}", pista="modos: pasivo, amortiguado, fijo, estable, caminar, cabeza, tren_superior")
        for m in camino:
            ctx.seguridad.comprobar_alto()
            if m in ctx.robot.confirmaciones and ctx.cfg["seguridad"].get("confirmar_pies", True):
                ctx.seguridad.confirmar(ctx.robot.confirmaciones[m])
            ctx.seguridad.comprobar_alto()
            ctx.alertas.info(f"modo: {origen} -> {m}")
            ctx.robot.cambiar_modo(m)
            origen = m
        ctx.seguridad.esperar_modos(MODOS_ESPERADOS.get(modo, {modo}))

    def _paso_modo(self, a, extra):
        # mismo camino que 'preparar': confirmaciones, ruta valida y vigilancia del modo
        self._paso_preparar(a, extra)

    def _paso_caminar(self, a, extra):
        a = a or {}
        vx, vy, wz = (_numero(a.get(k, 0.0), k) for k in ("vx", "vy", "wz"))
        vx, vy, wz = self.ctx.seguridad.limitar_velocidad(vx, vy, wz)    # las que realmente se enviaran
        if "duracion" in a:
            dur = _numero(a["duracion"], "duracion")
        elif "distancia" in a:
            if abs(vx) < 0.005:
                raise ErrorPlantilla("'distancia' necesita 'vx'")
            dur = abs(_numero(a["distancia"], "distancia") / vx)
            self.ctx.alertas.aviso("la distancia se estima por tiempo, sin medir; puede variar con el piso")
        else:
            raise ErrorPlantilla("'caminar' necesita 'duracion' o 'distancia'")
        self.ctx.seguridad.mover(vx, vy, wz, dur)

    def _paso_girar(self, a, extra):
        grados = _numero(a["grados"], "grados")
        if grados == 0:
            return
        wz = abs(_numero(a.get("wz", 0.4), "wz"))
        wz = abs(self.ctx.seguridad.limitar_velocidad(0.0, 0.0, wz)[2])      # velocidad efectiva tras recortar
        if wz == 0.0:
            raise ErrorPlantilla("'wz' no puede ser 0 en 'girar'")
        dur = math.radians(abs(grados)) / wz
        self.ctx.seguridad.mover(0.0, 0.0, math.copysign(wz, grados), dur)

    def _paso_parar(self, a, extra):
        if isinstance(a, dict) and a.get("emergencia"):
            self.ctx.seguridad.parada("pedida por la plantilla")
        else:
            self.ctx.seguridad.detener()

    def _paso_esperar(self, a, extra):
        seg = _numero(a if not isinstance(a, dict) else a.get("segundos", 0), "esperar")
        fin = time.monotonic() + max(0.0, min(seg, 600.0))
        while time.monotonic() < fin:
            if self.ctx.seguridad.parado:
                raise ErrorSeguridad("parada de emergencia durante la espera")
            time.sleep(min(0.05, fin - time.monotonic()))

    def _paso_decir(self, a, extra):
        self.ctx.habla.decir(a["texto"] if isinstance(a, dict) else a)

    def _paso_confirmar(self, a, extra):
        self.ctx.seguridad.confirmar(str(a["texto"] if isinstance(a, dict) else a))

    def _paso_registrar(self, a, extra):
        self.ctx.alertas.info(str(a["texto"] if isinstance(a, dict) else a))

    def _paso_gesto(self, a, extra):
        self.ctx.seguridad.revisar_antes("gestos")
        self.ctx.robot.gesto(a["nombre"], a.get("lado", "derecha"))

    def _paso_brazos(self, a, extra):
        ctx = self.ctx
        seg = ctx.seguridad
        seg.revisar_antes("brazos")
        if "pose" in a:
            if a["pose"] not in POSES:
                raise ErrorPlantilla(f"pose desconocida: {a['pose']}", pista=f"poses: {sorted(POSES)}")
            izq, der = POSES[a["pose"]]
        else:
            izq, der = a.get("izq"), a.get("der")
            if izq is None or der is None:
                raise ErrorPlantilla("'brazos' necesita 'izq' y 'der' con 7 valores cada uno, o una 'pose'")
        try:
            izq = lista_finita(izq, 7, "izq")
            der = lista_finita(der, 7, "der")
        except ErrorSeguridad as e:
            raise ErrorPlantilla(str(e), pista="'brazos' necesita 'izq' y 'der' con 7 numeros cada uno")
        ant_i, ant_d = ctx.ultimos_brazos
        delta = max(max(abs(x - y) for x, y in zip(izq, ant_i)), max(abs(x - y) for x, y in zip(der, ant_d)))
        vmax = float(ctx.cfg["teleop"].get("vel_art_max", 1.5))
        seg_ = max(finito(a.get("segundos", 0.0), "segundos"), delta / vmax)
        n = max(1, int(seg_ * 20))
        with seg.tren_superior_activo():
            for k in range(1, n + 1):
                if seg.parado:
                    raise ErrorSeguridad("parada de emergencia moviendo los brazos")
                seg.comprobar_alto()
                f = k / n
                nuevo_i = [x + (y - x) * f for x, y in zip(ant_i, izq)]
                nuevo_d = [x + (y - x) * f for x, y in zip(ant_d, der)]
                ctx.robot.brazos(nuevo_i, nuevo_d)
                ctx.ultimos_brazos = (nuevo_i, nuevo_d)        # lo realmente enviado, aunque se interrumpa
                time.sleep(seg_ / n)
            ctx.ultimos_brazos = (izq, der)

    def _paso_cabeza(self, a, extra):
        self.ctx.seguridad.revisar_antes("cabeza")
        self.ctx.robot.cabeza(_numero(a.get("yaw", 0.0), "yaw"), _numero(a.get("pitch", 0.0), "pitch"))

    def _paso_mano(self, a, extra):
        ctx = self.ctx
        ctx.seguridad.revisar_antes("manos")
        lado = a.get("lado", "ambas")
        lados = ("izquierda", "derecha") if lado == "ambas" else (lado,)
        if a.get("abrir"):
            valor = 1.0
        elif a.get("cerrar"):
            valor = 0.0
        else:
            valor = _numero(a.get("valor", 1.0), "valor")
        if not 0.0 <= valor <= 1.0:
            raise ErrorPlantilla(f"'valor' de la mano debe estar entre 0 (cerrada) y 1 (abierta): {valor}")
        for l in lados:
            if l not in ("izquierda", "derecha"):
                raise ErrorPlantilla(f"lado invalido: {l}", pista="izquierda, derecha o ambas")
            ctx.robot.mano(l, valor, a.get("tipo", "pinza"))

    def _paso_escuchar(self, a, extra):
        ctx = self.ctx
        if ctx.oido is None:
            raise ErrorVoz("no hay oido configurado", pista="usa --oido texto, panel o whisper")
        texto = ctx.oido.escuchar(timeout=float((a or {}).get("tiempo", 15)))
        ctx.variables[(a or {}).get("guardar_en", "oido")] = texto or ""

    def _paso_entender(self, a, extra):
        ctx = self.ctx
        if ctx.entendedor is None:
            raise ErrorVoz("la plantilla no define 'comandos'")
        texto = ctx.variables.get(a.get("de", "oido"), "")
        r = ctx.entendedor.entender(texto)
        ctx.variables[a.get("guardar_en", "accion")] = r.accion or ""

    def _paso_ejecutar_accion(self, a, extra):
        accion = a["accion"] if isinstance(a, dict) else a
        if not accion:
            return
        if accion not in self.ctx.comandos:
            raise ErrorPlantilla(f"accion desconocida: {accion}", pista=f"definidas: {sorted(self.ctx.comandos)}")
        self.pasos(self.ctx.comandos[accion]["pasos"])

    def _paso_voz_bucle(self, a, extra):
        """Escucha mientras ejecuta: la orden se corre en un hilo aparte para que 'para' la corte al instante."""
        ctx = self.ctx
        seg = ctx.seguridad
        a = a or {}
        if ctx.oido is None:
            raise ErrorVoz("no hay oido configurado", pista="usa --oido texto, panel o whisper")
        if ctx.entendedor is None:
            raise ErrorVoz("la plantilla no define 'comandos'")
        turnos = int(a.get("turnos", 0))
        salir = {normalizar(s) for s in a.get("salir", ["salir", "terminar", "adios"])}
        espera = float(a.get("escuchar_s", 20))
        ctx.habla.decir(a.get("saludo", "Te escucho."))
        trabajo = {"hilo": None, "fallo": None}

        def correr_comando(cid):
            try:
                self.pasos(ctx.comandos[cid]["pasos"])
            except Interrumpido:
                ctx.alertas.info(f"'{cid}' interrumpido")
            except ErrorSeguridad as e:
                trabajo["fallo"] = e
            except ErrorAndamio as e:
                ctx.alertas.error(f"no se pudo hacer '{cid}': {e}", pista=e.pista)
                ctx.habla.decir("No pude hacerlo.")
            except Exception as e:
                ctx.alertas.error(f"error inesperado en '{cid}': {e}")
                ctx.habla.decir("No pude hacerlo.")

        def ocupado():
            h = trabajo["hilo"]
            return h is not None and h.is_alive()

        n = 0
        try:
            while (turnos == 0 or n < turnos) and not seg.parado:
                if trabajo["fallo"] is not None:
                    raise trabajo["fallo"]
                texto = ctx.oido.escuchar(timeout=0.4 if ocupado() else espera)
                if not texto:
                    continue
                if salir & set(normalizar(texto).split()):
                    ctx.habla.decir("Hasta luego.")
                    if ocupado():
                        trabajo["hilo"].join(10.0)          # deja terminar lo que estaba haciendo
                    return
                n += 1
                r = ctx.entendedor.entender(texto)
                ctx.alertas.info(f'oido: "{texto}" -> {r.accion or "nada"} ({r.via})')
                if r.respuesta:
                    ctx.habla.decir(r.respuesta)
                if r.accion is None:
                    continue
                if r.accion == "parar":
                    seg.interrumpir()
                    if ocupado():
                        trabajo["hilo"].join(3.0)
                    seg.limpiar_alto()
                    ctx.alertas.aviso("parar por voz")
                    continue
                if r.accion not in ctx.comandos:
                    continue
                if ocupado():
                    ctx.habla.decir("Espera, estoy ocupado. Di para si quieres detenerme.")
                    continue
                seg.limpiar_alto()
                trabajo["hilo"] = threading.Thread(target=correr_comando, args=(r.accion,), daemon=True,
                                                   name="andamio-comando-voz")
                trabajo["hilo"].start()
            if trabajo["fallo"] is not None:
                raise trabajo["fallo"]
        finally:
            seg.interrumpir()
            if ocupado():
                trabajo["hilo"].join(5.0)
            seg.limpiar_alto()
        # al salir, esperar a que termine lo que quedo corriendo es innecesario: ya se interrumpio

    def _paso_teleop(self, a, extra):
        ctx = self.ctx
        if ctx.fabrica_teleop is None:
            raise NoSoportado("este modo de ejecucion no tiene teleoperacion",
                              pista="usa python -m andamio con --robot sim, x2 o remoto")
        a = a or {}
        puerto = int(a.get("puerto", ctx.cfg["teleop"]["puerto"]))
        grabar = bool(a.get("grabar", False))
        duracion = float(a.get("duracion", 0))
        teleop = ctx.fabrica_teleop(puerto)
        teleop.fijar_inicio(*ctx.ultimos_brazos)          # arranca desde donde estan los brazos
        if grabar and ctx.grabador is not None:
            ctx.grabador.iniciar(a.get("tarea", "teleop"), ctx.robot.nombre)
        try:
            with ctx.seguridad.tren_superior_activo():
                teleop.correr(duracion)
        finally:
            ctx.ultimos_brazos = (list(map(float, teleop.q_cmd["izquierda"])), list(map(float, teleop.q_cmd["derecha"])))
            if grabar and ctx.grabador is not None and ctx.grabador.activo:
                meta = ctx.grabador.parar()
                if meta:
                    ctx.alertas.info(f"episodio guardado: {meta.get('episodio')} ({meta.get('tramas')} tramas)")

    def _paso_mirar(self, a, extra):
        from ..autonomia import mirar
        mirar(self.ctx, a)

    def _paso_buscar(self, a, extra):
        from ..autonomia import buscar
        buscar(self.ctx, a)

    def _paso_acercarse(self, a, extra):
        from ..autonomia import acercarse
        acercarse(self.ctx, a)

    def _paso_repetir(self, a, extra):
        for i in range(int(a.get("veces", 1))):
            self.pasos(a["pasos"], {"i": i + 1})

    def _paso_grabar(self, a, extra):
        ctx = self.ctx
        if ctx.grabador is None:
            raise NoSoportado("no hay grabador configurado")
        ctx.grabador.iniciar(a.get("tarea", "sin_nombre"), ctx.robot.nombre)
        try:
            self.pasos(a["pasos"], extra)
        finally:
            meta = ctx.grabador.parar()
            if meta:
                ctx.alertas.info(f"episodio guardado: {meta.get('episodio')} ({meta.get('tramas')} tramas)")

    def _paso_si(self, a, extra):
        izq, op, der = _COND.match(str(a["cuando"])).groups()
        v1 = self._operando(izq, extra)
        v2 = self._operando(der, extra)
        comparar = {">=": lambda x, y: x >= y, "<=": lambda x, y: x <= y, "==": lambda x, y: x == y,
                    "!=": lambda x, y: x != y, ">": lambda x, y: x > y, "<": lambda x, y: x < y}[op]
        try:
            res = comparar(v1, v2)
        except TypeError:
            raise ErrorPlantilla(f"no se puede comparar {v1!r} con {v2!r}", pista="compara numero con numero o texto con texto")
        self.pasos(a.get("entonces", []) if res else a.get("si_no", []), extra)

    def _operando(self, texto, extra):
        crudo = texto.strip()
        entre_comillas = len(crudo) >= 2 and crudo[0] == crudo[-1] and crudo[0] in "'\""
        texto = crudo.strip("'\"")
        try:
            return float(texto)
        except ValueError:
            pass
        if entre_comillas:
            return texto
        if texto.lower() in ("verdadero", "true"):
            return True
        if texto.lower() in ("falso", "false"):
            return False
        if re.fullmatch(r"[A-Za-z_][\w.]*", texto):
            # un nombre se resuelve como variable o estado.*; si no existe es un error, no un texto
            # (para comparar con un texto, escribelo entre comillas)
            return _resolver(texto, self.ctx, extra)
        return texto


def _sustituir_args(nombre, args, ctx, extra):
    if nombre in ("repetir", "grabar", "si"):
        # solo se sustituyen los argumentos escalares; los pasos hijos se sustituyen al correrlos
        return {k: (v if k in ("pasos", "entonces", "si_no", "cuando") else _sustituir(v, ctx, extra))
                for k, v in args.items()} if isinstance(args, dict) else args
    return _sustituir(args, ctx, extra)
