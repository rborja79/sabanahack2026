# Paso a paso para el equipo

Esto es lo unico que tienen que hacer antes del viernes. Toma entre 15 y 30
minutos. Haganlo con tiempo, no el mismo dia.

**No hace falta tener visor ni camara para probar todo.** El kit trae un
emulador de Quest y un cliente de terminal.

## 1. Instalar lo basico

Revisen primero si ya lo tienen:

```bash
python3 --version    # 3.10 o superior
node --version       # 20 o superior
git --version
```

Lo que falte:

- **Windows**: instalen [Python](https://www.python.org/downloads/) marcando
  **Add python.exe to PATH**, [Node](https://nodejs.org) y
  [Git](https://git-scm.com). Nada mas.
- **macOS**: `brew install python@3.12 node git`
- **Ubuntu**: `sudo apt-get install -y python3 python3-venv nodejs npm git libosmesa6`

## 2. Bajar el repositorio

No usen un zip ni un tar. Clonen:

```bash
git clone https://github.com/rborja79/sabanahack2026.git
cd sabanahack2026
```

## 3. Instalar

**Windows**, en PowerShell, parados en la carpeta:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

**macOS y Linux**, en la terminal:

```bash
./setup.sh
```

Al final tiene que decir estas dos lineas:

```
robot ok · bodies 30 · error IK 0.98 mm · estado 90+120 valores
vision ok · detector yolo11n cargado desde el repo
```

Si dicen eso, quedo listo. Si se cae, manden al grupo la linea completa del
error, no una foto recortada.

## 4. Probar que funciona

### Lo mas rapido, sin navegador

```bash
cd bridge && python server.py          # terminal 1
cd bridge && python cliente_prueba.py  # terminal 2
```

El segundo dibuja un circulo con la mano del robot, graba el episodio y
revisa que coincida. Tiene que terminar en `prueba OK`.

### Con el visor web

Dos terminales:

```bash
# terminal 1
source .venv/bin/activate          # Windows PowerShell: .\.venv\Scripts\Activate.ps1
cd bridge && python server.py --modelo unitree_g1
```

```bash
# terminal 2
cd web && npm run dev
```

Abran la direccion que imprime vite y pulsen **Conectar**. Tiene que aparecer
un humanoide. Arrastren las esferas de colores con el raton y el robot sigue la
mano. Pulsen **Grabar**, muevan un poco, **Parar**, y revisen:

```bash
python datos/cargar.py
```

### Probar VR sin tener visor

A la misma direccion le agregan `?emular`:

```
http://localhost:5173/?emular
http://localhost:5173/?emular=manos
```

El navegador finge ser un Quest 3. Aparece el boton **ENTER VR** y unos
controles en pantalla para mover la cabeza y las manos. El codigo que corre es
el mismo de VR de verdad, asi que sirve para encontrar errores desde ya.

### Probar el detector de objetos

```bash
python vision/objetos.py --fuente 0            # camara del portatil
python vision/objetos.py --fuente una_foto.jpg --salida resultado.png
```

El modelo viene dentro del repo, no hay que descargar nada.

## 5. Leer

En este orden, son 15 minutos:

1. `README.md`: que hay y como se conectan las piezas
2. `docs/viernes.md`: el plan del dia y el reparto de roles
3. `docs/quest.md`: solo quien vaya a manejar el visor de verdad

## 6. Opcional, si alcanzan

**Teleoperar con la camara**, sin visor:

```bash
python vision/marcador.py --imprimir hoja.png   # imprimen la hoja
python vision/marcador.py                       # pegan los marcadores a la mano
```

**Entrar en VR de verdad** desde un Quest: `docs/quest.md`. Se necesita cable
USB y modo desarrollador.

## Si algo falla

| Sintoma | Que hacer |
|---|---|
| `setup.sh: permission denied` | `chmod +x setup.sh` |
| PowerShell no deja correr el script | usen el comando con `-ExecutionPolicy Bypass` tal cual esta arriba |
| `python` no existe o abre la Microsoft Store | reinstalen Python marcando "Add python.exe to PATH" |
| El visor abre pero no hay robot | revisen que exista `web/public/robots/unitree_g1.glb` |
| En Linux, error de OpenGL | `sudo apt-get install -y libosmesa6` |
| Fallo la descarga de MediaPipe | es opcional, ignorenlo: el detector y ArUco no lo usan |

Lo importante es llegar con el paso 4 funcionando. Lo demas se resuelve el
viernes entre todos.
