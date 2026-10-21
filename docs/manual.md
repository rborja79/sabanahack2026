# Manual: que hace cada cosa y como se usa

Referencia pieza por pieza. Para instalar, `docs/equipo.md`. Para el panorama
general, el `README.md`.

---

## 1. Como encaja todo

```
  quien manda                     el puente                el resultado
  -----------                     ---------                ------------
  visor WebXR (VR/AR)  ──manos──▶
  emulador ?emular     ──manos──▶   server.py  ──▶  sim.py  ──▶  estado
  camara ArUco         ──manos──▶   (ws 8765)       (IK)         de cada
  camara manos         ──manos──▶       │                        pieza
  raton en escritorio  ──manos──▶       │                          │
  cliente_prueba.py    ──manos──▶       ▼                          ▼
                                   recorder.py              el visor pinta
                                        │
                                        ▼
                                 datos/<episodio>/
```

Cualquier cosa que sepa mandar un punto 3D por websocket puede manejar el
robot. Los seis modos de arriba son solo seis formas de producir ese punto.

---

## 2. bridge/ · el puente con el robot

### `server.py` · el proceso que hay que tener corriendo siempre

```bash
python server.py --modelo unitree_g1 --puerto 8765 --hz 50 --escala 1.0
```

| Argumento | Que hace |
|---|---|
| `--modelo` | `unitree_g1`, `unitree_z1` o `unitree_go2` |
| `--puerto` | puerto del websocket, por defecto 8765 |
| `--hz` | cuantas veces por segundo manda el estado, por defecto 50 |
| `--escala` | cuanto se mueve el robot por cada metro tuyo. Bajala a 0.7 si no alcanza |

**Protocolo.** JSON sobre websocket. Al conectarse el servidor manda `hola`:

```json
{"type":"hola","robot":"unitree_g1","glb":"/robots/unitree_g1.glb",
 "bodies":["pelvis","left_hip_pitch_link","..."],
 "efectores":{"left":"left_wrist_yaw_link","right":"right_wrist_yaw_link"},
 "hz":50}
```

Y a partir de ahi, `hz` veces por segundo:

```json
{"type":"estado","t":1792614000.12,
 "p":[x0,y0,z0, x1,y1,z1, ...],
 "q":[w0,x0,y0,z0, w1,x1,y1,z1, ...],
 "grabando":false,"n":0}
```

`p` trae 3 numeros por pieza y `q` trae 4, en el mismo orden de `bodies`. Los
cuaterniones van en orden **wxyz**, que es el de MuJoCo, no el de three.js.

El cliente manda dos tipos de mensaje:

```json
{"type":"manos","left":{"p":[x,y,z],"pinza":1.0},
                "right":{"p":[x,y,z],"pinza":0.2},
                "head":{"p":[x,y,z]}}
{"type":"cmd","cmd":"calibrar"}
{"type":"cmd","cmd":"reset"}
{"type":"cmd","cmd":"grabar","tarea":"recoger_taza"}
{"type":"cmd","cmd":"parar"}
```

**Calibracion por ancla.** Al calibrar, el puente guarda donde esta tu mano y
donde esta la mano del robot, y despues suma la diferencia:

```
objetivo = mano_robot_al_calibrar + (tu_mano_ahora - tu_mano_al_calibrar) * escala
```

Por eso no importa que tu cuerpo y el robot no midan lo mismo, ni que estes
sentado o de pie. Si el brazo queda estirado o no alcanza, casi siempre la
solucion es volver a calibrar con la mano en una posicion comoda.

### `sim.py` · el robot y la cinematica inversa

```python
from sim import Robot

r = Robot("unitree_g1")          # tambien unitree_z1, unitree_go2
r.fijar_objetivo("right", [0.2, 0.3, 1.0])   # a donde debe ir la mano
r.paso()                                      # una iteracion de IK
p, q = r.estado()                             # pose de las 30 piezas
r.pos_efector("right")                        # donde quedo la mano
r.qpos()                                      # angulos de todas las junturas
r.reposo()                                    # vuelve a la pose inicial
```

| Metodo | Que devuelve |
|---|---|
| `fijar_objetivo(lado, punto)` | nada, guarda a donde debe ir esa mano |
| `paso()` | nada, acerca las manos a sus objetivos un paso |
| `estado()` | `(p, q)` planos, para mandar al visor |
| `pos_efector(lado)` | `[x,y,z]` de la mano, o `None` si ese robot no la tiene |
| `qpos()` | lista de angulos, lo que se guarda como observacion |
| `reposo()` | nada, devuelve el robot a la pose de la que arranca |

