#!/usr/bin/env bash
# Instala todo lo que necesita el kit. Se puede correr varias veces sin dano.
set -euo pipefail
cd "$(dirname "$0")"
RAIZ="$(pwd)"

info () { printf "\n\033[36m==> %s\033[0m\n" "$*"; }
aviso () { printf "\033[33m    %s\033[0m\n" "$*"; }

# ---------------------------------------------------------------- requisitos
info "revisando requisitos"
for prog in python3 git; do
  command -v "$prog" >/dev/null || { echo "falta $prog"; exit 1; }
done
command -v node >/dev/null || aviso "falta node: el visor no va a compilar. Instala Node 20 o superior."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || { echo "se necesita Python 3.10 o superior"; exit 1; }

# ---------------------------------------------------------------- python
info "entorno de python"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
echo "    paquetes listos"

# En Linux el render sin pantalla necesita OSMesa.
if [ "$(uname -s)" = "Linux" ] && ! ldconfig -p 2>/dev/null | grep -q libOSMesa; then
  aviso "para render sin pantalla: sudo apt-get install -y libosmesa6"
fi

# ---------------------------------------------------------------- modelos de robot
info "modelos de robot"
if [ ! -d sim/mujoco_menagerie ]; then
  git clone --depth 1 https://github.com/google-deepmind/mujoco_menagerie.git sim/mujoco_menagerie
else
  echo "    ya estaba"
fi

# ---------------------------------------------------------------- mallas para el visor
info "mallas del visor"
for modelo in unitree_g1 unitree_go2 unitree_z1; do
  if [ -f "web/public/robots/$modelo.glb" ]; then
    echo "    $modelo ya estaba"
  else
    ( cd bridge && python export_robot.py --modelo "$modelo" \
        --salida "../web/public/robots/$modelo.glb" --decimar 6000 )
  fi
done

# ---------------------------------------------------------------- modelos de vision
info "modelos de vision"
mkdir -p vision/modelos
bajar () {
  [ -f "vision/modelos/$1" ] && { echo "    $1 ya estaba"; return; }
  curl -fsSL -o "vision/modelos/$1" "$2" && echo "    $1 listo" \
    || aviso "no se pudo bajar $1, el modo camara con manos no va a correr"
}
bajar hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
bajar efficientdet_lite0.tflite \
  https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float32/1/efficientdet_lite0.tflite

# ---------------------------------------------------------------- visor
info "visor web"
if command -v node >/dev/null; then
  ( cd web && npm install --silent )
  echo "    node_modules listo"
fi

# ---------------------------------------------------------------- prueba
info "prueba rapida"
python - <<'PY'
import sys
sys.path.insert(0, "bridge")
from sim import Robot
import numpy as np
r = Robot("unitree_g1")
r.fijar_objetivo("right", r.pos_efector("right") + np.array([0.0, 0.0, 0.12]))
for _ in range(400):
    r.paso()
err = np.linalg.norm(r.pos_efector("right") - r.objetivos["right"])
p, q = r.estado()
print(f"    robot ok · bodies {len(r.nombres_body)} · error IK {err*1000:.2f} mm · estado {len(p)}+{len(q)} valores")
PY

cat <<'FIN'

Listo. Para arrancar:

  source .venv/bin/activate
  cd bridge && python server.py --modelo unitree_g1     # terminal 1
  cd web    && npm run dev                              # terminal 2

Abre lo que imprima vite y pulsa Conectar. Lee README.md.
FIN
