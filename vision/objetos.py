"""Encuentra objetos en la mesa y los pasa al marco del robot.

Dos caminos: MediaPipe Tasks si esta el modelo (clases generales tipo taza,
botella, celular), y un detector por color que funciona siempre y sirve para
cubos o piezas marcadas.

    python objetos.py --fuente 0 --modo color --color naranja
    python objetos.py --fuente foto.jpg --modo modelo
"""
import argparse, json, os

import cv2
import numpy as np

from comun import imagen_a_robot

MODELO = os.path.join(os.path.dirname(__file__), "modelos", "efficientdet_lite0.tflite")

# Rangos en HSV de OpenCV: H va de 0 a 179.
COLORES = {
    "rojo": [((0, 120, 80), (8, 255, 255)), ((172, 120, 80), (179, 255, 255))],
    "naranja": [((9, 130, 100), (22, 255, 255))],
    "amarillo": [((23, 110, 110), (34, 255, 255))],
    "verde": [((38, 80, 60), (85, 255, 255))],
    "azul": [((90, 90, 60), (128, 255, 255))],
    "morado": [((129, 70, 50), (160, 255, 255))],
}


def por_color(cuadro, color="naranja", area_min=600):
    """Devuelve las manchas del color pedido, ordenadas de mayor a menor."""
    hsv = cv2.cvtColor(cv2.GaussianBlur(cuadro, (5, 5), 0), cv2.COLOR_BGR2HSV)
    mascara = None
    for lo, hi in COLORES[color]:
        m = cv2.inRange(hsv, np.array(lo), np.array(hi))
        mascara = m if mascara is None else cv2.bitwise_or(mascara, m)
    nucleo = np.ones((5, 5), np.uint8)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, nucleo)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, nucleo)
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    alto, ancho = cuadro.shape[:2]
    salida = []
    for c in contornos:
        area = cv2.contourArea(c)
        if area < area_min:
            continue
        x, y, w, h = cv2.boundingRect(c)
        salida.append({"clase": color, "score": round(float(area) / (ancho * alto), 4),
                       "caja": [x, y, w, h],
                       "centro": [(x + w / 2) / ancho, (y + h / 2) / alto],
                       "area_rel": round(float(area) / (ancho * alto), 5)})
    return sorted(salida, key=lambda d: -d["area_rel"])


def por_modelo(cuadro, ruta=MODELO, umbral=0.4):
    """Detector general de MediaPipe. Necesita el .tflite que baja setup.sh."""
    import mediapipe as mp
    from mediapipe.tasks import python as mpp
    from mediapipe.tasks.python import vision
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"falta {ruta}. Corre ./setup.sh")
    det = vision.ObjectDetector.create_from_options(vision.ObjectDetectorOptions(
        base_options=mpp.BaseOptions(model_asset_path=ruta),
        running_mode=vision.RunningMode.IMAGE, score_threshold=umbral))
    img = mp.Image(image_format=mp.ImageFormat.SRGB,
                   data=cv2.cvtColor(cuadro, cv2.COLOR_BGR2RGB))
    alto, ancho = cuadro.shape[:2]
    salida = []
    for d in det.detect(img).detections:
        c = d.bounding_box
        salida.append({"clase": d.categories[0].category_name,
                       "score": round(float(d.categories[0].score), 3),
                       "caja": [c.origin_x, c.origin_y, c.width, c.height],
                       "centro": [(c.origin_x + c.width / 2) / ancho,
                                  (c.origin_y + c.height / 2) / alto],
                       "area_rel": round(c.width * c.height / (ancho * alto), 5)})
    det.close()
    return sorted(salida, key=lambda d: -d["score"])


def a_objetivo(det, altura_mesa=0.78, cerca=0.5):
    """Pasa una deteccion al marco del robot para usarla como punto de agarre."""
    u, v = det["centro"]
    p = imagen_a_robot(u, v, cerca)
    p[2] = altura_mesa
    return p


def pintar(cuadro, dets):
    for d in dets:
        x, y, w, h = d["caja"]
        cv2.rectangle(cuadro, (x, y), (x + w, y + h), (80, 230, 200), 2)
        cv2.putText(cuadro, f"{d['clase']} {d['score']}", (x, max(16, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 230, 200), 2)
    return cuadro


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuente", default="0", help="indice de camara o ruta de imagen")
    ap.add_argument("--modo", default="color", choices=["color", "modelo"])
    ap.add_argument("--color", default="naranja", choices=list(COLORES))
    ap.add_argument("--umbral", type=float, default=0.4)
    ap.add_argument("--salida", default="", help="guarda el resultado en esta imagen")
    a = ap.parse_args()

    detectar = ((lambda c: por_color(c, a.color)) if a.modo == "color"
                else (lambda c: por_modelo(c, umbral=a.umbral)))

    if a.fuente.isdigit():
        cap = cv2.VideoCapture(int(a.fuente))
        while True:
            ok, cuadro = cap.read()
            if not ok:
                break
            dets = detectar(cuadro)
            cv2.imshow("objetos", pintar(cuadro, dets))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        cap.release()
        cv2.destroyAllWindows()
    else:
        cuadro = cv2.imread(a.fuente)
        dets = detectar(cuadro)
        print(json.dumps({"detecciones": dets,
                          "objetivo": a_objetivo(dets[0]) if dets else None},
                         indent=1, ensure_ascii=False))
        if a.salida:
            cv2.imwrite(a.salida, pintar(cuadro, dets))