La IK es **minimos cuadrados amortiguados**: toma el jacobiano de la cadena que
va del torso a la mano, y resuelve `dq = Jᵀ(JJᵀ + λ²I)⁻¹ · error`. El `λ`
(`amortiguacion`, 0.08) evita que se dispare cerca de las singularidades, y
`ganancia` (0.6) controla que tan rapido converge. Si el brazo tiembla, sube la
amortiguacion; si va lento, sube la ganancia.

Que body sigue a cada mano esta en `EFECTORES`, arriba del archivo. Para agregar
un robot nuevo se agrega una entrada ahi.

**Con robot fisico el viernes:** se cambia en un solo sitio. `paso()` pasa a
leer la pose real del SDK, y `fijar_objetivo()` pasa a mandar el comando al
controlador. El visor, el grabador y el protocolo no se tocan.

### `recorder.py` · guarda los episodios

No se usa directamente, lo llama `server.py` cuando mandas `grabar`. Escribe
`datos/<fecha-id>/tramas.jsonl`, una linea por trama:

```json
{"i":0,"t":1792614000.12,
 "obs":{"qpos":[...]},
 "accion":{"left":[x,y,z],"right":[x,y,z],
           "manos":{"left":{...},"right":{...},"head":{...}}}}
```

Y al parar escribe `manifiesto.json` con `episodio`, `tarea`, `robot`,
`operador`, `inicio`, `fin`, `duracion_s` y `tramas`.

### `cliente_prueba.py` · prueba la cadena sin navegador

```bash
python cliente_prueba.py --tramas 120 --radio 0.12
```

Se conecta, calibra, dibuja un circulo con la mano derecha, graba el episodio y
compara lo pedido contra lo que hizo el robot. Termina en `prueba OK` si el
error medio de seguimiento es menor a 3 cm. Es la forma mas rapida de saber si
algo se rompio.

### `export_robot.py` · convierte un robot de MuJoCo en un GLB

```bash
python export_robot.py --modelo unitree_h1 \
  --salida ../web/public/robots/unitree_h1.glb --decimar 6000
```

Solo hace falta para agregar un robot que no venga listo. Los tres que trae el
kit ya estan exportados. `--decimar` baja los triangulos por pieza, que es lo
que hace la diferencia entre 8 MB y 1.8 MB.

### `prueba.py` · la revision que corre el instalador

```bash
python prueba.py
```

Confirma que el robot carga, que la IK converge y que el detector arranca.

---

## 3. web/ · el visor

```bash
cd web && npm run dev
```

| URL | Que hace |
|---|---|
| `http://localhost:5173` | escritorio: orbitas con el raton y arrastras las esferas |
| `http://localhost:5173/?emular` | el navegador finge ser un Quest 3, con mandos |
| `http://localhost:5173/?emular=manos` | igual pero en seguimiento de manos |

Teclas: `c` calibra, `r` manda a reposo, `g` graba o para.

El panel de la izquierda muestra `piezas 30/30 · mallas 71`. Si dice `0/30` el
GLB no cargo.

### Los archivos

| Archivo | Que hace |
|---|---|
| `src/main.js` | arma la escena, las sesiones de VR y AR, lee las manos y conecta todo |
| `src/bridge.js` | el cliente websocket. Emite eventos `hola`, `estado`, `aviso` |
| `src/robot.js` | carga el GLB y le aplica la pose a cada pieza en cada trama |
| `index.html` | el panel de control |
| `vite.config.js` | configuracion del servidor de desarrollo |

### Dos trampas que ya estan resueltas, no las deshagan

**Los ejes no son los mismos.** MuJoCo trabaja con Z arriba y WebXR con Y
arriba. La conversion esta en `robot.js`:

```js
mjAtres = (p) => new THREE.Vector3(p[0], p[2], -p[1])
tresAmj = (v) => [v.x, -v.z, v.y]
```

**El indice de la mano no es el lado.** `render.xr.getHand(0)` no siempre es la
izquierda. Hay que leer la lateralidad del evento `connected`, que es lo que
hace `main.js`. Si alguien lo cambia a indices, las dos manos se pegan al mismo
lado y cuesta media hora darse cuenta.

### Para depurar desde la consola del navegador

```js
xr.vista.diagnostico()   // {bodies, mapeados, mallas, sinMapear}
xr.puente.tramas         // cuantas tramas han llegado
xr.estado                // lo que muestra el panel
xr.manosXR               // que objeto quedo asignado a cada mano
```

---

## 4. vision/ · ver con la camara

### `objetos.py` · encontrar cosas

El modelo **viene en el repo**: `vision/modelos/yolo11n.onnx`, 11 MB, lo corre
OpenCV directamente. No necesita torch, no descarga nada y funciona igual en
Windows, macOS y Linux. Reconoce las 80 clases de COCO, y las que sirven para
una mesa son: botella, vaso, copa, tazon, tenedor, cuchillo, cuchara, celular,
libro, tijeras, control, teclado, mouse, manzana, banano, naranja.

