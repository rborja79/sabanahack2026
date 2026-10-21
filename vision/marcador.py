"""Teleoperacion con marcadores ArUco y una camara cualquiera.

Imprime los marcadores (python marcador.py --imprimir), pegalos a un guante o a
un palo, y la camara te da la posicion en 3D de verdad, sin adivinar la
profundidad y sin descargar ningun modelo.

    python marcador.py --servidor ws://localhost:8765 --lado-marcador 0.05
"""
import argparse, asyncio, json, time

import cv2
import numpy as np

from comun import Suavizado, camara_por_defecto, cargar_calibracion

DICC = cv2.aruco.DICT_4X4_50
# Que id de marcador controla cada mano.
IDS = {0: "left", 1: "right"}


def esquinas_objeto(lado):
    """Esquinas del marcador en su propio marco, en metros."""
    m = lado / 2.0
    return np.array([[-m, m, 0], [m, m, 0], [m, -m, 0], [-m, -m, 0]], float)


def hoja_para_imprimir(ruta, ids=(0, 1), px=700):
    """Genera un PNG con los marcadores listos para imprimir."""
    d = cv2.aruco.getPredefinedDictionary(DICC)
    hoja = np.full((px + 120, px * len(ids) + 60 * (len(ids) + 1)), 255, "uint8")
    for i, mid in enumerate(ids):
        img = cv2.aruco.generateImageMarker(d, mid, px)
        x = 60 + i * (px + 60)
        hoja[60:60 + px, x:x + px] = img
        cv2.putText(hoja, f"id {mid} -> {IDS.get(mid, '?')}", (x, px + 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3)
    cv2.imwrite(ruta, hoja)
    return ruta


class Rastreador:
    """Encuentra los marcadores en un cuadro y devuelve su pose en metros."""

    def __init__(self, lado=0.05, K=None, dist=None):
        self.lado = lado
        self.obj = esquinas_objeto(lado)
        self.K = K
        self.dist = np.zeros(5) if dist is None else dist
        self.det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(DICC),
                                           cv2.aruco.DetectorParameters())
        self.suave = {}

    def procesar(self, cuadro, dibujar=True):
        alto, ancho = cuadro.shape[:2]
        if self.K is None:
            self.K = camara_por_defecto(ancho, alto)
        gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY) if cuadro.ndim == 3 else cuadro
        esquinas, ids, _ = self.det.detectMarkers(gris)
        salida = {}
        if ids is None:
            return salida
        for esq, mid in zip(esquinas, ids.ravel().tolist()):
            lado = IDS.get(int(mid))
            if lado is None:
                continue
            ok, rvec, tvec = cv2.solvePnP(self.obj, esq.reshape(4, 2).astype(float),
                                          self.K, self.dist, flags=cv2.SOLVEPNP_IPPE_SQUARE)
            if not ok:
                continue
            # Camara: x derecha, y abajo, z al frente. Robot: x derecha, y al
            # frente, z arriba. La camara mira al operador, asi que x se invierte.
            t = tvec.ravel()
            p = [-float(t[0]), float(t[2]), -float(t[1])]
            if lado not in self.suave:
                self.suave[lado] = Suavizado()
            salida[lado] = {"p": [round(v, 4) for v in self.suave[lado](p)],
                            "pinza": 1.0, "fuente": "aruco",
                            "rvec": [round(float(v), 4) for v in rvec.ravel()]}
            if dibujar and cuadro.ndim == 3:
                cv2.aruco.drawDetectedMarkers(cuadro, [esq], np.array([[mid]]))
                cv2.drawFrameAxes(cuadro, self.K, self.dist, rvec, tvec, self.lado)
        return salida


async def principal(args):
    import websockets
    K = dist = None
    if args.calibracion:
        K, dist = cargar_calibracion(args.calibracion)
    rastreador = Rastreador(args.lado_marcador, K, dist)
    cap = cv2.VideoCapture(args.camara)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
    print(f"camara lista · enviando a {args.servidor} · q sale, c calibra, r reposo, g graba")
    grabando = False
    async with websockets.connect(args.servidor, max_size=2 ** 22) as ws:
        ultimo = 0.0
        while True:
            ok, cuadro = cap.read()
            if not ok:
                break
            datos = rastreador.procesar(cuadro)
            ahora = time.time()
            if datos and ahora - ultimo > 1.0 / args.hz:
                ultimo = ahora
                await ws.send(json.dumps({"type": "manos", **datos}))
            if not args.sin_ventana:
                cv2.putText(cuadro, f"marcadores: {len(datos)} {'GRABANDO' if grabando else ''}",
                            (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 230, 200), 2)
                cv2.imshow("aruco", cuadro)
                t = cv2.waitKey(1) & 0xFF
                if t == ord("q"):
                    break
                if t in (ord("c"), ord("r")):
                    await ws.send(json.dumps({"type": "cmd",
                                              "cmd": "calibrar" if t == ord("c") else "reset"}))
                if t == ord("g"):
                    grabando = not grabando
                    await ws.send(json.dumps({"type": "cmd",
                                              "cmd": "grabar" if grabando else "parar",
                                              "tarea": args.tarea}))
            await asyncio.sleep(0)
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--servidor", default="ws://localhost:8765")
    ap.add_argument("--camara", type=int, default=0)
    ap.add_argument("--lado-marcador", type=float, default=0.05, help="lado impreso en metros")
    ap.add_argument("--calibracion", default="")
    ap.add_argument("--hz", type=int, default=30)
    ap.add_argument("--tarea", default="aruco")
    ap.add_argument("--sin-ventana", action="store_true")
    ap.add_argument("--imprimir", default="", help="guarda la hoja de marcadores en este PNG")
    a = ap.parse_args()
    if a.imprimir:
        print("hoja guardada en", hoja_para_imprimir(a.imprimir))
    else:
        asyncio.run(principal(a))
