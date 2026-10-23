#!/usr/bin/env bash
# Simulador OFICIAL del X2 (AgiBot "X2 Sim + MC Deployment"): MuJoCo con fisica + el mismo control de
# movimiento (mc) del robot real. El robot camina, se equilibra y se levanta de verdad, y el andamio
# lo maneja con el mismo ROS 2 que usara con el X2:  python -m andamio PLANTILLA --robot x2sim
#
# Solo x86_64 con Ubuntu 22.04 (nativo o WSL2 en Windows 11). No funciona en Mac Apple Silicon.
#
#   ./andamio/instalar/sim_oficial.sh preparar CARPETA   # una vez: CARPETA = donde bajaste aimdk, sim_mujoco y mc
#   ./andamio/instalar/sim_oficial.sh iniciar            # abre la ventana de MuJoCo y arranca mc
#   ./andamio/instalar/sim_oficial.sh correr caminar --panel     # corre una plantilla contra el simulador
#   ./andamio/instalar/sim_oficial.sh ver                # mira los registros (Ctrl+B y luego D para salir)
#   ./andamio/instalar/sim_oficial.sh parar
#
# Los paquetes se bajan de la barra flotante de la documentacion del SDK (x2-aimdk.agibot.com, seccion
# Extras: mc-x86 y sim_mujoco-x86) junto con el SDK AimDK. La guia oficial es el capitulo
# "Simulation and Reinforcement Learning > X2 Sim + MC Deployment" del manual del AimDK.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ="$(pwd)"
SIM="${X2_SIM:-$HOME/x2_simulation}"
SESION=x2sim
info () { printf "\n\033[36m==> %s\033[0m\n" "$*"; }
aviso () { printf "\033[33m    %s\033[0m\n" "$*"; }
error () { printf "\033[31m%s\033[0m\n" "$*"; exit 1; }

ENTORNO="set +u; source /opt/ros/humble/setup.bash; export RMW_IMPLEMENTATION=rmw_fastrtps_cpp; \
[ -f '$SIM/aimdk/install/local_setup.bash' ] && source '$SIM/aimdk/install/local_setup.bash'"

revisar_maquina () {
  [ "$(uname -m)" = "x86_64" ] || error "el simulador oficial solo corre en x86_64 (este equipo es $(uname -m))"
  . /etc/os-release
  [ "${VERSION_ID:-}" = "22.04" ] || aviso "la guia oficial pide Ubuntu 22.04; tienes ${PRETTY_NAME:-?}"
  if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    aviso "no hay pantalla grafica (DISPLAY vacio): en WSL2 hace falta Windows 11 con WSLg (wsl --update)"
  fi
}

# Busca dentro de $1 una carpeta que tenga el archivo $2 (por ejemplo bin/start_sim.sh) y la imprime.
buscar () {
  local base="$1" marca="$2" f
  f="$(find "$base" -maxdepth 5 -path "*/$marca" -print -quit 2>/dev/null || true)"
  [ -n "$f" ] && echo "${f%/$marca}"
}

