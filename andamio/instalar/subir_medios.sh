#!/usr/bin/env bash
# Sube videos (.mp4) y audios (.wav) para la pantalla y el parlante del X2.
# Van al computador de INTERACCION (PC3, 10.0.1.42), no al de desarrollo: asi lo pide el manual.
#   ./andamio/instalar/subir_medios.sh USUARIO video.mp4 saludo.wav ...
# Por el WiFi del robot (salto por 192.168.88.88):
#   SSH="ssh -J USUARIO@192.168.88.88" SCP="scp -J USUARIO@192.168.88.88" ./andamio/instalar/subir_medios.sh USUARIO ...
# El usuario y la clave del PC3 los dan los organizadores.
set -euo pipefail
U="${1:?uso: subir_medios.sh usuario[@host] archivo.mp4 archivo.wav ...}"; shift
[ "$#" -gt 0 ] || { echo "faltan archivos"; exit 1; }
HOST="${HOST:-10.0.1.42}"; DIR="${DIR:-/var/tmp/andamio_medios}"
case "$U" in *@*) DEST="$U";; *) DEST="$U@$HOST";; esac
case "$DEST" in *10.0.1.40*|*192.168.88.88*) echo "ese es el PC de movimiento (PC1): los medios van al PC3 (10.0.1.42)"; exit 2;; esac
SSH="${SSH:-ssh}"; SCP="${SCP:-scp}"
for f in "$@"; do
  [ -f "$f" ] || { echo "no existe: $f"; exit 1; }
  case "$f" in
    *.mp4|*.MP4|*.wav|*.WAV|*.pcm) ;;
    *.mp3|*.m4a) echo "$f: el robot no reproduce mp3/m4a. Convierte:  ffmpeg -i \"$f\" -ar 16000 -ac 1 salida.wav"; exit 1;;
    *) echo "$f: formato no soportado (usa .mp4 para video y .wav para audio)"; exit 1;;
  esac
done
$SSH "$DEST" "mkdir -p '$DIR' && chmod 755 '$DIR'"
$SCP "$@" "$DEST:$DIR/"
$SSH "$DEST" "chmod a+r '$DIR'/*"
echo
echo "Listo. En una plantilla:   - video: {archivo: $(basename "$1")}     - audio: {archivo: saludo.wav}"
