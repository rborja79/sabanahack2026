# Andamio

Andamio es el andamiaje para el reto: **cargas una plantilla (un archivo YAML), eliges el robot y se ejecuta**, con
seguridad, alertas y mensajes que dicen qué hacer cuando algo falla.

```
python -m andamio caminar  --robot sim  --confirmo     # simulación, sin robot
python -m andamio saludar  --robot x2                  # X2 real (desde un equipo con ROS + SDK)
python -m andamio voz      --robot remoto --panel      # voz, con el robot en otra máquina
python -m andamio buscar_persona --robot falso --ojo camara --panel   # autonomía con la webcam
```

En el Mac, lo más fácil: doble clic en **`Probar en Mac.command`** (en la raíz del repo) e
**`Subir al repo.command`** para hacer commit y push.

## Qué trae

| Pieza | Para qué |
|---|---|
| `plantillas/*.yaml` | Misiones listas: `caminar`, `voz`, `manos`, `teleop_grabar`, `saludar` |
| `nucleo/seguridad.py` | Límites de velocidad, batería, modos, parada de emergencia, vigilante |
| `nucleo/alertas.py` | Avisos en consola, panel y `alertas.jsonl`, siempre con una pista de qué hacer |
| `nucleo/voz.py` | Voz: Claude por API elige **solo** entre las acciones de la plantilla; sin internet usa palabras clave |
| `robots/` | `falso` (con fallos inyectables), `sim` (MuJoCo), `x2`, `d1`, `remoto` |
| `servidor_robot.py` | Se ejecuta junto al robot; el Mac o cualquier portátil lo controla por TCP |
| `teleop.py` | Gafas/visor WebXR → IK → brazos del robot, con grabación (mismo websocket del visor de `web/`) |
| `panel.py` | Panel en el navegador: PARAR, confirmaciones, voz, estado, alertas |
| `doctor.py` | Diagnóstico: `python -m andamio.doctor --robot x2` |

## Tres formas de conectar con el X2 (elige según tu portátil)

1. **Directo (Ubuntu 22.04 o WSL2 con red espejo):** cable Gigabit, IP `10.0.1.2/24`, SDK AimDK compilado, `--robot x2`.
2. **Contenedor en la unidad de desarrollo (la más robusta, recomendada por el manual):** copias Andamio al robot con
   `instalar/copiar_al_robot.sh` y corres `python3 -m andamio.servidor_robot --robot x2` adentro. Desde cualquier portátil
   (también el Mac) usas `--robot remoto`. Ver `instalar/contenedor_x2.md`.
3. **Solo simulación:** `--robot sim` con el MJCF del X2 en `robots/`. Sirve para ensayar todo antes de tocar el robot.

> El Mac no puede correr ROS 2 con el robot de forma directa. Por eso existe el modo 2: el código que toca ROS vive junto
> al robot y el Mac solo manda órdenes de alto nivel (y calcula la cinemática y el visor).

## Elegir el robot: `--robot`

El robot se elige al lanzar, no dentro de la plantilla: `--robot falso | sim | x2 | d1 | remoto`.
La plantilla declara lo que necesita (`requiere: [caminar, manos, medios...]`) y el andamio se niega a correrla en un
robot que no lo tiene, con un mensaje claro. Las **manos** no son un robot aparte: son parte del X2 (pinza o mano diestra),
y se usan con los pasos `mano` y `brazos` (plantilla `manos.yaml`).

| Robot | Qué es | Sabe hacer |
|---|---|---|
| `falso` | robot de mentira en memoria, para probar lógica y fallos | todo (lo anota) |
| `sim` | X2 en MuJoCo con su modelo real; `--ver3d` abre una ventana 3D | caminar (deslizando), brazos, cabeza |
| `x2` | X2 real por ROS 2 (Ubuntu + AimDK, cable a 10.0.1.41) | caminar, brazos, cabeza, manos, gestos, voz, medios |
| `x2sim` | X2 en el simulador oficial de AgiBot (física + control real), Ubuntu/WSL2 x86 | caminar, brazos, cabeza, manos, gestos (voz/pantalla se anuncian) |
| `d1` | cuadrúpedo D1 (SDK zsl-1, solo Linux) | caminar, gestos |
| `remoto` | cualquiera de los anteriores corriendo en otra máquina con `servidor_robot` | lo que tenga el de allá |

### Simulador 3D

