# sabanahack2026 · kit de teleoperacion XR

Entorno de trabajo listo para construir una solucion de **teleoperacion y captura
de demostraciones** con robots, en VR, en AR o con una camara comun. Corre igual
en un portatil y en una sesion en la nube, con o sin robot fisico.

La apuesta: lo que piden los patrocinadores (Ansrobex vende kits de captura de
datos encarnados, Robotics 4.0 vende Unitree y tiene plataforma de teleoperacion,
AGI Villa conecta China con LatAm) apunta al mismo sitio: **mover un robot con el
cuerpo y guardar lo que hiciste en un formato con el que se pueda entrenar**. Eso
es lo que hace este kit de arranque.

---

## Que hay adentro

```
bridge/     simulador, cinematica inversa, grabador y servidor websocket
web/        visor en three.js con WebXR: VR, AR y escritorio
vision/     teleoperacion por camara (ArUco y manos) y deteccion de objetos
datos/      episodios grabados y utilidades para cargarlos
sim/        mujoco_menagerie (lo baja setup.sh)
docs/       guia del Quest y plan del dia
```

Tres robots quedan listos: **Unitree G1** (humanoide, dos brazos), **Unitree Z1**
(brazo de mesa) y **Unitree Go2** (cuadrupedo). Son los mismos que vende Robotics
4.0, que es el patrocinador que trae hardware.

> Para el equipo: el paso a paso completo esta en [`docs/equipo.md`](docs/equipo.md).

## Instalacion

```bash
git clone https://github.com/rborja79/sabanahack2026.git
cd sabanahack2026
./setup.sh
```

Toma entre 5 y 15 minutos segun la conexion. Al final imprime una prueba del
robot; si dice `robot ok` quedo bien.

En Windows, desde PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Requisitos: Python 3.10 o superior, Node 20 o superior, git. En Linux sin
pantalla, ademas `sudo apt-get install -y libosmesa6`.

## Arrancar

Dos terminales.

```bash
# terminal 1: el puente con el robot
source .venv/bin/activate
cd bridge && python server.py --modelo unitree_g1
```

```bash
# terminal 2: el visor
cd web && npm run dev
```

Abre la direccion que imprime vite, pulsa **Conectar** y ya deberias ver el robot.
En escritorio arrastras las dos esferas de colores para mover las manos. Teclas:
`c` calibra, `r` manda a reposo, `g` graba o para.

## Los cuatro modos de control

| Modo | Que necesitas | Para que sirve |
|---|---|---|
| Escritorio | nada | probar y depurar, arrastrando dos esferas |
| Visor emulado | nada | probar todo el camino de VR sin tener visor |
| Terminal | nada | probar la cadena completa sin navegador |
| ArUco | una camara y una hoja impresa | posicion real en 3D, sin descargas |
| Manos por camara | una camara | lo mas rapido de montar, menos exacto |
| VR o AR de verdad | Quest con navegador | la demo que se ve bien |

**Visor emulado.** Abre la misma pagina con `?emular` y el navegador finge ser
un Quest 3: aparece ENTER VR, hay mandos y manos virtuales que mueves con el
raton, y el codigo que corre es exactamente el de VR. Con `?emular=manos`
arranca en seguimiento de manos en lugar de mandos.

```
http://localhost:5173/?emular
http://localhost:5173/?emular=manos
```

**Terminal.** Sin navegador, sin visor y sin camara:

```bash
cd bridge && python cliente_prueba.py
```

Se conecta al puente, dibuja un circulo con la mano derecha, graba el episodio
y revisa que lo grabado coincida con lo pedido. Es la prueba mas rapida de que
toda la cadena esta viva.

VR y AR de verdad: mira `docs/quest.md`.

ArUco, el mas preciso sin visor:

```bash
python vision/marcador.py --imprimir hoja.png     # imprime y pega los dos marcadores
python vision/marcador.py --lado-marcador 0.05    # mide el lado impreso y pasalo en metros
```

Manos por camara:

```bash
python vision/manos.py
```

## Grabar demostraciones

