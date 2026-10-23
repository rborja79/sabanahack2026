#!/bin/bash
# Doble clic en el Finder: instala lo que falte (la primera vez tarda unos minutos) y abre una demo.
cd "$(dirname "$0")"
echo "=== Andamio · probar en el Mac ==="
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import cv2, yaml, mujoco, websockets, anthropic" 2>/dev/null; then
  echo "Instalando (solo la primera vez)..."
  ./andamio/instalar/mac_linux.sh || { echo; echo "La instalacion fallo: copia el error de arriba."; read -r -p "Enter para cerrar"; exit 1; }
fi
source .venv/bin/activate
echo
echo "Que quieres probar? (se abre el panel en el navegador; ahi esta el boton PARAR y 'Confirmar')"
echo "  1) Autonomia con TU CAMARA: busca a una persona y se acerca (alejate 2-3 m y camina hacia el Mac)"
echo "  2) Autonomia SIMULADA, sin camara (persona imaginaria en el mapa)"
echo "  3) Voz: escribe o di 'camina', 'gira a la izquierda', 'saluda', 'para'"
echo "  4) Caminar: plantilla basica"
echo "  5) Solo el panel con la camara (para elegir la plantilla desde ahi)"
read -r -t 20 -p "Numero (si no eliges en 20 s arranca la 2) [2]: " op || echo
case "${op:-2}" in
  1) python -m andamio buscar_persona --robot falso --ojo camara --panel ;;
  2) python -m andamio buscar_persona --robot falso --ojo simulado --panel --confirmo ;;
  3) python -m andamio voz --robot falso --panel --oido panel ;;
  4) python -m andamio caminar --robot falso --panel ;;
  *) python -m andamio --robot falso --ojo camara --panel ;;
esac
echo
read -r -p "Termino (Ctrl+C para salir del panel). Enter para cerrar esta ventana" _