Con el modelo del X2 en `robots/X2_URDF/` (el repo oficial `AgibotTech/agibot_x2_urdf`, carpeta `X2_URDF-v1.4.0`):

```
.venv/bin/mjpython -m andamio buscar_persona --robot sim --ojo simulado --ver3d --panel --confirmo   # Mac
python -m andamio buscar_persona --robot sim --ojo simulado --ver3d --panel --confirmo              # Linux/Windows
```

En el Mac la ventana 3D exige `mjpython` (viene con mujoco). La simulación es cinemática: el robot se desliza al caminar
(no simula pasos ni equilibrio, eso lo hace el robot real) y mueve brazos y cabeza con los límites del modelo. Sirve para
ver que la plantilla hace lo que crees, no para validar estabilidad.

### Simulador oficial de AgiBot con física (WSL2 / Ubuntu x86)

En un portátil x86 con Ubuntu 22.04 o WSL2 (Windows 11) corre el simulador oficial "X2 Sim + MC Deployment":
MuJoCo con física y el **mismo control de movimiento (mc) del robot real**, así que el X2 camina, se equilibra y se
levanta de verdad. El andamio lo maneja con `--robot x2sim`, por el mismo ROS 2 que usará con el robot (lo que el
simulador no trae —batería, voz, pantalla, luces— se anuncia en las alertas). No corre en Mac Apple Silicon.

```
# una vez: baja del sitio del SDK (barra flotante > Extras) sim_mujoco-x86 y mc-x86, y el SDK AimDK; ponlos en una carpeta
./andamio/instalar/sim_oficial.sh preparar ~/Descargas/x2_sim
./andamio/instalar/sim_oficial.sh iniciar                 # ventana de MuJoCo + mc en una sesion tmux
./andamio/instalar/sim_oficial.sh correr caminar --panel  # cualquier plantilla contra el simulador
./andamio/instalar/probar_wsl.sh                          # menu de pruebas
./andamio/instalar/sim_oficial.sh parar
```

La cámara del portátil no se ve dentro de WSL2: en Windows, `Probar en Windows.bat` opción 8 (o
`python -m andamio.camara_red`) la comparte como video y en WSL2 se usa con
`ANDAMIO_VISION__CAMARA=http://127.0.0.1:8781/video ... --ojo camara`. Nota de la guía oficial: con este control, girar
solo con velocidad angular no garantiza el giro en el sitio; si no gira, agrega un poco de avance (`vx: 0.2`).

## Pantalla, sonido y luces (X2)

Pasos: `expresion` (`feliz`, `parpadear`, `dormido`, `aburrido`, `muy_enojado`, `adorar`, `anormal` o un id del manual),
`luces` (`modo: fijo|respirar|parpadear|fluir`, `color: azul` o `[r, g, b]`), `video` (`archivo: intro.mp4`,
`repetir: true`), `audio` (`archivo: saludo.wav`) y `decir` (voz sintetizada). Plantilla de ejemplo: `medios.yaml`.

Los videos y audios viven en el **computador de interacción del robot (PC3, 10.0.1.42)**, no en el de desarrollo:
súbelos con `./andamio/instalar/subir_medios.sh USUARIO intro.mp4 saludo.wav` (quedan en `/var/tmp/andamio_medios/`,
legibles por todos, como pide el manual). Audio solo **WAV/PCM** (convierte mp3 con `ffmpeg -i x.mp3 -ar 16000 -ac 1 x.wav`).
El manual pide detener `task_manager` en el PC1 para que no compita por la pantalla y las luces: eso lo hacen los
organizadores (`aima em stop-app task_manager`); nosotros nunca ejecutamos nada en el PC1.

## Autonomía (nivel 1: mirar → decidir → actuar)

Pasos nuevos para plantillas: `mirar` (guarda lo que ve en una variable), `buscar` (gira hasta ver el objeto y lo centra)
y `acercarse` (camina hacia él corrigiendo el rumbo y frena a `distancia` m). Los objetos son las 80 clases de COCO en
español: `persona`, `botella`, `vaso`, `silla`, `mochila`... Plantillas: `buscar_persona.yaml` y `seguir_persona.yaml`.

```yaml
- buscar:    {objeto: persona, max_s: 25, sentido: izquierda}
- acercarse: {objeto: persona, distancia: 1.2, vx: 0.3, max_s: 40, perdido_s: 1.5}
- mirar:     {objeto: botella, guardar_en: visto}
- si: {cuando: "visto.n > 0", entonces: [{decir: "veo una botella a la ${visto.lado}"}]}
```

