"""El "ojo" del robot: de una imagen saca que hay, hacia donde esta y a que distancia.

Fuentes (todas devuelven lo mismo, asi las plantillas no cambian):

  camara     la camara del portatil (la del Mac sirve para ensayar: te pones delante)
  simulado   objetos imaginarios en el mundo; se ven segun la pose del robot falso
  x2         la camara RGB-D de la cabeza del X2 (ROS 2), con distancia por profundidad
  remoto     pide las detecciones al servidor del robot (servidor_robot --ojo x2)

Cada deteccion es un dict:
  clase      "persona", "botella", "silla"... (las 80 de COCO, en espanol)
  score      confianza 0..1
  cx, cy     posicion en la imagen: cx -1 = borde izquierdo, 0 = centro, +1 = borde derecho
  alto, ancho  tamano relativo de la caja (0..1)
  distancia  metros (por profundidad o estimada por tamano) o None
  origen     de donde salio la distancia: "profundidad", "tamano", "simulada" o None

Sin verificar con el robot delante: el formato exacto de la profundidad del X2 (se asume
16UC1 en milimetros) y que la imagen RGB y la de profundidad esten alineadas.
"""
import base64
import math
import pathlib
import threading
import time

from .nucleo.errores import ErrorRobot, NoSoportado

try:
    import numpy as np
except ImportError:  # el servidor del robot puede vivir sin numpy si no usa el ojo
    np = None

try:
    import cv2
except ImportError:
    cv2 = None

RAIZ_REPO = pathlib.Path(__file__).resolve().parents[1]
MODELO_YOLO = RAIZ_REPO / "vision" / "modelos" / "yolo11n.onnx"

COCO = [
    "persona", "bicicleta", "carro", "moto", "avion", "bus", "tren", "camion",
    "bote", "semaforo", "hidrante", "senal de pare", "parquimetro", "banca",
    "pajaro", "gato", "perro", "caballo", "oveja", "vaca", "elefante", "oso",
    "cebra", "jirafa", "mochila", "sombrilla", "bolso", "corbata", "maleta",
    "frisbee", "esquis", "tabla de nieve", "pelota", "cometa", "bate",
    "guante", "patineta", "tabla de surf", "raqueta", "botella", "copa",
    "vaso", "tenedor", "cuchillo", "cuchara", "tazon", "banano", "manzana",
    "sandwich", "naranja", "brocoli", "zanahoria", "perro caliente", "pizza",
    "dona", "torta", "silla", "sofa", "matera", "cama", "mesa", "inodoro",
    "television", "portatil", "mouse", "control", "teclado", "celular",
    "microondas", "horno", "tostadora", "lavaplatos", "nevera", "libro",
    "reloj", "florero", "tijeras", "peluche", "secador", "cepillo de dientes",
]

# Tamano real aproximado (alto, ancho) en metros para estimar la distancia sin profundidad.
TAMANOS = {
    "persona": (1.70, 0.45), "silla": (0.90, 0.45), "botella": (0.25, 0.07), "vaso": (0.12, 0.08),
    "copa": (0.15, 0.08), "tazon": (0.08, 0.15), "celular": (0.15, 0.07), "libro": (0.24, 0.17),
    "pelota": (0.22, 0.22), "mochila": (0.45, 0.30), "portatil": (0.25, 0.33), "perro": (0.60, 0.70),
    "gato": (0.30, 0.45), "peluche": (0.30, 0.25), "television": (0.60, 1.00), "mesa": (0.75, 1.20),
}


