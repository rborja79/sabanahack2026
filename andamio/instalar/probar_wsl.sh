#!/usr/bin/env bash
# Menu de pruebas dentro de WSL2 / Ubuntu (equipo x86 con Windows 11).
#   ./andamio/instalar/probar_wsl.sh
cd "$(dirname "$0")/../.."
SO=./andamio/instalar/sim_oficial.sh
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
CAM="${CAMARA_WINDOWS:-http://127.0.0.1:8781/video}"
cat <<'MENU'
=== Andamio en WSL2 ===
 Simulador OFICIAL de AgiBot (fisica real: camina y se equilibra con el mismo control del X2):
   1) Iniciar el simulador oficial y caminar
   2) Simulador oficial + voz (en el panel escribe: camina, gira a la izquierda, saluda, para)
   3) Simulador oficial + buscar y acercarse a una persona con la camara de Windows
      (antes, en Windows: 'Probar en Windows.bat' opcion 8)
   4) Simulador oficial + saludar (gesto de fabrica)
   5) Diagnostico del simulador oficial
   6) Parar el simulador oficial
 Simulador ligero del andamio (sin fisica):
   7) Buscar persona en 3D
   8) Voz en 3D
MENU
read -r -t 30 -p "Numero [1]: " op || echo
case "${op:-1}" in
  1) $SO iniciar && $SO correr caminar --panel ;;
  2) $SO iniciar && $SO correr voz --panel --oido panel ;;
  3) $SO iniciar && ANDAMIO_VISION__CAMARA="$CAM" $SO correr buscar_persona --ojo camara --panel ;;
  4) $SO iniciar && $SO correr saludar --panel ;;
  5) bash -lc "set +u; source /opt/ros/humble/setup.bash; export RMW_IMPLEMENTATION=rmw_fastrtps_cpp; \
       [ -f ~/x2_simulation/aimdk/install/local_setup.bash ] && source ~/x2_simulation/aimdk/install/local_setup.bash; \
       $PY -m andamio.doctor --robot x2sim" ;;
  6) $SO parar ;;
  7) $PY -m andamio buscar_persona --robot sim --ojo simulado --ver3d --panel --confirmo ;;
  8) $PY -m andamio voz --robot sim --ver3d --panel --oido panel --confirmo ;;
  *) echo "opcion desconocida" ;;
esac
