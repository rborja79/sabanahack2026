"""Alertas: lo que el operador debe ver, en consola, en el panel y en un archivo."""
import json
import sys
import threading
import time
from collections import deque

NIVELES = {"info": 10, "aviso": 20, "error": 30, "critico": 40}
_COLOR = {"info": "\033[36m", "aviso": "\033[33m", "error": "\033[31m", "critico": "\033[1;37;41m"}


class Alertas:
    def __init__(self, archivo=None, maximo=300, consola=True, nivel_minimo="info", sonido=True, salida=None):
        self._lock = threading.Lock()
        self._recientes = deque(maxlen=maximo)
        self._suscriptores = []
        self.archivo = archivo
        self.consola = consola
        self.sonido = sonido
        self.nivel_minimo = NIVELES[nivel_minimo]
        self.salida = salida or sys.stderr
        self.conteo = {k: 0 for k in NIVELES}
        self._fh = None
        if archivo:
            try:
                self._fh = open(archivo, "a", encoding="utf-8")
            except OSError:
                self._fh = None

    # ---------- emitir ----------
    def emitir(self, nivel, mensaje, pista="", **datos):
        if nivel not in NIVELES:
            nivel = "aviso"
        registro = {"t": round(time.time(), 3), "nivel": nivel, "mensaje": str(mensaje)}
        if pista:
            registro["pista"] = str(pista)
        if datos:
            registro["datos"] = datos
        with self._lock:
            self.conteo[nivel] += 1
            self._recientes.append(registro)
            suscriptores = list(self._suscriptores)
            if self._fh:
                try:
                    self._fh.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")
                    self._fh.flush()
                except (OSError, ValueError):
                    pass
        if self.consola and NIVELES[nivel] >= self.nivel_minimo:
            self._escribir(registro)
        for cb in suscriptores:
            try:
                cb(registro)
            except Exception:
                pass
        return registro

    def info(self, mensaje, **kw):
        return self.emitir("info", mensaje, **kw)

    def aviso(self, mensaje, **kw):
        return self.emitir("aviso", mensaje, **kw)

    def error(self, mensaje, **kw):
        return self.emitir("error", mensaje, **kw)

    def critico(self, mensaje, **kw):
        return self.emitir("critico", mensaje, **kw)

    # ---------- consulta ----------
    def recientes(self, n=50):
        with self._lock:
            return list(self._recientes)[-n:]

    def suscribir(self, callback):
        with self._lock:
            self._suscriptores.append(callback)

    def hubo(self, nivel="error"):
        minimo = NIVELES[nivel]
        return any(self.conteo[k] for k, v in NIVELES.items() if v >= minimo)

    def cerrar(self):
        with self._lock:
            if self._fh:
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None

    # ---------- consola ----------
    def _escribir(self, r):
        hora = time.strftime("%H:%M:%S", time.localtime(r["t"]))
        etiqueta = r["nivel"].upper().ljust(7)
        tty = getattr(self.salida, "isatty", lambda: False)()
        if tty:
            linea = f"{hora} {_COLOR[r['nivel']]}{etiqueta}\033[0m {r['mensaje']}"
        else:
            linea = f"{hora} {etiqueta} {r['mensaje']}"
        if r.get("pista"):
            linea += f"\n         -> {r['pista']}"
        try:
            self.salida.write(linea + "\n")
            if r["nivel"] == "critico" and self.sonido and tty:
                self.salida.write("\a")
            self.salida.flush()
        except (OSError, ValueError):
            pass