# ------------------------------------------------------------------ detector
class Detector:
    """YOLO11n con OpenCV (cv2.dnn). No necesita torch ni internet: el modelo viene en el repo."""

    def __init__(self, ruta=None, confianza=0.45, solapamiento=0.45, lado=640, clases=None):
        if cv2 is None or np is None:
            raise ErrorRobot("falta OpenCV para la vision", pista="pip install opencv-python numpy")
        ruta = pathlib.Path(ruta or MODELO_YOLO)
        if not ruta.exists():
            raise ErrorRobot(f"no esta el modelo de vision: {ruta}",
                             pista="viene en el repo en vision/modelos/yolo11n.onnx; haz git pull")
        try:
            self.red = cv2.dnn.readNetFromONNX(str(ruta))
        except Exception as e:
            raise ErrorRobot(f"OpenCV no pudo cargar el modelo: {e}", pista="actualiza opencv-python (>= 4.9)")
        self.confianza = float(confianza)
        self.clases = list(clases) if clases else COCO
        self.solapamiento = float(solapamiento)
        self.lado = int(lado)

    def detectar(self, bgr):
        """Devuelve [(clase, score, x, y, w, h)] en pixeles de la imagen original."""
        alto, ancho = bgr.shape[:2]
        e = self.lado / max(alto, ancho)
        nw, nh = int(round(ancho * e)), int(round(alto * e))
        lienzo = np.full((self.lado, self.lado, 3), 114, np.uint8)
        dx, dy = (self.lado - nw) // 2, (self.lado - nh) // 2
        lienzo[dy:dy + nh, dx:dx + nw] = cv2.resize(bgr, (nw, nh))
        blob = cv2.dnn.blobFromImage(lienzo, 1 / 255.0, (self.lado, self.lado), swapRB=True, crop=False)
        self.red.setInput(blob)
        salida = self.red.forward()[0].T          # (8400, 4 + N): 4 de caja + N clases
        puntajes = salida[:, 4:]
        if puntajes.shape[1] != len(self.clases):
            raise ErrorRobot(f"el modelo tiene {puntajes.shape[1]} clases y vision.clases tiene {len(self.clases)}",
                             pista="pon en vision.clases los nombres de tu modelo, en el mismo orden del data.yaml")
        mejor = puntajes.argmax(axis=1)
        valor = puntajes[np.arange(len(mejor)), mejor]
        sirve = valor >= self.confianza
        if not sirve.any():
            return []
        cajas, valor, mejor = salida[sirve, :4], valor[sirve], mejor[sirve]
        x = (cajas[:, 0] - cajas[:, 2] / 2 - dx) / e
        y = (cajas[:, 1] - cajas[:, 3] / 2 - dy) / e
        w, h = cajas[:, 2] / e, cajas[:, 3] / e
        rect = np.stack([x, y, w, h], axis=1)
        quedan = cv2.dnn.NMSBoxes(rect.tolist(), valor.tolist(), self.confianza, self.solapamiento)
        out = []
        for i in np.asarray(quedan).ravel().tolist():
            k = int(mejor[i])
            x0, y0 = max(0.0, float(x[i])), max(0.0, float(y[i]))
            x1, y1 = min(float(ancho), float(x[i] + w[i])), min(float(alto), float(y[i] + h[i]))
            out.append((self.clases[k], float(valor[i]), x0, y0, x1 - x0, y1 - y0))
        return out


def _ruta_modelo(ruta):
    """Rutas relativas se resuelven desde la raiz del repo (vision/modelos/mio.onnx)."""
    if not ruta:
        return None
    p = pathlib.Path(ruta)
    return p if p.is_absolute() or p.exists() else RAIZ_REPO / p


def _a_deteccion(clase, score, x, y, w, h, ancho, alto, fov_h, profundidad=None, escala_prof=0.001):
    cx = ((x + w / 2) / ancho) * 2 - 1
    cy = ((y + h / 2) / alto) * 2 - 1
    d, origen = None, None
    if profundidad is not None:
        d = _distancia_profundidad(profundidad, x, y, w, h, ancho, alto, escala_prof)
        origen = "profundidad" if d is not None else None
    if d is None:
        d = _distancia_tamano(clase, x, y, w, h, ancho, alto, fov_h)
        origen = "tamano" if d is not None else None
    return {"clase": clase, "score": round(score, 3), "cx": round(cx, 3), "cy": round(cy, 3),
            "alto": round(h / alto, 3), "ancho": round(w / ancho, 3),
            "distancia": None if d is None else round(d, 2), "origen": origen,
            "caja": [int(x), int(y), int(w), int(h)]}


def _distancia_tamano(clase, x, y, w, h, ancho, alto, fov_h):
    """Distancia aproximada con camara estenopeica y el tamano tipico del objeto."""
    if clase not in TAMANOS or w <= 1 or h <= 1:
        return None
    alto_real, ancho_real = TAMANOS[clase]
    fh = math.radians(fov_h)
    fv = 2 * math.atan(math.tan(fh / 2) * alto / ancho)
    cortada_v = y <= 2 or y + h >= alto - 2          # la caja toca arriba o abajo: el alto no sirve
    if cortada_v:
        return ancho_real / ((w / ancho) * 2 * math.tan(fh / 2))
    return alto_real / ((h / alto) * 2 * math.tan(fv / 2))


def _distancia_profundidad(prof, x, y, w, h, ancho, alto, escala):
    """Mediana de la profundidad en el centro de la caja (se re-escala si las imagenes no miden igual)."""
    ph, pw = prof.shape[:2]
    sx, sy = pw / ancho, ph / alto
    x0, x1 = int((x + w * 0.35) * sx), int((x + w * 0.65) * sx)
    y0, y1 = int((y + h * 0.35) * sy), int((y + h * 0.65) * sy)
    zona = prof[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)].astype("float32").ravel()
    zona = zona[np.isfinite(zona) & (zona > 0)]
    if zona.size < 5:
        return None
    d = float(np.median(zona)) * escala
    return d if 0.1 < d < 15 else None


