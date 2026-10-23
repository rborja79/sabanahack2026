#!/bin/bash
# Doble clic en el Finder: instala lo que falte (la primera vez tarda unos minutos) y abre una demo.
cd "$(dirname "$0")"
echo "=== Andamio · probar en el Mac ==="
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import cv2, yaml, mujoco, websockets, anthropic" 2>/dev/null; then
  echo "Instalando (solo la primera vez)..."
  ./andamio/instalar/mac_linux.sh || { echo; echo "La instalacion fallo: copia el error de arriba."; read -r -p "Enter para cerrar"; exit 1; }
fi
source .venv/bin/activate
# El visor 3D de MuJoCo en el Mac necesita mjpython (viene con mujoco)
PY3D=python; [ -x .venv/bin/mjpython ] && PY3D=.venv/bin/mjpython
SIM=""; python -c "from andamio.robots.sim_mujoco import buscar_modelo; buscar_modelo()" 2>/dev/null && SIM=1
[ -n "$SIM" ] || echo "(No hay modelo 3D del X2 en robots/X2_URDF: las opciones 1-3 no tendran ventana 3D)"
echo
echo "Que quieres probar? Se abre el panel en el navegador (PARAR, Confirmar, alertas) y, en 1-3, una ventana 3D."
echo "  1) Simulador 3D del X2: busca a una persona (verde) y camina hacia ella"
echo "  2) Simulador 3D + voz: en el panel escribe o di 'camina', 'gira a la izquierda', 'saluda', 'para'"
echo "  3) Simulador 3D + brazos y manos"
echo "  4) Autonomia con TU CAMARA (alejate 2-3 m y camina hacia el Mac)"
echo "  5) Pantalla, sonido y luces del X2 (en el Mac solo anuncia lo que haria)"
echo "  6) Solo el panel con la camara"
read -r -t 20 -p "Numero (si no eliges en 20 s arranca la 1) [1]: " op || echo
case "${op:-1}" in
  1) $PY3D -m andamio buscar_persona --robot sim --ojo simulado --ver3d --panel --confirmo ;;
  2) $PY3D -m andamio voz --robot sim --ver3d --panel --oido panel --confirmo ;;
  3) $PY3D -m andamio manos --robot sim --ver3d --panel --confirmo ;;
  4) python -m andamio buscar_persona --robot falso --ojo camara --panel ;;
  5) python -m andamio medios --robot falso --panel ;;
  *) python -m andamio --robot falso --ojo camara --panel ;;
esac
echo
read -r -p "Termino (Ctrl+C para salir). Enter para cerrar esta ventana" _
