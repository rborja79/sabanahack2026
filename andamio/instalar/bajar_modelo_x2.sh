#!/usr/bin/env bash
# Baja el modelo 3D oficial del X2 (MJCF + mallas) del repo publico de AgiBot a robots/X2_URDF.
# Lo usan --robot sim, el visor 3D, la teleoperacion y los limites de los brazos. Se puede repetir.
set -euo pipefail
cd "$(dirname "$0")/../.."
DEST=robots/X2_URDF
if [ -f "$DEST/scene.xml" ] && [ -f "$DEST/meshes/pelvis.stl" ]; then echo "    modelo del X2 ya esta en $DEST"; exit 0; fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "    bajando el modelo del X2 (AgibotTech/agibot_x2_urdf)..."
git clone -q --depth 1 --filter=blob:none --sparse https://github.com/AgibotTech/agibot_x2_urdf.git "$TMP/x2"
git -C "$TMP/x2" sparse-checkout set X2_URDF-v1.4.0 >/dev/null
mkdir -p robots
rm -rf "$DEST"
cp -R "$TMP/x2/X2_URDF-v1.4.0" "$DEST"
echo "    modelo del X2 listo en $DEST"