```bash
python objetos.py --fuente 0                           # camara en vivo
python objetos.py --fuente foto.jpg --salida vista.png
python objetos.py --fuente 0 --clases botella,vaso,tazon
python objetos.py --fuente 0 --modo color --color naranja
```

Desde Python:

Desde Python, parado en `vision/`:

```python
import objetos
dets = objetos.por_onnx(cuadro)              # lista ordenada por confianza
dets = objetos.por_color(cuadro, "naranja")  # mas rapido, para cubos marcados
punto = objetos.a_objetivo(dets[0])          # [x, y, z] en el marco del robot
cuadro = objetos.pintar(cuadro, dets)        # dibuja las cajas
```

Cada deteccion es:

```python
{"clase":"botella", "score":0.87, "caja":[x,y,ancho,alto],
 "centro":[u,v],          # normalizado de 0 a 1
 "area_rel":0.043}
```

`a_objetivo(det, altura_mesa=0.78, cerca=0.5)` es el puente entre ver y mover:
convierte el centro de una caja en un punto del marco del robot. La altura se
pasa a mano porque una camara sola no sabe la profundidad.

Probado con imagenes reales: bus 0.94, personas 0.90, corbata 0.48, cajas bien
puestas.

### `marcador.py` · teleoperar con ArUco, lo mas preciso sin visor

```bash
python marcador.py --imprimir hoja.png        # imprime los dos marcadores
python marcador.py --lado-marcador 0.05       # mide el lado impreso en metros
```

Imprimes la hoja, pegas el marcador 0 a la mano izquierda y el 1 a la derecha,
y la camara te da la posicion en 3D de verdad, sin adivinar profundidad. Error
medido: 4.5 mm a 45 cm con una camara sin calibrar. Entre mas grande imprimas
el marcador, mas preciso.

El `--lado-marcador` tiene que ser el lado real del cuadro negro en metros. Si
lo pones mal, la escala de todo queda mal.

### `manos.py` · teleoperar con las manos, sin imprimir nada

```bash
python manos.py
```

Mas comodo pero menos exacto: la profundidad la estima con el tamano aparente
de la mano. Es el unico modulo que necesita los modelos de MediaPipe, que
`setup.sh` intenta bajar. Si la descarga falla, usa ArUco.

### `comun.py` · lo que comparten

```python
from comun import imagen_a_robot, Suavizado, CAJA

imagen_a_robot(u, v, cerca)   # de pixel normalizado a metros en el marco del robot
Suavizado(alfa=0.35)          # filtro para que el objetivo no tiemble
```

`CAJA` define a que volumen frente al robot se mapea la imagen. Si el robot se
queda corto o se pasa, se ajusta ahi:

```python
CAJA = {"x": (-0.45, 0.45), "y": (0.15, 0.55), "z": (0.75, 1.45)}
```

---

## 5. datos/ · los episodios grabados

```bash
python datos/cargar.py                        # lista lo que hay
python datos/cargar.py --episodio 20261021-...  # lo vuelve tabla
```

Desde Python:

```python
from datos.cargar import episodios, tramas, tabla

episodios()              # lista de manifiestos
tramas("2026...")        # generador, una trama a la vez, para archivos grandes
tabla("2026...")         # DataFrame: una fila por trama
```

`tabla()` devuelve columnas `t`, `i`, `q0..qN` con los angulos, y
`left_x/y/z`, `right_x/y/z` con lo que pedia el operador. Eso es exactamente la
forma que necesita una politica de clonacion de comportamiento: `qpos` como
observacion y el objetivo de la mano como accion.

---

## 6. Recetas

**Cambiar de robot**

```bash
python server.py --modelo unitree_z1
```

El visor se entera solo, porque el nombre del GLB viene en el `hola`.

**El robot no alcanza**

Pulsa `c` para recalibrar, o baja la escala: `python server.py --escala 0.7`.

**Grabar un conjunto de demostraciones**

Escribe el nombre de la tarea en el campo `tarea`, graba, para, repite. Usa el
mismo nombre para todas las repeticiones de la misma tarea, porque es lo que
despues las agrupa.

**Que el objetivo salga de la camara y no de tu mano**

Parado en la raiz del repo:

```python
import sys
sys.path += ["vision", "bridge"]

import objetos
from sim import Robot

r = Robot("unitree_g1")
dets = objetos.por_onnx(cuadro, clases=["botella"])
if dets:
    r.fijar_objetivo("right", objetos.a_objetivo(dets[0]))
    for _ in range(200):
        r.paso()
```

Ese bucle es el esqueleto de cerrar el lazo: ver, apuntar, mover.
