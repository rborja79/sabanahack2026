"""Comparte la camara de este equipo por la red local como video MJPEG.

Sirve para usar la webcam de Windows desde WSL2 (WSL2 no ve la camara del portatil):

  En Windows (doble clic en 'Probar en Windows.bat', opcion 8, o):
      .venv\\Scripts\\python.exe -m andamio.camara_red
  En WSL2 / Ubuntu:
      ANDAMIO_VISION__CAMARA=http://127.0.0.1:8781/video python -m andamio buscar_persona --robot x2sim --ojo camara --panel

Con WSL en red espejo, 127.0.0.1 llega a Windows; si no, usa la IP de Windows que muestra este programa.
Solo hace falta OpenCV. Cualquier equipo de la red que conozca la direccion puede ver la camara:
usalo en la red del equipo, no en una WiFi publica.
"""
import argparse
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


def principal(argv=None):
    ap = argparse.ArgumentParser(description="Comparte la webcam como MJPEG (http://IP:PUERTO/video)")
    ap.add_argument("--camara", default="0", help="indice de la camara (0 = la del portatil)")
    ap.add_argument("--puerto", type=int, default=8781)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--ancho", type=int, default=960)
    args = ap.parse_args(argv)
    import cv2

    fuente = int(args.camara) if str(args.camara).isdigit() else args.camara
    cap = cv2.VideoCapture(fuente)
    ok, cuadro = cap.read() if cap.isOpened() else (False, None)
    if not ok:
        print(f"ERROR: no se pudo abrir la camara {args.camara!r}. Cierra otras apps que la usen "
              "(Teams, Zoom) o prueba --camara 1; en Windows revisa Configuracion > Privacidad > Camara.")
        return 2
    ultimo = {"jpg": None, "n": 0}
    candado = threading.Condition()

    def capturar():
        while True:
            ok, img = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            if img.shape[1] > args.ancho:
                e = args.ancho / img.shape[1]
                img = cv2.resize(img, (args.ancho, int(img.shape[0] * e)))
            okj, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if okj:
                with candado:
                    ultimo["jpg"], ultimo["n"] = buf.tobytes(), ultimo["n"] + 1
                    candado.notify_all()

    threading.Thread(target=capturar, daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.split("?")[0] not in ("/video", "/video.mjpg"):
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=cuadro")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            visto = -1
            try:
                while True:
                    with candado:
                        candado.wait_for(lambda: ultimo["n"] != visto, timeout=2.0)
                        jpg, visto = ultimo["jpg"], ultimo["n"]
                    if jpg is None:
                        continue
                    self.wfile.write(b"--cuadro\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

    srv = ThreadingHTTPServer((args.host, args.puerto), H)
    print(f"Camara compartida en http://127.0.0.1:{args.puerto}/video")
    for ip in _ips():
        print(f"   y en la red: http://{ip}:{args.puerto}/video")
    print("En WSL2:  ANDAMIO_VISION__CAMARA=http://127.0.0.1:%d/video python -m andamio ... --ojo camara" % args.puerto)
    print("Deja esta ventana abierta. Ctrl+C para terminar.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
