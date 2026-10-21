"""Teleoperacion con la camara del portatil, sin visor y sin marcadores.

Usa MediaPipe Tasks para leer las manos. La profundidad se estima con el tamano
aparente de la mano, asi que es menos exacta que ArUco, pero no hay que imprimir
nada. Necesita el modelo hand_landmarker.task, que baja setup.sh.

    python manos.py --servidor ws://localhost:8765
"""
import argparse, asyncio, json, math, os, time

import cv2
import numpy as np

from comun import Suavizado, imagen_a_robot

MODELO = os.path.join(os.path.dirname(__file__), "modelos", "hand_landmarker.task")
MUNECA, PULGAR, INDICE = 0, 4, 8


def crear_lector(ruta=MODELO, manos=2, confianza=0.5):
    """Arma el detector de MediaPipe en modo video."""
    from mediapipe.tasks import python as mpp
    from mediapipe.tasks.python import vision
    if not os.path.exists(ruta):
        raise FileNotFoundError(
            f"falta {ruta}. Corre ./setup.sh o bajalo de "
            "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
            "hand_landmarker/float16/1/hand_landmarker.task")
    opciones = vision.HandLandmarkerOptions(
        base_options=mpp.BaseOptions(model_asset_path=ruta),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=manos,
        min_hand_detection_confidence=confianza,
        min_tracking_confidence=confianza)
    return vision.HandLandmarker.create_from_options(opciones)


def extension(puntos):
    """Tamano aparente de la mano en la imagen, de 0 a 1."""
    xs = [p.x for p in puntos]
    ys = [p.y for p in puntos]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def apertura(puntos):
    """0 es pinza cerrada, 1 es abierta."""
    a, b = puntos[PULGAR], puntos[INDICE]
    d = math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
    return round(float(np.clip(d / 0.18, 0.0, 1.0)), 3)


def pose_mano(puntos, cerca_min=0.12, cerca_max=0.34):
    """Convierte una mano detectada en un punto del marco del robot."""
    mu = puntos[MUNECA]
    cerca = float(np.clip((extension(puntos) - cerca_min) / (cerca_max - cerca_min), 0, 1))
    return imagen_a_robot(mu.x, mu.y, cerca), apertura(puntos)


def dibujar(cuadro, puntos, color):
    alto, ancho = cuadro.shape[:2]
    for p in puntos:
        cv2.circle(cuadro, (int(p.x * ancho), int(p.y * alto)), 3, color, -1)


async def principal(args):
    import mediapipe as mp
    import websockets
    lector = crear_lector(args.modelo, confianza=args.confianza)
    cap = cv2.VideoCapture(args.camara)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
    suave = {}
    print(f"camara lista · enviando a {args.servidor} · q sale, c calibra, r reposo, g graba")
    grabando = False
    t0 = time.time()
    async with websockets.connect(args.servidor, max_size=2 ** 22) as ws:
        ultimo = 0.0
        while True:
            ok, cuadro = cap.read()
            if not ok:
                break
            cuadro = cv2.flip(cuadro, 1)
            rgb = mp.Image(image_format=mp.ImageFormat.SRGB,
                           data=cv2.cvtColor(cuadro, cv2.COLOR_BGR2RGB))
            res = lector.detect_for_video(rgb, int((time.time() - t0) * 1000))
            datos = {}
            for puntos, info in zip(res.hand_landmarks, res.handedness):
                # La imagen va en espejo, asi que la etiqueta se invierte.
                lado = "right" if info[0].category_name == "Left" else "left"
                p, pinza = pose_mano(puntos)
                suave.setdefault(lado, Suavizado())
                datos[lado] = {"p": [round(v, 4) for v in suave[lado](p)],
                               "pinza": pinza, "fuente": "camara"}
                dibujar(cuadro, puntos, (80, 230, 200) if lado == "left" else (85, 173, 246))
            ahora = time.time()
            if datos and ahora - ultimo > 1.0 / args.hz:
                ultimo = ahora
                await ws.send(json.dumps({"type": "manos", **datos}))
            if not args.sin_ventana:
                cv2.putText(cuadro, f"manos: {len(datos)} {'GRABANDO' if grabando else ''}",
                            (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 230, 200), 2)
                cv2.imshow("manos", cuadro)
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
    ap.add_argument("--modelo", default=MODELO)
    ap.add_argument("--confianza", type=float, default=0.5)
    ap.add_argument("--hz", type=int, default=30)
    ap.add_argument("--tarea", default="camara")
    ap.add_argument("--sin-ventana", action="store_true")
    asyncio.run(principal(ap.parse_args()))
