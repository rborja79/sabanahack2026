"""Panel web local para operar: estado, alertas, boton PARAR, confirmaciones, voz y plantillas.

Solo escucha en 127.0.0.1 y exige un token en cada orden (se imprime al abrir), para que
ninguna otra pagina del navegador pueda mandarle ordenes al robot.
"""
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .aplicacion import listar_plantillas
from .nucleo.errores import ErrorAndamio
from .nucleo.voz import es_alto

PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Andamio</title><style>
:root{--bg:#0f1318;--fg:#e8edf2;--mut:#8a97a6;--card:#171d25;--ok:#3ecf8e;--av:#f5b942;--er:#ff6b6b;--cr:#ff2d55;--ac:#4aa8ff}
@media(prefers-color-scheme:light){:root{--bg:#f4f6f9;--fg:#18202a;--mut:#5b6877;--card:#fff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px system-ui,sans-serif;padding:16px;max-width:1000px;margin:auto}
h1{font-size:18px;margin:0 0 12px}.fila{display:flex;gap:12px;flex-wrap:wrap}.card{background:var(--card);border-radius:10px;padding:14px;flex:1;min-width:260px}
button{font:inherit;padding:8px 14px;border-radius:8px;border:0;cursor:pointer;background:var(--ac);color:#fff}
button.parar{background:var(--cr);font-weight:700;font-size:20px;padding:18px;width:100%}button.sec{background:#4b5563}
input,select{font:inherit;padding:8px;border-radius:8px;border:1px solid #556;background:transparent;color:inherit;width:100%}
#alertas{font:13px ui-monospace,monospace;max-height:320px;overflow:auto}.a{padding:3px 0;border-bottom:1px solid #8883}
.info{color:var(--mut)}.aviso{color:var(--av)}.error{color:var(--er)}.critico{color:var(--cr);font-weight:700}
.dato{display:flex;justify-content:space-between;padding:3px 0}.mut{color:var(--mut)}
#conf{display:none;background:var(--av);color:#000;padding:12px;border-radius:8px;margin-bottom:12px}
</style></head><body><h1>Andamio · panel de operacion</h1>
<div id="conf"><b id="conftxt"></b> <button onclick="post('confirmar')">Confirmar</button></div>
<div class="fila"><div class="card"><button class="parar" onclick="post('parar')">PARAR</button>
<p><button class="sec" onclick="post('reanudar')">Levantar parada</button></p>
<div class="dato"><span class="mut">Robot</span><span id="robot"></span></div><div class="dato"><span class="mut">Modo</span><span id="modo"></span></div>
<div class="dato"><span class="mut">Bateria</span><span id="bat"></span></div><div class="dato"><span class="mut">Parada</span><span id="par"></span></div>
<div class="dato"><span class="mut">Plantilla</span><span id="pl"></span></div></div>
<div class="card"><b>Plantilla</b><p><select id="sel"></select></p><p><button onclick="correr()">Ejecutar</button></p>
<b>Voz</b><p><input id="txt" placeholder="escribe una orden y Enter"></p><p><button id="mic" class="sec" onclick="hablar()">Hablar</button></p><div id="oido" class="mut"></div></div></div>
<div class="card" id="vis" style="margin-top:12px;display:none"><b>Vision</b> <span class="mut" id="visfps"></span>
<div class="fila" style="margin-top:8px"><div style="flex:2;min-width:260px"><img id="cam" alt="camara" style="width:100%;border-radius:8px;background:#000;min-height:120px"></div>
<div style="flex:1;min-width:200px"><div id="dec" style="font-weight:700;margin-bottom:6px"></div><div id="dets" class="mut" style="font:13px ui-monospace,monospace"></div>
<canvas id="mapa" width="260" height="260" style="width:100%;max-width:260px;margin-top:8px;border-radius:8px;background:#0003"></canvas><div class="mut" style="font-size:12px">mapa: robot (azul) y objetivos simulados (verde), 1 cuadro = 1 m</div></div></div></div>
<div class="card" style="margin-top:12px"><b>Alertas</b><div id="alertas"></div></div>
<script>
const T="__TOKEN__";
async function post(p,b){const r=await fetch('/api/'+p,{method:'POST',headers:{'X-Token':T,'Content-Type':'application/json'},body:JSON.stringify(b||{})});return r.json()}
async function correr(){const r=await post('correr',{plantilla:sel.value});if(r.error)alert(r.error)}
document.getElementById('txt').addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.value){post('voz',{texto:e.target.value});e.target.value=''}});
function hablar(){const R=window.SpeechRecognition||window.webkitSpeechRecognition;if(!R){oido.textContent='Este navegador no tiene reconocimiento de voz; usa Chrome o escribe.';return}
const r=new R();r.lang='es-CO';r.onresult=e=>{const t=e.results[0][0].transcript;oido.textContent='oido: '+t;post('voz',{texto:t})};r.onerror=e=>oido.textContent='error de microfono: '+e.error;r.start();oido.textContent='escuchando...'}
async function ref(){try{const r=await (await fetch('/api/estado')).json();
robot.textContent=r.robot;modo.textContent=(r.estado&&r.estado.modo)||'?';bat.textContent=(r.estado&&r.estado.bateria!=null)?r.estado.bateria+'%':'?';
par.textContent=r.parado?'ACTIVA':'no';par.style.color=r.parado?'var(--cr)':'';pl.textContent=r.corriendo||'-';
conf.style.display=r.pendiente?'block':'none';conftxt.textContent=r.pendiente||'';
if(!sel.options.length)r.plantillas.forEach(p=>sel.add(new Option(p,p)));
vision(r);alertas.innerHTML=r.alertas.slice().reverse().map(a=>`<div class="a ${a.nivel}">${new Date(a.t*1000).toLocaleTimeString()} ${a.nivel.toUpperCase()} ${esc(a.mensaje)}${a.pista?'<br><span class="mut">→ '+esc(a.pista)+'</span>':''}</div>`).join('')}catch(e){}}
let camT=0;function vision(r){const v=r.vision;vis.style.display=v?'block':'none';if(!v)return;
if(Date.now()-camT>300){camT=Date.now();cam.src='/camara.jpg?'+camT}
visfps.textContent=v.fuente+' · '+v.fps+' fps';dec.textContent=v.decision||'(sin comportamiento activo)';
dets.innerHTML=v.detecciones.map(d=>esc(d.clase)+' '+d.score.toFixed(2)+' · '+(d.cx<-0.2?'izq':d.cx>0.2?'der':'centro')+(d.distancia?' · '+d.distancia.toFixed(1)+' m':'')).join('<br>')||'no veo nada';
const c=mapa.getContext('2d'),W=mapa.width,s=W/8,o=W/2;c.clearRect(0,0,W,W);c.strokeStyle='#8884';
for(let i=0;i<=8;i++){c.beginPath();c.moveTo(i*s,0);c.lineTo(i*s,W);c.stroke();c.beginPath();c.moveTo(0,i*s);c.lineTo(W,i*s);c.stroke()}
const p=(r.estado&&r.estado.pose)||[0,0,0];
(v.objetivos||[]).forEach(t=>{c.fillStyle='#3ecf8e';c.beginPath();c.arc(o+(t.x-p[0])*s,o-(t.y-p[1])*s,6,0,7);c.fill()});
c.fillStyle='#4aa8ff';c.beginPath();c.arc(o,o,7,0,7);c.fill();c.strokeStyle='#4aa8ff';c.lineWidth=3;c.beginPath();c.moveTo(o,o);c.lineTo(o+Math.cos(p[2])*s*0.9,o-Math.sin(p[2])*s*0.9);c.stroke();c.lineWidth=1}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
setInterval(ref,1000);ref();
</script></body></html>"""


class Panel:
    def __init__(self, app, host=None, puerto=None, abrir=True):
        self.app = app
        cfg = app.cfg["panel"]
        self.host = host or cfg["host"]
        self.puerto = int(puerto if puerto is not None else cfg["puerto"])
        self.token = secrets.token_urlsafe(16)
        self.abrir = abrir
        self.srv = None

    def estado(self):
        a = self.app
        try:
            est = a.robot.estado() if not a.seco else {}
        except Exception as e:
            est = {"error": str(e)}
        vision = None
        if a.ojo is not None:
            try:
                vision = a.ojo.estado()
            except Exception as e:
                vision = {"fuente": a.ojo.nombre, "fps": 0, "decision": f"error: {e}", "detecciones": []}
        return {"robot": a.robot.nombre, "estado": est, "parado": a.seguridad.parado, "pendiente": a.seguridad.pendiente,
                "corriendo": a.corriendo, "ultimo": a.ultimo, "alertas": a.alertas.recientes(60),
                "plantillas": listar_plantillas(), "vision": vision}

    def orden(self, nombre, cuerpo):
        a = self.app
        if nombre == "parar":
            a.seguridad.parada("boton PARAR del panel")
            return {"ok": True}
        if nombre == "reanudar":
            a.seguridad.reanudar()
            return {"ok": True}
        if nombre == "confirmar":
            a.seguridad.confirmar_ahora()
            return {"ok": True}
        if nombre == "voz":
            texto = str(cuerpo.get("texto", ""))[:300]
            if not a.oido_es_panel:
                # igual atendemos "para"/"alto": frenar nunca debe quedar sin respuesta
                if es_alto(texto):
                    if a.corriendo:
                        a.seguridad.interrumpir()
                    return {"ok": True}
                return {"ok": False, "error": "el oido de esta sesion no es el panel",
                        "pista": "inicia con --oido panel para dar ordenes desde aqui"}
            a.cola_voz.poner(texto)
            return {"ok": True}
        if nombre == "correr":
            try:
                a.ejecutar_en_hilo(str(cuerpo.get("plantilla", "")), cuerpo.get("parametros"))
            except ErrorAndamio as e:
                return {"ok": False, "error": f"{e}" + (f" ({e.pista})" if e.pista else "")}
            return {"ok": True}
        return {"ok": False, "error": "orden desconocida"}

    def iniciar(self):
        panel = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, codigo=200):
                datos = json.dumps(obj, default=str).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(datos)

            def _host_ok(self):
                h = (self.headers.get("Host") or "").split(":")[0]
                return h in ("127.0.0.1", "localhost", "[::1]")

            def do_GET(self):
                if not self._host_ok():
                    return self._json({"error": "host no permitido"}, 403)
                if self.path == "/":
                    datos = PAGINA.replace("__TOKEN__", panel.token).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(datos)))
                    self.end_headers()
                    self.wfile.write(datos)
                elif self.path == "/api/estado":
                    self._json(panel.estado())
                elif self.path.split("?")[0] == "/camara.jpg":
                    datos = panel.app.ojo.jpeg() if panel.app.ojo is not None else None
                    if not datos:
                        return self._json({"error": "sin imagen todavia"}, 404)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(datos)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(datos)
                else:
                    self._json({"error": "no existe"}, 404)

            def do_POST(self):
                if not self._host_ok() or self.headers.get("X-Token") != panel.token:
                    return self._json({"error": "no autorizado"}, 403)
                try:
                    n = int(self.headers.get("Content-Length", 0))
                    cuerpo = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
                except ValueError:
                    return self._json({"error": "JSON invalido"}, 400)
                if not self.path.startswith("/api/"):
                    return self._json({"error": "no existe"}, 404)
                self._json(panel.orden(self.path[5:], cuerpo))

        try:
            self.srv = ThreadingHTTPServer((self.host, self.puerto), H)
        except OSError as e:
            raise ErrorAndamio(f"no se pudo abrir el panel en el puerto {self.puerto}: {e.strerror or e}",
                               pista="seguramente ya hay otro andamio abierto: cierralo (Ctrl+C en su ventana) "
                                     f"o usa ANDAMIO_PANEL__PUERTO={self.puerto + 1}")
        self.puerto = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True, name="andamio-panel").start()
        url = f"http://{self.host}:{self.puerto}/"
        self.app.alertas.info(f"panel en {url}")
        if self.abrir:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        return url

    def cerrar(self):
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
