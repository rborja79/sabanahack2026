"""Grabador de episodios de demostracion.

Cada episodio es un archivo JSONL: una linea por trama, mas un manifiesto.
El formato es plano a proposito, para poder cargarlo con pandas en una linea.
"""
import json, os, time, pathlib, uuid

RAIZ = pathlib.Path(__file__).resolve().parents[1] / "datos"


class Grabador:
    def __init__(self, raiz=None):
        self.raiz = pathlib.Path(raiz or RAIZ)
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.activo = False
        self.fh = None
        self.meta = {}
        self.n = 0

    def iniciar(self, tarea="sin_nombre", robot="", operador=""):
        if self.activo:
            self.parar()
        eid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        carpeta = self.raiz / eid
        carpeta.mkdir(parents=True, exist_ok=True)
        self.meta = {"episodio": eid, "tarea": tarea, "robot": robot, "operador": operador,
                     "inicio": time.time(), "tramas": 0}
        self.fh = open(carpeta / "tramas.jsonl", "w", encoding="utf-8")
        self.ruta = carpeta
        self.activo = True
        self.n = 0
        return eid

    def trama(self, obs, accion):
        if not self.activo:
            return
        self.fh.write(json.dumps({"i": self.n, "t": round(time.time(), 4),
                                  "obs": obs, "accion": accion}, ensure_ascii=False) + "\n")
        self.n += 1

    def parar(self):
        if not self.activo:
            return None
        self.fh.close()
        self.meta["tramas"] = self.n
        self.meta["fin"] = time.time()
        self.meta["duracion_s"] = round(self.meta["fin"] - self.meta["inicio"], 2)
        with open(self.ruta / "manifiesto.json", "w", encoding="utf-8") as fh:
            json.dump(self.meta, fh, ensure_ascii=False, indent=1)
        self.activo = False
        return dict(self.meta)