El "ojo" se elige con `--ojo`: `camara` (webcam; en el Mac la primera vez macOS pide permiso de cámara para la Terminal),
`simulado` (personas imaginarias en el mapa; prueba todo sin cámara), `x2` (cámara RGB-D de la cabeza, con distancia por
profundidad) o `remoto` (el servidor del robot corre el detector: `servidor_robot --ojo x2`). El panel muestra la imagen
con las cajas, la decisión que está tomando y un mapa.

Seguridad propia: la velocidad caduca sola en 0,35 s si el ciclo se cuelga, frena si pierde de vista el objeto,
tiene tiempo máximo, no avanza si el objeto no está al frente o si no sabe la distancia, y nunca se acerca a menos de
0,5 m. Con la webcam la distancia se estima por el tamaño típico del objeto: es aproximada. Sin verificar con el robot:
el campo de visión de la cámara del X2 (`vision.fov_h`) y el formato de su profundidad (se asume 16UC1 en mm).

### Entrenar YOLO con tus propios objetos

Para personas, botellas, vasos, sillas o mochilas **no hace falta entrenar**: el modelo del repo ya reconoce las 80 clases de
COCO. Entrena solo si el reto trae objetos raros (una pieza, un logo, un juguete):

1. **Fotos:** 100 a 300 por objeto, con distintos fondos, luces y distancias (la propia cámara del robot o la del portátil:
   `python vision/objetos.py --fuente 0` sirve para ver qué ya detecta).
2. **Etiquetar:** cajas alrededor de cada objeto en Roboflow, CVAT o Label Studio; exporta en formato **YOLO** (deja un
   `data.yaml` con las clases en orden).
3. **Entrenar** (en el Mac usa la GPU con `device=mps`; 20-40 min con yolo11n):
   ```
   pip install ultralytics
   yolo detect train model=yolo11n.pt data=mis_datos/data.yaml epochs=60 imgsz=640 device=mps
   yolo export model=runs/detect/train/weights/best.pt format=onnx opset=12 imgsz=640
   cp runs/detect/train/weights/best.onnx vision/modelos/mio.onnx
   ```
4. **Usarlo** en `andamio/config.yaml`:
   ```yaml
   vision:
     modelo: vision/modelos/mio.onnx
     clases: [pieza_roja, taza_logo]     # mismo orden que el data.yaml
   ```
   y en la plantilla `buscar: {objeto: pieza_roja}`. Si el número de clases no cuadra, el andamio lo dice al arrancar.
   Para objetos nuevos la distancia se estima por tamaño solo si los agregas a `TAMANOS` en `vision.py`; con el X2 se
   usa la profundidad de la cámara.

## Llevar lo que probaste al robot (cable, WiFi o PC del equipo)

Hay dos formas; elige según lo que quieras mover:

1. **No mover nada:** deja el PC pegado al robot (cable) corriendo `python -m andamio.servidor_robot --robot x2` (o dentro del
   contenedor) y ejecuta desde el Mac con `--robot remoto`. Las plantillas, la voz y el panel corren en el Mac; solo viajan
   órdenes cortas por TCP. Esto **funciona por WiFi o cualquier red** donde el Mac vea la IP del PC: pon su IP en
   `remoto.host` (o `ANDAMIO_REMOTO__HOST=192.168.x.y`) y el mismo `ANDAMIO_TOKEN` en ambos. Si se corta la red, el
   servidor detiene el robot solo (la velocidad caduca a los 0,3 s).
2. **Mover el trabajo:** las plantillas son archivos `.yaml`; haz `git add/commit/push` desde el Mac y `git pull` en el PC.
   Las grabaciones (`datos/`) y tu `.env`/`config.yaml` no van a Git: cópialos por USB o con `scp` si los necesitas allá.

### El WiFi del robot (X2 Ultra)

El X2 Ultra trae su propio punto de acceso: en la app del robot activa **AP Hotspot** y ahí ves el nombre y la clave del
WiFi. Conectado a ese WiFi llegas a la unidad de desarrollo (10.0.1.41) **pasando por** 192.168.88.88 con SSH (las
credenciales las da soporte técnico / los organizadores). El manual dice que el WiFi es "solo para depurar" y que ROS entre
equipos vaya por cable. Con Andamio no hace falta ROS por WiFi: el servidor corre **dentro del contenedor del robot** y
por el WiFi solo viaja el TCP de Andamio, metido en un túnel SSH:

