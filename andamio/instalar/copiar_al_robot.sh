#!/usr/bin/env bash
# Copia Andamio a la unidad de desarrollo del X2 (o a su contenedor) y deja listo el servidor.
#   ./andamio/instalar/copiar_al_robot.sh USUARIO[@HOST]    (HOST por defecto 10.0.1.41)
# El usuario y la clave de la unidad los dan los organizadores. NUNCA copies a 10.0.1.40 (PC1).
# Por el WiFi del robot (salto por 192.168.88.88):
#   SSH="ssh -J USUARIO@192.168.88.88" ./andamio/instalar/copiar_al_robot.sh agi@10.0.1.41
set -euo pipefail
cd "$(dirname "$0")/../.."
DEST="${1:?uso: copiar_al_robot.sh usuario[@host]}"
case "$DEST" in *@*) ;; *) DEST="$DEST@10.0.1.41";; esac
case "$DEST" in *10.0.1.40*) echo "10.0.1.40 es PC1 (control de movimiento): prohibido desarrollar ahi"; exit 2;; esac
SSH="${SSH:-ssh}"
echo "==> copiando a $DEST:~/andamio_robot"
$SSH "$DEST" 'mkdir -p ~/andamio_robot'
tar cf - --exclude='__pycache__' --exclude='tests' --exclude='*.pyc' andamio vision/modelos/yolo11n.onnx \
  | $SSH "$DEST" 'tar xf - -C ~/andamio_robot'
cat <<'FIN'

Copiado. En el robot (ssh), con el SDK compilado y su setup cargado:

  cd ~/andamio_robot
  export ANDAMIO_TOKEN='el-mismo-que-en-tu-.env'
  python3 -m andamio.servidor_robot --robot x2          # escucha en el puerto 8790
  # con camara para buscar/acercarse (una vez: pip install opencv-python-headless numpy):
  python3 -m andamio.servidor_robot --robot x2 --ojo x2

En tu portatil:  python -m andamio.doctor --robot remoto  &&  python -m andamio saludar --robot remoto
Con camara:     python -m andamio buscar_persona --robot remoto --ojo remoto --panel
FIN
