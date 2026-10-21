"""Visor de mentiras: mueve el robot sin navegador y sin visor.

Se conecta al puente como lo haria el visor, dibuja un circulo con la mano
derecha, graba el episodio y revisa que lo grabado se parezca a lo pedido.
Sirve para probar toda la cadena en una terminal, y para dejar datos de prueba.

    python cliente_prueba.py --tramas 120 --radio 0.12
"""
import argparse, asyncio, json, math, time

import numpy as np
import websockets


async def principal(args):
    async with websockets.connect(args.servidor, max_size=2 ** 22) as ws:
        hola = json.loads(await ws.recv())
        if hola.get("type") != "hola":
            raise SystemExit(f"el puente no saludo: {hola}")
        print(f"conectado · robot {hola['robot']} · {len(hola['bodies'])} piezas")

        centro = np.array([0.0, 0.30, 1.05])
        pedidos, recibidos = [], []

        async def mandar(p, pinza=1.0):
            await ws.send(json.dumps({"type": "manos",
                                      "right": {"p": [float(v) for v in p], "pinza": pinza},
                                      "head": {"p": [0.0, 0.0, 1.6]}}))

        async def leer_estado(hasta=0.1):
            """Vacia la cola y devuelve la ultima trama de estado."""
            ultimo = None
            fin = time.time() + hasta
            while time.time() < fin:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=hasta))
                except asyncio.TimeoutError:
                    break
                if m.get("type") == "estado":
                    ultimo = m
            return ultimo

        # 1. ancla la mano en el centro y calibra
        await mandar(centro)
        await leer_estado(0.4)
        await ws.send(json.dumps({"type": "cmd", "cmd": "calibrar"}))
        await leer_estado(0.3)

        # 2. graba
        await ws.send(json.dumps({"type": "cmd", "cmd": "grabar", "tarea": args.tarea}))
        await leer_estado(0.3)

        # 3. dibuja el circulo
        idx = hola["bodies"].index(hola["efectores"]["right"])
        for i in range(args.tramas):
            a = 2 * math.pi * i / args.tramas
            p = centro + np.array([args.radio * math.cos(a), 0.0, args.radio * math.sin(a)])
            await mandar(p)
            est = await leer_estado(1.0 / args.hz)
            if est:
                pedidos.append(p.copy())
                recibidos.append(est["p"][idx * 3:idx * 3 + 3])

        # 4. para y revisa
        await ws.send(json.dumps({"type": "cmd", "cmd": "parar"}))
        meta = None
        fin = time.time() + 2
        while time.time() < fin:
            m = json.loads(await ws.recv())
            if m.get("type") == "grabado":
                meta = m["meta"]
                break

        # La calibracion por ancla suma un desfase fijo entre tu mano y la del
        # robot, asi que lo que se compara es el movimiento, no la posicion.
        ped, rec = np.array(pedidos), np.array(recibidos)
        ped -= ped.mean(axis=0)
        rec -= rec.mean(axis=0)
        err = np.linalg.norm(ped - rec, axis=1)
        radio_real = np.linalg.norm(rec, axis=1).mean()
        print(f"tramas enviadas {len(ped)} · error de seguimiento medio "
              f"{err.mean()*1000:.1f} mm · maximo {err.max()*1000:.1f} mm")
        print(f"radio pedido {args.radio:.3f} m · radio seguido {radio_real:.3f} m")
        if meta:
            print(f"episodio {meta['episodio']} · {meta['tramas']} tramas en datos/")
        ok = err.mean() < 0.03 and abs(radio_real - args.radio) < 0.03
        print("prueba OK" if ok else "la mano no siguio bien, revisa escala o alcance")
        return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--servidor", default="ws://localhost:8765")
    ap.add_argument("--tramas", type=int, default=120)
    ap.add_argument("--radio", type=float, default=0.12)
    ap.add_argument("--hz", type=int, default=50)
    ap.add_argument("--tarea", default="prueba_circulo")
    raise SystemExit(asyncio.run(principal(ap.parse_args())))