# ------------------------------------------------------------------ ojos
class Ojo:
    """Interfaz comun. ver() nunca bloquea: devuelve lo ultimo que se vio (vacio si es viejo)."""
    nombre = "ojo"

    def __init__(self, cfg=None, alertas=None):
        self.cfg = (cfg or {}).get("vision", {}) if cfg else {}
        self.alertas = alertas
        self.decision = ""                 # lo que el comportamiento esta haciendo (se muestra en el panel)
        self._lock = threading.Lock()
        self._dets = []
        self._t = 0.0
        self._jpeg = None
        self.fps = 0.0

    def iniciar(self):
        pass

    def cerrar(self):
        pass

    def ver(self, clase=None, minimo=0.0, max_edad=1.0):
        with self._lock:
            if time.monotonic() - self._t > max_edad:
                return []
            dets = list(self._dets)
        return [d for d in dets if (clase is None or d["clase"] == clase) and d["score"] >= minimo]

    def jpeg(self):
        with self._lock:
            return self._jpeg

    def estado(self):
        return {"fuente": self.nombre, "fps": round(self.fps, 1), "decision": self.decision,
                "detecciones": [{k: d[k] for k in ("clase", "score", "cx", "distancia", "origen")} for d in self.ver()]}

    def _publicar(self, dets, jpeg=None):
        with self._lock:
            self._dets = dets
            self._t = time.monotonic()
            if jpeg is not None:
                self._jpeg = jpeg