```
# 1) en el robot (contenedor):   python3 -m andamio.servidor_robot --robot x2 --host 127.0.0.1
# 2) en el Mac, conectado al WiFi del robot (deja esta terminal abierta):
ssh -N -J USUARIO@192.168.88.88 agi@10.0.1.41 -L 8790:127.0.0.1:8790
# 3) en otra terminal del Mac:
ANDAMIO_REMOTO__HOST=127.0.0.1 python -m andamio voz --robot remoto --panel
```

Sin verificar: que el salto por 192.168.88.88 permita túneles (si no, usa el cable). 192.168.88.88 / 10.0.1.40 es el PC de
movimiento: solo se usa como paso del SSH, **nunca** ejecutes ni copies nada ahí. Por WiFi puede haber cortes; si se cae,
el servidor frena el robot solo.

## Instalación

| Equipo | Comando |
|---|---|
| Mac / Linux sin ROS | `./andamio/instalar/mac_linux.sh` |
| Windows, para probar (sin WSL) | `powershell -ExecutionPolicy Bypass -File .\andamio\instalar\windows_nativo.ps1`, luego doble clic en `Probar en Windows.bat`: simulador 3D, panel, voz, cámara, modo remoto |
| Windows, para el X2 por cable (ROS 2) | PowerShell **como administrador**: `powershell -ExecutionPolicy Bypass -File .\andamio\instalar\windows.ps1` (instala WSL2 + Ubuntu 22.04 y clona el repo público; hay que haber hecho `git push` antes) |
| Ubuntu 22.04 / WSL2 | `./andamio/instalar/ubuntu.sh --ros` y luego `--sdk ~/aimdk` |

Copia `andamio/.env.ejemplo` a `.env` (en la raíz) y pon `ANTHROPIC_API_KEY` y `ANDAMIO_TOKEN`. `.env` está en `.gitignore`.
El SDK, los PDF y los modelos del robot van en `robots/` (ignorada por Git salvo su `LEEME.md`): **no se suben al repo**.

## Antes de mover un robot real (reglas del evento)

- Batería **sobre 50 %**. Humanoide colgado del gancho al inicio; **no** muevas el robot a mano si está encendido.
- Máximo **dos computadores** controlando a la vez. No compiles ni ejecutes en la capa de movimiento (PC1, 10.0.1.40).
- Alguien con la mano en el **botón de emergencia físico** y otra persona con el panel (`--panel`, botón PARAR).
- Primero la plantilla en `--seco` (solo imprime) y en `--robot sim`; recién después el robot.
- El SDK debe ser de la **misma versión que el firmware**.
- Límites por defecto: 0.4 m/s adelante, 0.3 lateral, 0.6 rad/s de giro. Súbelos en `config.yaml` de a poco.
- `--confirmo` (saltar confirmaciones) no se permite con robots reales.

## Escribir una plantilla

```yaml
nombre: Mi misión
requiere: [caminar]            # capacidades que debe tener el robot
parametros: {velocidad: 0.3}   # se sobrescriben con --param velocidad=0.25
pasos:
  - preparar: caminar          # recorre los modos intermedios; pide confirmar al entrar a "estable"
  - caminar: {vx: "${velocidad}", duracion: 3}
    reintentos: 1              # opcional; en_fallo: abortar | continuar | parar
  - girar: {grados: 90}
  - decir: "Listo"
```

Pasos: `preparar` `modo` `caminar` `girar` `parar` `esperar` `decir` `gesto` `brazos` `cabeza` `mano` `escuchar` `entender`
`ejecutar_accion` `voz_bucle` `teleop` `repetir` `si` `grabar` `registrar` `confirmar` `mirar` `buscar` `acercarse`
`expresion` `luces` `video` `audio`.
`python -m andamio MISION --validar` revisa claves, pasos y condiciones sin tocar el robot; `--seco` muestra lo que haría.
Condiciones de `si`: una sola comparación; los textos van entre comillas (`estado.modo == 'caminar'`), un nombre suelto sin
definir es error. La configuración es estricta: una clave `ANDAMIO_SECCION__CLAVE` desconocida o un valor no numérico (NaN) se rechaza al arrancar.
Un error de **seguridad** (batería, modo, parada) nunca se reintenta ni se salta con `en_fallo: continuar`.

