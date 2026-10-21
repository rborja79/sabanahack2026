"""Encuentra objetos en la mesa y los pasa al marco del robot.

Tres caminos:

- `onnx`: YOLO11n sobre OpenCV. Reconoce 80 clases de COCO, incluidas botella,
  vaso, tazon, celular, libro y tijeras. El modelo viene en el repo, no hay
  nada que descargar y corre igual en Windows, macOS y Linux.
- `color`: manchas de un color. Util para cubos o piezas marcadas, y es el mas
  rapido de todos.
- `modelo`: MediaPipe Tasks, si bajo su .tflite.

    python objetos.py --fuente 0 --modo onnx
    python objetos.py --fuente foto.jpg --modo onnx --salida vista.png
    python objetos.py --fuente 0 --modo color --color naranja
"""
import argparse, json, os

import cv2
import numpy as np

from comun import imagen_a_robot

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELO = os.path.join(AQUI, "modelos", "efficientdet_lite0.tflite")
ONNX = os.path.join(AQUI, "modelos", "yolo11n.onnx")
LADO = 640

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


def _encajar(cuadro, lado=LADO):
    """Redimensiona sin deformar y rellena con gris. Devuelve escala y margen."""
    alto, ancho = cuadro.shape[:2]
    e = min(lado / ancho, lado / alto)
    nw, nh = int(round(ancho * e)), int(round(alto * e))
    lienzo = np.full((lado, lado, 3), 114, np.uint8)
    dx, dy = (lado - nw) // 2, (lado - nh) // 2
    lienzo[dy:dy + nh, dx:dx + nw] = cv2.resize(cuadro, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return lienzo, e, dx, dy


_RED = {}


def _red(ruta=ONNX):
    """Carga la red una sola vez."""
    if ruta not in _RED:
        if not os.path.exists(ruta):
            raise FileNotFoundError(f"falta {ruta}")
        r = cv2.dnn.readNetFromONNX(ruta)
        r.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        r.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        _RED[ruta] = r
    return _RED[ruta]


def por_onnx(cuadro, ruta=ONNX, umbral=0.35, solapamiento=0.45, clases=None):
    """YOLO11n con OpenCV. No necesita torch ni descargar nada."""
    from clases_coco import COCO
    alto, ancho = cuadro.shape[:2]
    lienzo, e, dx, dy = _encajar(cuadro)
    blob = cv2.dnn.blobFromImage(lienzo, 1 / 255.0, (LADO, LADO), swapRB=True, crop=False)
    red = _red(ruta)
    red.setInput(blob)
    # Sale (1, 84, 8400): 4 de caja y 80 de clase, una columna por candidato.
    salida = red.forward()[0].T
    puntajes = salida[:, 4:]
    mejor = puntajes.argmax(axis=1)
    valor = puntajes[np.arange(len(mejor)), mejor]
    sirve = valor >= umbral
    if not sirve.any():
        return []
    cajas, valor, mejor = salida[sirve, :4], valor[sirve], mejor[sirve]
    # De centro y tamano a esquina, deshaciendo el relleno.
    x = (cajas[:, 0] - cajas[:, 2] / 2 - dx) / e
    y = (cajas[:, 1] - cajas[:, 3] / 2 - dy) / e
    w, h = cajas[:, 2] / e, cajas[:, 3] / e
    rect = np.stack([x, y, w, h], axis=1)
    quedan = cv2.dnn.NMSBoxes(rect.tolist(), valor.tolist(), umbral, solapamiento)
    salida_final = []
    for i in np.asarray(quedan).ravel().tolist():
        nombre = COCO[int(mejor[i])] if int(mejor[i]) < len(COCO) else str(mejor[i])
        if clases and nombre not in clases:
            continue
        bx = [int(max(0, x[i])), int(max(0, y[i])),
              int(min(w[i], ancho)), int(min(h[i], alto))]
        salida_final.append({"clase": nombre, "score": round(float(valor[i]), 3),
                             "caja": bx,
                             "centro": [(bx[0] + bx[2] / 2) / ancho, (bx[1] + bx[3] / 2) / alto],
                             "area_rel": round(bx[2] * bx[3] / (ancho * alto), 5)})
    return sorted(salida_final, key=lambda d: -d["score"])


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
    ap.add_argument("--modo", default="onnx", choices=["onnx", "color", "modelo"])
    ap.add_argument("--color", default="naranja", choices=list(COLORES))
    ap.add_argument("--umbral", type=float, default=0.35)
    ap.add_argument("--clases", default="", help="lista separada por comas para filtrar")
    ap.add_argument("--salida", default="", help="guarda el resultado en esta imagen")
    a = ap.parse_args()

    filtro = [x.strip() for x in a.clases.split(",") if x.strip()] or None
    if a.modo == "color":
        detectar = lambda c: por_color(c, a.color)
    elif a.modo == "onnx":
        detectar = lambda c: por_onnx(c, umbral=a.umbral, clases=filtro)
    else:
        detectar = lambda c: por_modelo(c, umbral=a.umbral)

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