class OjoImagenes(Ojo):
    """Recibe cuadros (de la webcam o del robot) y los procesa en su propio hilo, al ritmo que pueda."""
    nombre = "imagenes"

    def __init__(self, cfg=None, alertas=None, detector=None):
        super().__init__(cfg, alertas)
        self.fov_h = float(self.cfg.get("fov_h", 70.0))
        self.hz = float(self.cfg.get("hz", 8))
        self.escala_prof = float(self.cfg.get("escala_profundidad", 0.001))
        self.detector = detector or Detector(_ruta_modelo(self.cfg.get("modelo")), self.cfg.get("confianza", 0.45),
                                             clases=self.cfg.get("clases") or None)
        self._cuadro = None
        self._prof = None
        self._nuevo = threading.Event()
        self._fin = threading.Event()
        self._hilo = None

    def poner(self, bgr, profundidad=None):
        self._cuadro = bgr
        if profundidad is not None:
            self._prof = profundidad
        self._nuevo.set()

    def iniciar(self):
        if self._hilo is None:
            self._hilo = threading.Thread(target=self._procesar, daemon=True, name="andamio-ojo")
            self._hilo.start()

    def cerrar(self):
        self._fin.set()
        self._nuevo.set()

    def _procesar(self):
        periodo = 1.0 / max(1.0, self.hz)
        ultimo = 0.0
        while not self._fin.is_set():
            if not self._nuevo.wait(0.5):
                continue
            self._nuevo.clear()
            espera = periodo - (time.monotonic() - ultimo)
            if espera > 0:
                time.sleep(espera)
            cuadro, prof = self._cuadro, self._prof
            if cuadro is None:
                continue
            t0 = time.monotonic()
            try:
                crudas = self.detector.detectar(cuadro)
            except Exception as e:
                if self.alertas:
                    self.alertas.error(f"vision: fallo el detector: {e}")
                time.sleep(1.0)
                continue
            alto, ancho = cuadro.shape[:2]
            dets = sorted((_a_deteccion(*c, ancho, alto, self.fov_h, prof, self.escala_prof) for c in crudas),
                          key=lambda d: -d["score"])
            self._publicar(dets, self._pintar(cuadro, dets))
            dt = time.monotonic() - (ultimo or t0)
            ultimo = time.monotonic()
            self.fps = 0.8 * self.fps + 0.2 * (1.0 / dt if dt > 0 else 0)

    def _pintar(self, cuadro, dets):
        img = cuadro.copy()
        alto, ancho = img.shape[:2]
        if ancho > 640:
            e = 640 / ancho
            img = cv2.resize(img, (640, int(alto * e)))
        else:
            e = 1.0
        for d in dets:
            x, y, w, h = (int(v * e) for v in d["caja"])
            cv2.rectangle(img, (x, y), (x + w, y + h), (80, 200, 120), 2)
            txt = f"{d['clase']} {d['score']:.2f}" + (f" {d['distancia']:.1f}m" if d["distancia"] else "")
            cv2.putText(img, txt, (x + 3, max(14, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 200, 120), 2)
        cv2.line(img, (img.shape[1] // 2, 0), (img.shape[1] // 2, img.shape[0]), (120, 120, 120), 1)
        if self.decision:
            cv2.rectangle(img, (0, img.shape[0] - 28), (img.shape[1], img.shape[0]), (0, 0, 0), -1)
            cv2.putText(img, self.decision[:70], (8, img.shape[0] - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (255, 255, 255), 1)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else None


class OjoCamara(OjoImagenes):
    """La camara del portatil. En el Mac, la primera vez macOS pide permiso de camara para la Terminal."""
    nombre = "camara"

    def __init__(self, cfg=None, alertas=None, fuente=None, detector=None):
        super().__init__(cfg, alertas, detector)
        f = self.cfg.get("camara", 0) if fuente is None else fuente
        self.fuente = int(f) if str(f).isdigit() else f
        self._cap = None
        self._hilo_cap = None

    def iniciar(self):
        self._cap = cv2.VideoCapture(self.fuente)
        ok, cuadro = (self._cap.read() if self._cap.isOpened() else (False, None))
        if not ok:
            self._cap.release()
            raise ErrorRobot(f"no se pudo abrir la camara {self.fuente!r}",
                             pista="en el Mac: Ajustes del Sistema > Privacidad y seguridad > Camara > activa la "
                                   "Terminal y vuelve a abrirla; o prueba --param camara=1, o usa --ojo simulado")
        self.poner(cuadro)
        self._hilo_cap = threading.Thread(target=self._capturar, daemon=True, name="andamio-camara")
        self._hilo_cap.start()
        super().iniciar()
        if self.alertas:
            self.alertas.info(f"camara {self.fuente} abierta ({cuadro.shape[1]}x{cuadro.shape[0]})")

    def _capturar(self):
        fallos = 0
        while not self._fin.is_set():
            ok, cuadro = self._cap.read()
            if not ok:
                fallos += 1
                if fallos == 30 and self.alertas:
                    self.alertas.error("la camara dejo de entregar imagen", pista="revisa que otra app no la este usando")
                time.sleep(0.05)
                continue
            fallos = 0
            self.poner(cuadro)

    def cerrar(self):
        super().cerrar()
        if self._hilo_cap is not None:
            self._hilo_cap.join(1.0)
        if self._cap is not None:
            self._cap.release()


class OjoX2(OjoImagenes):
    """Camara RGB-D de la cabeza del X2. El driver se suscribe a los topicos y le pasa los cuadros."""
    nombre = "x2"

    def __init__(self, robot, cfg=None, alertas=None, detector=None):
        super().__init__(cfg, alertas, detector)
        if not hasattr(robot, "suscribir_camara"):
            raise NoSoportado(f"el robot {robot.nombre} no expone camara",
                              pista="usa --robot x2 (o el servidor del robot con --ojo x2)")
        self.robot = robot

    def iniciar(self):
        self.robot.suscribir_camara(self.poner)
        super().iniciar()


class OjoSimulado(Ojo):
    """Objetos imaginarios fijos en el mundo. Se ven o no segun la pose del robot (falso o sim).
    Sirve para probar los comportamientos de punta a punta sin camara."""
    nombre = "simulado"

    def __init__(self, robot, cfg=None, alertas=None, objetivos=None, hz=10):
        super().__init__(cfg, alertas)
        self.robot = robot
        self.fov_h = float(self.cfg.get("fov_h", 70.0))
        self.alcance = 8.0
        self.objetivos = [dict(o) for o in (objetivos if objetivos is not None else
                                            self.cfg.get("objetivos_simulados") or [])]
        self.hz = hz
        self._fin = threading.Event()
        self._hilo = None

    def iniciar(self):
        if self._hilo is None:
            self._hilo = threading.Thread(target=self._bucle, daemon=True, name="andamio-ojo-sim")
            self._hilo.start()

    def cerrar(self):
        self._fin.set()

    def calcular(self):
        try:
            pose = self.robot.estado().get("pose") or [0.0, 0.0, 0.0]
        except Exception:
            return []
        x, y, yaw = (float(v) for v in pose[:3])
        dets = []
        for o in self.objetivos:
            dx, dy = float(o["x"]) - x, float(o["y"]) - y
            d = math.hypot(dx, dy)
            ang = math.atan2(dy, dx) - yaw
            ang = math.atan2(math.sin(ang), math.cos(ang))       # -pi..pi, positivo = a la izquierda
            if d > self.alcance or d < 0.05 or abs(ang) > math.radians(self.fov_h) / 2:
                continue
            alto_real = TAMANOS.get(o["clase"], (0.5, 0.5))[0]
            fv = 2 * math.atan(math.tan(math.radians(self.fov_h) / 2) * 0.75)
            h = min(1.0, alto_real / (d * 2 * math.tan(fv / 2)))
            dets.append({"clase": o["clase"], "score": 0.9, "cx": round(-ang / (math.radians(self.fov_h) / 2), 3),
                         "cy": 0.0, "alto": round(h, 3), "ancho": round(h * 0.3, 3), "distancia": round(d, 2),
                         "origen": "simulada", "caja": [0, 0, 0, 0]})
        return sorted(dets, key=lambda e: e["distancia"])

    def _bucle(self):
        while not self._fin.is_set():
            t0 = time.monotonic()
            dets = self.calcular()
            self._publicar(dets, self._pintar(dets))
            self.fps = self.hz
            self._fin.wait(max(0.0, 1.0 / self.hz - (time.monotonic() - t0)))

    def _pintar(self, dets):
        if cv2 is None or np is None:
            return None
        ancho, alto = 640, 360
        img = np.full((alto, ancho, 3), 40, np.uint8)
        img[alto // 2:] = (60, 70, 60)
        for d in dets:
            h = int(d["alto"] * alto)
            w = max(8, int(h * 0.35))
            cx = int((d["cx"] + 1) / 2 * ancho)
            y0 = alto // 2 + int(alto * 0.15) - h // 2
            cv2.rectangle(img, (cx - w // 2, y0), (cx + w // 2, y0 + h), (80, 200, 120), 2)
            cv2.putText(img, f"{d['clase']} {d['distancia']:.1f}m", (cx - w // 2, max(14, y0 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 200, 120), 2)
        cv2.line(img, (ancho // 2, 0), (ancho // 2, alto), (120, 120, 120), 1)
        cv2.putText(img, "vista simulada", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        if self.decision:
            cv2.rectangle(img, (0, alto - 28), (ancho, alto), (0, 0, 0), -1)
            cv2.putText(img, self.decision[:70], (8, alto - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else None

    def estado(self):
        e = super().estado()
        e["objetivos"] = self.objetivos
        return e


class OjoRemoto(Ojo):
    """Le pide al servidor del robot lo que ve su camara (el detector corre alla)."""
    nombre = "remoto"

    def __init__(self, robot, cfg=None, alertas=None, hz=8):
        super().__init__(cfg, alertas)
        if not hasattr(robot, "ver_remoto"):
            raise NoSoportado("el ojo remoto necesita --robot remoto")
        self.robot = robot
        self.hz = hz
        self._fin = threading.Event()
        self._hilo = None
        self._t_foto = 0.0

    def iniciar(self):
        self.robot.ver_remoto()          # falla aqui, con pista, si el servidor no tiene ojo
        self._hilo = threading.Thread(target=self._bucle, daemon=True, name="andamio-ojo-remoto")
        self._hilo.start()

    def cerrar(self):
        self._fin.set()

    def _bucle(self):
        fallos = 0
        while not self._fin.is_set():
            t0 = time.monotonic()
            try:
                dets = self.robot.ver_remoto()
                fallos = 0
                foto = None
                if time.monotonic() - self._t_foto > 0.5:
                    self._t_foto = time.monotonic()
                    b64 = self.robot.foto_remota()
                    foto = base64.b64decode(b64) if b64 else None
                self._publicar(dets, foto)
                self.fps = 0.8 * self.fps + 0.2 / max(1e-3, time.monotonic() - t0)
            except Exception as e:
                fallos += 1
                if fallos in (1, 50) and self.alertas:
                    self.alertas.aviso(f"vision remota: {e}")
            self._fin.wait(max(0.0, 1.0 / self.hz - (time.monotonic() - t0)))


OJOS = ("ninguno", "camara", "simulado", "x2", "remoto")


def crear_ojo(tipo, robot, cfg, alertas):
    if not tipo or tipo == "ninguno":
        return None
    if tipo == "camara":
        return OjoCamara(cfg, alertas)
    if tipo == "simulado":
        return OjoSimulado(robot, cfg, alertas)
    if tipo == "x2":
        return OjoX2(robot, cfg, alertas)
    if tipo == "remoto":
        return OjoRemoto(robot, cfg, alertas)
    raise ErrorRobot(f"ojo desconocido: {tipo}", pista=f"opciones: {', '.join(OJOS)}")