### Voz

La plantilla `voz.yaml` define `comandos` (id, descripción, palabras, pasos). El modelo recibe esa lista cerrada y devuelve
una acción **de la lista** o `ninguna`; lo que diga la persona se trata como dato, no como instrucción. "para / detente /
alto" frenan siempre por reglas, sin esperar a la red (incluso "vamos *para* allá": un falso positivo seguro).
Entradas: `--oido texto` (escribes), `--oido panel` (botón Hablar del navegador, Chrome) o `--oido whisper` (micrófono local).
Modelo configurable en `voz.modelo`; `python -m andamio.doctor --probar-claude` comprueba que existe.

### Teleoperación con las gafas

`teleop_grabar.yaml` abre el websocket (puerto 8765) que ya usa el visor de `web/`. Pulsa **calibrar** con las manos en
posición cómoda; el movimiento relativo de tu mano se suma a la muñeca del robot (IK sobre el MJCF), con límite de velocidad
por articulación. `grabar`/`parar` desde el visor guardan el episodio en `datos/` (mismo formato que `bridge/recorder.py`); "parar" en el visor
solo detiene la grabación, no el robot (el robot se frena con PARAR del panel o con "para" por voz).

**Seguridad del websocket:** al iniciar, la consola muestra la URL con un PIN (`ws://<IP>:8765/?pin=XXXX`); pégala en el campo
URL del visor. Sin PIN correcto se rechaza la conexión, y solo se admite un visor a la vez. Fija un PIN propio en
`teleop.pin` o deja que se genere uno nuevo cada vez. `teleop.host` (por defecto `0.0.0.0`, necesario para que lo vean las
gafas) puede ponerse en `127.0.0.1` si todo corre en el mismo equipo.

## Cuando algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `el servicio ... del robot no responde` | cable, IP, versión del SDK, Fast DDS | `ping 10.0.1.41`; IP `10.0.1.2/24`; `export RMW_IMPLEMENTATION=rmw_fastrtps_cpp`; SDK = firmware |
| `falta rclpy` / `aimdk_msgs` | no hiciste `source` del SDK compilado | `source /opt/ros/humble/setup.bash` y `source ~/aimdk/install/local_setup.bash`; o usa `--robot remoto` |
| `el robot rechazo el cambio a ...` | transición no permitida | usa `preparar` (recorre la ruta); el grafo de modos es una suposición: ajusta `nucleo/modos.py` |
| `el robot no llego a ... en 12 s` | no está de pie, alarma activa | revisa el robot; sube `x2.espera_modo_s` |
| `bateria X% por debajo del minimo` | batería | cambia/carga la batería |
| `PARADA DE EMERGENCIA` | batería crítica, perdió conexión, modo inesperado o botón | revisa la causa; `reanudar` en el panel levanta la parada |
| `... fuera del alcance del robot` (teleop) | mano lejos del rango | acerca la mano o pulsa calibrar |
| la voz no entiende | sin red / sin clave | revisa `.env`; funciona con palabras clave sin internet |
| `no se pudo cargar mc_sdk_zsl_1_py` (D1) | solo Linux, Python 3.10 | define `d1.sdk` con la carpeta que tiene `lib/` |

Todo queda en el JSONL que pases con `--log alertas.jsonl`.

## Lo que NO está verificado (decídelo con el robot delante)

- Corre sin robot en pruebas automáticas (`python -m pytest andamio/tests`): el adaptador del X2 se probó contra un
  `rclpy` y `aimdk_msgs` simulados, **no** contra el SDK real.
- El **grafo de transiciones de modo** es una suposición (el diagrama del manual es una imagen).
- Las **poses de ejemplo** de `manos.yaml` y el cierre de la mano dexterosa (factor 0.8 sobre "el doble de la mitad") son
  estimaciones: pruébalas en `--robot sim` y ajústalas.
- El orden de los 7 ángulos por brazo es el de la cadena hombro→muñeca del MJCF; confirma contra el SDK en el evento.
- El mensaje de batería (`/aima/hal/pmu/stat`) puede venir de otro paquete de mensajes; si no se encuentra, se avisa y la
  batería se revisa a ojo.
- El D1 está escrito contra la documentación del SDK `zsl-1`, sin robot.