preparar () {
  local origen="${1:-}"
  [ -n "$origen" ] && [ -d "$origen" ] || error "uso: sim_oficial.sh preparar CARPETA (la carpeta con lo que bajaste: aimdk, sim_mujoco, mc o sus .tar.gz/.zip)"
  origen="$(cd "$origen" && pwd)"
  revisar_maquina

  info "paquetes del sistema (ROS 2 Humble completo y dependencias de la guia oficial; tarda la primera vez)"
  "$RAIZ/andamio/instalar/ubuntu.sh" --sim-x2
  sudo apt-get install -y tmux libgl1 libgl1-mesa-dri libglx-mesa0 mesa-utils liboctomap1.9 libopencv-dev \
    libscrypt0 ros-humble-cv-bridge ros-humble-joy x11-xserver-utils unzip

  info "descomprimiendo lo descargado"
  local tmp; tmp="$(mktemp -d)"
  shopt -s nullglob
  for a in "$origen"/*.tar.gz "$origen"/*.tgz "$origen"/*.tar "$origen"/*.zip; do
    echo "    $(basename "$a")"
    case "$a" in
      *.zip) unzip -q "$a" -d "$tmp" ;;
      *) tar xf "$a" -C "$tmp" ;;
    esac
  done
  shopt -u nullglob

  local d_sim d_mc d_sdk
  d_sim="$(buscar "$origen" bin/start_sim.sh || true)"; [ -n "$d_sim" ] || d_sim="$(buscar "$tmp" bin/start_sim.sh || true)"
  d_mc="$(buscar "$origen" bin/em_run.sh || true)";     [ -n "$d_mc" ]  || d_mc="$(buscar "$tmp" bin/em_run.sh || true)"
  d_sdk="$(buscar "$origen" src/aimdk_msgs || true)";   [ -n "$d_sdk" ] || d_sdk="$(buscar "$tmp" src/aimdk_msgs || true)"
  [ -n "$d_sdk" ] || d_sdk="$(dirname "$(find "$origen" "$tmp" -maxdepth 4 -type d -name src -path '*aimdk*' -print -quit 2>/dev/null)" 2>/dev/null || true)"
  [ -n "$d_sim" ] || error "no encontre sim_mujoco (debe traer bin/start_sim.sh) en $origen"
  [ -n "$d_mc" ]  || error "no encontre mc (debe traer bin/em_run.sh) en $origen"
  [ -n "$d_sdk" ] && [ -d "$d_sdk/src" ] || error "no encontre el SDK aimdk (debe traer src/) en $origen"

  info "copiando a $SIM"
  mkdir -p "$SIM"
  for par in "sim_mujoco:$d_sim" "mc:$d_mc" "aimdk:$d_sdk"; do
    nombre="${par%%:*}"; desde="${par#*:}"
    if [ "$(cd "$desde" && pwd)" != "$SIM/$nombre" ]; then
      rm -rf "${SIM:?}/$nombre"
      cp -a "$desde" "$SIM/$nombre"
    fi
    echo "    $nombre <- $desde"
  done
  rm -rf "$tmp"
  chmod +x "$SIM"/sim_mujoco/bin/*.sh "$SIM"/mc/bin/*.sh 2>/dev/null || true

  info "carpeta de ejecucion del control de movimiento"
  sudo mkdir -p /agibot/data/var/ && sudo chown "$USER:$USER" -R /agibot

  info "compilando el SDK del simulador (colcon build, unos minutos)"
  ( eval "$ENTORNO"; cd "$SIM/aimdk" && colcon build )

  echo
  echo "Listo. Ahora:  ./andamio/instalar/sim_oficial.sh iniciar"
}

iniciar () {
  revisar_maquina
  for d in sim_mujoco mc aimdk; do [ -d "$SIM/$d" ] || error "falta $SIM/$d: corre primero  sim_oficial.sh preparar CARPETA"; done
  command -v tmux >/dev/null || error "falta tmux: sudo apt-get install -y tmux"
  if tmux has-session -t "$SESION" 2>/dev/null; then
    aviso "el simulador ya estaba corriendo (sim_oficial.sh parar para reiniciarlo)"
  else
    info "terminal 1: MuJoCo (se abre una ventana con el X2)"
    tmux new-session -d -s "$SESION" -n sim \
      "bash -lc \"$ENTORNO; cd '$SIM/sim_mujoco/bin' && ./start_sim.sh -s; echo; echo '[sim terminado] Enter para cerrar'; read\""
    sleep 8
    info "terminal 2: control de movimiento (mc)"
    tmux new-window -t "$SESION" -n mc \
      "bash -lc \"$ENTORNO; cd '$SIM/mc/bin' && unset AGIBOT_SOFTWARE_HOME && ./em_run.sh; echo; echo '[mc terminado] Enter para cerrar'; read\""
  fi
  info "esperando a que el control de movimiento responda (hasta 90 s)"
  local ok=0
  for _ in $(seq 1 45); do
    if bash -lc "$ENTORNO; ros2 service list 2>/dev/null" | grep -q "GetMcAction"; then ok=1; break; fi
    sleep 2
  done
  if [ "$ok" = 1 ]; then
    echo "    mc responde"
    echo
    echo "Simulador listo. Prueba el andamio contra el, por ejemplo:"
    echo "  ./andamio/instalar/sim_oficial.sh correr caminar --panel"
    echo "  ./andamio/instalar/sim_oficial.sh correr voz --panel --oido panel"
  else
    aviso "mc no responde todavia. Mira los registros con:  ./andamio/instalar/sim_oficial.sh ver"
    aviso "si la ventana de MuJoCo pregunta el modelo del robot, elige el que coincide con lo descargado"
  fi
}

correr () {
  [ $# -ge 1 ] || error "uso: sim_oficial.sh correr PLANTILLA [opciones del andamio]"
  tmux has-session -t "$SESION" 2>/dev/null || aviso "el simulador no parece estar corriendo (sim_oficial.sh iniciar)"
  local py="$RAIZ/.venv/bin/python"
  [ -x "$py" ] || py=python3
  bash -lc "$ENTORNO; cd '$RAIZ'; '$py' -m andamio $(printf '%q ' "$@") --robot x2sim"
}

ver () { tmux attach -t "$SESION"; }

parar () {
  if tmux has-session -t "$SESION" 2>/dev/null; then
    tmux send-keys -t "$SESION:mc" C-c 2>/dev/null || true
    sleep 2
    tmux send-keys -t "$SESION:sim" C-c 2>/dev/null || true
    sleep 2
    tmux kill-session -t "$SESION" 2>/dev/null || true
    echo "simulador detenido"
  else
    echo "no estaba corriendo"
  fi
}

estado () {
  tmux has-session -t "$SESION" 2>/dev/null && echo "simulador: corriendo (sesion tmux $SESION)" || echo "simulador: apagado"
  bash -lc "$ENTORNO; ros2 service list 2>/dev/null" | grep -q GetMcAction && echo "mc: responde" || echo "mc: no responde"
}

case "${1:-}" in
  preparar) shift; preparar "$@" ;;
  iniciar) iniciar ;;
  correr) shift; correr "$@" ;;
  ver) ver ;;
  parar) parar ;;
  estado) estado ;;
  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
