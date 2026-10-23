#!/usr/bin/env bash
# Instala Andamio en Ubuntu 22.04 (nativo o dentro de WSL2) con ROS 2 Humble y, si hay SDK, lo compila.
#   ./andamio/instalar/ubuntu.sh [--ros] [--sdk RUTA_AIMDK] [--voz] [--sim-x2]
#   --ros     instala ROS 2 Humble (base) y lo necesario para compilar el SDK AimDK
#   --sdk     compila el SDK en esa carpeta (la que tiene src/ del AimDK)
#   --voz     microfono local con Whisper (opcional)
#   --sim-x2  dependencias del simulador oficial del X2 (ros-humble-desktop-full, ~2 GB)
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ="$(pwd)"
ROS=0; SDK=""; VOZ=0; SIM=0
while [ $# -gt 0 ]; do
  case "$1" in
    --ros) ROS=1;; --sdk) SDK="$2"; shift;; --voz) VOZ=1;; --sim-x2) SIM=1; ROS=1;;
    *) echo "opcion desconocida: $1"; exit 2;;
  esac; shift
done
info () { printf "\n\033[36m==> %s\033[0m\n" "$*"; }
aviso () { printf "\033[33m    %s\033[0m\n" "$*"; }

. /etc/os-release
[ "${VERSION_ID:-}" = "22.04" ] || aviso "este instalador esta pensado para Ubuntu 22.04 (ROS 2 Humble); tienes ${PRETTY_NAME:-desconocido}"

info "paquetes base"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git curl build-essential iputils-ping net-tools libportaudio2

if [ "$ROS" = 1 ]; then
  info "ROS 2 Humble"
  if [ ! -f /opt/ros/humble/setup.bash ]; then
    sudo apt-get install -y software-properties-common gnupg2 lsb-release ca-certificates
    sudo add-apt-repository -y universe
    sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") main" \
      | sudo tee /etc/apt/sources.list.d/ros2.list >/dev/null
    sudo apt-get update -y
  fi
  PAQ_ROS=ros-humble-ros-base
  [ "$SIM" = 1 ] && PAQ_ROS=ros-humble-desktop-full
  sudo apt-get install -y "$PAQ_ROS" ros-humble-rmw-fastrtps-cpp ros-humble-grid-map-msgs ros-humble-grid-map-ros \
    python3-colcon-common-extensions cmake libcurl4-openssl-dev libeigen3-dev libgflags-dev libncurses-dev libyaml-cpp-dev pkg-config
  # trayectorias que usa el ejemplo oficial de control articular
  python3 -m pip install --user --no-cache-dir -U pip packaging "scikit-build-core<0.10" nanobind || true
  python3 -m pip install --user --no-cache-dir --no-build-isolation ruckig==0.15.3 || aviso "ruckig no se instalo: solo hace falta para los ejemplos de motores"
  if ! grep -q 'rmw_fastrtps_cpp' ~/.bashrc; then
    {
      echo ''
      echo '# --- Andamio / X2 ---'
      echo 'source /opt/ros/humble/setup.bash'
      echo 'export RMW_IMPLEMENTATION=rmw_fastrtps_cpp'
    } >> ~/.bashrc
    echo "    ~/.bashrc actualizado (ROS y Fast DDS)"
  fi
fi

if [ "$SIM" = 1 ]; then
  info "carpeta de ejecucion del control de movimiento (simulador oficial)"
  sudo mkdir -p /agibot/data/var/ && sudo chown "$USER:$USER" -R /agibot
fi

info "entorno de python de Andamio"
# --system-site-packages para ver rclpy y aimdk_msgs de ROS dentro del entorno
[ -d .venv ] || python3 -m venv --system-site-packages .venv
PY="$RAIZ/.venv/bin/python"
"$PY" -m pip install --upgrade pip --quiet
"$PY" -m pip install -r andamio/requirements.txt --quiet
[ "$VOZ" = 1 ] && "$PY" -m pip install -r andamio/requirements-voz.txt --quiet
[ -f .env ] || { cp andamio/.env.ejemplo .env; aviso "se creo .env: pon tu ANTHROPIC_API_KEY y un ANDAMIO_TOKEN"; }
grep -q '^\.env$' .gitignore 2>/dev/null || printf '\n.env\n' >> .gitignore

if [ -n "$SDK" ]; then
  info "compilando el SDK AimDK en $SDK"
  [ -d "$SDK" ] || { echo "no existe $SDK"; exit 1; }
  ( set +u; source /opt/ros/humble/setup.bash; cd "$SDK" && colcon build )
  if ! grep -q "$SDK/install/local_setup.bash" ~/.bashrc; then
    echo "source $SDK/install/local_setup.bash" >> ~/.bashrc
  fi
  echo "    SDK compilado. Abre una terminal nueva (o: source ~/.bashrc)."
else
  aviso "sin --sdk: cuando tengas la carpeta del AimDK (la de la unidad de desarrollo, version igual al firmware) corre:"
  aviso "  ./andamio/instalar/ubuntu.sh --sdk ~/aimdk"
fi

info "modelo 3D del X2"
./andamio/instalar/bajar_modelo_x2.sh || aviso "no se pudo bajar el modelo del X2 (sin internet?): el simulador 3D no funcionara"

info "pruebas y diagnostico"
"$PY" -m pytest andamio/tests -q -x 2>&1 | tail -3 || true
"$PY" -m andamio.doctor --robot x2 || true
cat <<'FIN'

Conexion al X2: cable Gigabit al robot, tu IP fija 10.0.1.2/24, ping 10.0.1.41.
  source .venv/bin/activate && source ~/.bashrc
  python -m andamio.doctor --robot x2
  python -m andamio saludar --robot x2
Antes de mover nada lee andamio/LEEME.md (reglas del evento y parada de emergencia).
FIN
