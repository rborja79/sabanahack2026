"""Grabador de episodios, con el mismo formato que bridge/recorder.py.

Cada episodio es una carpeta con tramas.jsonl (una linea por trama) y manifiesto.json.
"""
import json
import pathlib
import threading
import time
import uuid

RAIZ = pathlib.Path(__file__).resolve().parents[1] / "datos"


class Grabador:
    def __init__(self, raiz=None):
        self.raiz = pathlib.Path(raiz or RAIZ)
        self._lock = threading.Lock()
        self.activo = False
        self.fh = None
        self.meta = {}
        self.ruta = None
        self.n = 0

    def iniciar(self, tarea="sin_nombre", robot="", operador=""):
        with self._lock:
            if self.activo:
                self._cerrar()
            self.raiz.mkdir(parents=True, exist_ok=True)
            eid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
            self.ruta = self.raiz / eid
            self.ruta.mkdir(parents=True, exist_ok=True)
            self.meta = {"episodio": eid, "tarea": tarea, "robot": robot, "operador": operador,
                         "inicio": time.time(), "tramas": 0}
            self.fh = open(self.ruta / "tramas.jsonl", "w", encoding="utf-8")
            self.activo = True
            self.n = 0
            return eid

    def trama(self, obs, accion):
        with self._lock:
            if not self.activo:
                return
            self.fh.write(json.dumps({"i": self.n, "t": round(time.time(), 4), "obs": obs, "accion": accion},
                                     ensure_ascii=False, default=str) + "\n")
            self.n += 1

    def _cerrar(self):
        self.fh.close()
        self.meta["tramas"] = self.n
        self.meta["fin"] = time.time()
        self.meta["duracion_s"] = round(self.meta["fin"] - self.meta["inicio"], 2)
        with open(self.ruta / "manifiesto.json", "w", encoding="utf-8") as fh:
            json.dump(self.meta, fh, ensure_ascii=False, indent=1)
        self.activo = False
        return dict(self.meta)

    def parar(self):
        with self._lock:
            if not self.activo:
                return None
            return self._cerrar()
