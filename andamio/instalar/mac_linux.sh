#!/usr/bin/env bash
# Instala Andamio en Mac o Linux (sin ROS). Sirve para simular, planear, usar el visor y
# controlar un robot por el servidor remoto. Se puede repetir sin dano.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ="$(pwd)"
info () { printf "\n\033[36m==> %s\033[0m\n" "$*"; }
aviso () { printf "\033[33m    %s\033[0m\n" "$*"; }

info "python"
PY3=$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3 || true)
[ -n "$PY3" ] || { echo "falta python3 (3.10 o mas)"; exit 1; }
"$PY3" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || { echo "se necesita Python 3.10 o mas"; exit 1; }
# En el Mac la carpeta puede estar en iCloud (Documentos): un entorno con miles de archivos no debe
# sincronizarse, asi que vive en .venv.nosync (iCloud ignora *.nosync) y .venv es un enlace a el.
if [ "$(uname)" = "Darwin" ] && [ ! -e .venv ]; then
  "$PY3" -m venv .venv.nosync && ln -s .venv.nosync .venv
fi
[ -e .venv ] || "$PY3" -m venv .venv
if [ -x .venv/bin/python ]; then PY="$RAIZ/.venv/bin/python"; else PY="$RAIZ/.venv/Scripts/python.exe"; fi
"$PY" -m pip install --upgrade pip --quiet
"$PY" -m pip install -r andamio/requirements.txt --quiet
echo "    paquetes listos"
if [ "${1:-}" = "--voz" ]; then
  "$PY" -m pip install -r andamio/requirements-voz.txt --quiet && echo "    voz local lista"
fi

info "modelo 3D del X2"
./andamio/instalar/bajar_modelo_x2.sh || aviso "no se pudo bajar el modelo del X2 (sin internet?): el simulador 3D no funcionara"

info "archivos de configuracion"
[ -f .env ] || { cp andamio/.env.ejemplo .env; aviso "se creo .env: pon tu ANTHROPIC_API_KEY y un ANDAMIO_TOKEN"; }
if ! grep -q '^\.env$' .gitignore 2>/dev/null; then printf '\n.env\n' >> .gitignore; fi

info "pruebas"
"$PY" -m pytest andamio/tests -q < /dev/null 2>&1 | tail -3 || aviso "algunas pruebas fallaron (arriba dice cuales); lo demas quedo instalado"

info "diagnostico"
"$PY" -m andamio.doctor || true

cat <<'FIN'

Listo. Ejemplos (con el entorno activado: source .venv/bin/activate):

  python -m andamio --listar
  python -m andamio caminar --robot sim --confirmo       # simulacion, sin robot
  python -m andamio voz --robot sim --panel              # panel en el navegador, voz por el navegador
  python -m andamio buscar_persona --robot falso --ojo camara --panel     # autonomia con tu webcam
  python -m andamio buscar_persona --robot falso --ojo simulado --panel   # autonomia sin camara
  python -m andamio.doctor --robot remoto                # revisa la conexion al servidor del robot

Lee andamio/LEEME.md.
FIN
