"""Puente entre el visor y el robot.

El visor manda la pose de las manos, el puente la convierte en objetivos para
el robot y devuelve la pose de cada pieza para que el visor la pinte.
"""
import argparse, asyncio, json, time
import numpy as np
import websockets

from sim import Robot
from recorder import Grabador


class Puente:
    def __init__(self, modelo="unitree_g1", hz=50, escala=1.0):
        self.robot = Robot(modelo)
        self.hz = hz
        self.escala = escala
        self.grabador = Grabador()
        self.anclas = {}          # lado -> (mano_ref, efector_ref)
        self.ultimas_manos = {}
        self.clientes = set()

    # ---------- calibracion ----------
    def anclar(self, lado, punto_mano):
        ef = self.robot.pos_efector(lado)
        if ef is None or punto_mano is None:
            return False
        self.anclas[lado] = (np.asarray(punto_mano, float), np.asarray(ef, float))
        return True

    def objetivo_desde_mano(self, lado, punto_mano):
        if lado not in self.anclas:
            if not self.anclar(lado, punto_mano):
                return None
        mano_ref, ef_ref = self.anclas[lado]
        return ef_ref + (np.asarray(punto_mano, float) - mano_ref) * self.escala

    # ---------- mensajes ----------
    def hola(self):
        return {"type": "hola", "robot": self.robot.modelo,
                "glb": f"/robots/{self.robot.modelo}.glb",
                "bodies": self.robot.nombres_body,
                "efectores": self.robot.efectores,
                "hz": self.hz}

    def recibir(self, msg):
        t = msg.get("type")
        if t == "manos":
            self.ultimas_manos = msg
            for lado in ("left", "right"):
                m = msg.get(lado)
                if not m or lado not in self.robot.efectores:
                    continue
                obj = self.objetivo_desde_mano(lado, m.get("p"))
                if obj is not None:
                    self.robot.fijar_objetivo(lado, obj)
        elif t == "cmd":
            c = msg.get("cmd")
            if c == "calibrar":
                self.anclas.clear()
                for lado in self.robot.efectores:
                    m = self.ultimas_manos.get(lado)
                    if m:
                        self.anclar(lado, m.get("p"))
                return {"type": "aviso", "texto": "calibrado"}
            if c == "reset":
                self.robot.reposo()
                self.anclas.clear()
                return {"type": "aviso", "texto": "robot en reposo"}
            if c == "grabar":
                eid = self.grabador.iniciar(msg.get("tarea", "sin_nombre"),
                                            self.robot.modelo, msg.get("operador", ""))
                return {"type": "grabando", "episodio": eid}
            if c == "parar":
                meta = self.grabador.parar()
                return {"type": "grabado", "meta": meta}
        return None

    def trama(self):
        self.robot.paso()
        p, q = self.robot.estado()
        if self.grabador.activo:
            obs = {"qpos": self.robot.qpos()}
            accion = {lado: (self.robot.objetivos.get(lado).tolist()
                             if self.robot.objetivos.get(lado) is not None else None)
                      for lado in self.robot.efectores}
            accion["manos"] = {k: v for k, v in self.ultimas_manos.items()
                               if k in ("left", "right", "head")}
            self.grabador.trama(obs, accion)
        return {"type": "estado", "t": round(time.time(), 4), "p": p, "q": q,
                "grabando": self.grabador.activo, "n": self.grabador.n}


async def manejar(ws, puente):
    puente.clientes.add(ws)
    await ws.send(json.dumps(puente.hola()))
    periodo = 1.0 / puente.hz

    async def enviar():
        while True:
            try:
                await ws.send(json.dumps(puente.trama()))
            except Exception:
                return
            await asyncio.sleep(periodo)

    tarea = asyncio.create_task(enviar())
    try:
        async for crudo in ws:
            try:
                respuesta = puente.recibir(json.loads(crudo))
            except Exception as e:
                respuesta = {"type": "error", "texto": str(e)[:200]}
            if respuesta:
                await ws.send(json.dumps(respuesta))
    except Exception:
        pass
    finally:
        tarea.cancel()
        puente.clientes.discard(ws)


async def principal(args):
    puente = Puente(args.modelo, args.hz, args.escala)
    print(f"puente listo · robot={args.modelo} · bodies={len(puente.robot.nombres_body)} · ws://0.0.0.0:{args.puerto}")
    async with websockets.serve(lambda ws: manejar(ws, puente), "0.0.0.0", args.puerto,
                                max_size=2 ** 22, ping_interval=20):
        await asyncio.Future()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default="unitree_g1")
    ap.add_argument("--puerto", type=int, default=8765)
    ap.add_argument("--hz", type=int, default=50)
    ap.add_argument("--escala", type=float, default=1.0)
    asyncio.run(principal(ap.parse_args()))