Pulsa **Grabar** en el visor, o `g` en cualquiera de los modos de camara. Cada
episodio queda en `datos/<fecha-id>/` con un `tramas.jsonl` y un
`manifiesto.json`. Una linea por trama con la pose del robot y lo que pedia el
operador.

```bash
python datos/cargar.py                       # lista los episodios
python datos/cargar.py --episodio 2026...    # lo vuelve tabla
```

En Python, para entrenar:

```python
from datos.cargar import tabla
df = tabla("20261021-201231-93b0")   # una fila por trama, qpos en columnas
```

## Ver objetos

El detector **viene dentro del repo**: `vision/modelos/yolo11n.onnx`, 10 MB,
corre sobre OpenCV. No hay que descargar nada, no necesita torch y funciona
igual en Windows, macOS y Linux. Reconoce las 80 clases de COCO, entre ellas
botella, vaso, tazon, celular, libro, tijeras y persona.

```bash
python vision/objetos.py --fuente 0                      # camara en vivo
python vision/objetos.py --fuente foto.jpg --salida v.png
python vision/objetos.py --fuente 0 --clases botella,vaso,tazon
python vision/objetos.py --fuente 0 --modo color --color naranja
```

`a_objetivo()` convierte una deteccion en un punto del marco del robot, que es
lo que necesitas para encadenar "veo la taza" con "muevo la mano a la taza".

Los modelos de MediaPipe (`hand_landmarker.task`, `efficientdet_lite0.tflite`)
son **opcionales** y solo los usa `vision/manos.py`. `setup.sh` los intenta
bajar; si la red los bloquea, no pasa nada: ArUco y el modo onnx no dependen
de ellos.

## Cambiar de robot

```bash
cd bridge && python server.py --modelo unitree_z1
```

Si quieres uno que no este, exportalo primero:

```bash
cd bridge
python export_robot.py --modelo <carpeta_en_menagerie> \
  --salida ../web/public/robots/<nombre>.glb --decimar 6000
```

Y agrega su efector final en `EFECTORES`, dentro de `bridge/sim.py`.

## Si el viernes hay robot fisico

El simulador y el robot real se cambian en un solo sitio. En `bridge/sim.py`,
`paso()` avanza la simulacion y `estado()` devuelve la pose de cada pieza. Para
un robot de verdad se reemplaza `paso()` por la lectura del SDK y se manda el
objetivo al controlador. El visor, el grabador y el protocolo no cambian.

## Como se comunican las piezas

```
visor o camara  --(manos: posicion y pinza)-->  puente  --> IK --> robot
visor           <--(estado: pose de cada pieza)--  puente
                                                     |
                                                     v
                                               datos/<episodio>/
```

El protocolo es JSON sobre websocket, puerto 8765:

- el servidor manda `hola` al conectarse (robot, URL del GLB, lista de bodies)
- el servidor manda `estado` a 50 Hz: `p` con 3 valores por body y `q` con 4
- el cliente manda `manos`: `{left: {p, pinza}, right: {...}, head: {p}}`
- el cliente manda `cmd`: `calibrar`, `reset`, `grabar`, `parar`

La calibracion es por ancla: al calibrar guarda donde esta tu mano y donde esta
el efector, y despues suma la diferencia. Por eso no importa que tu cuerpo y el
robot no midan lo mismo.

## Problemas comunes

**El visor conecta pero no aparece el robot.** El panel dice `piezas 0/30`. El
GLB no cargo: revisa que exista `web/public/robots/<modelo>.glb`.

**Desde el Quest no conecta.** El navegador exige HTTPS o localhost. Usa
`adb reverse`, que esta en `docs/quest.md`.

**No tengo visor y quiero probar VR.** Abre la pagina con `?emular`.

**El brazo no llega.** El objetivo quedo fuera del alcance. Pulsa `c` para
recalibrar con la mano en una posicion comoda, o baja `--escala` a 0.7.

**En Linux, `mujoco` falla al renderizar.** Falta OSMesa:
`sudo apt-get install -y libosmesa6` y corre con `MUJOCO_GL=osmesa`.

**MediaPipe no encuentra el modelo.** `setup.sh` no pudo bajarlo. Vuelve a
correrlo, o usa ArUco, que no necesita descargas.
