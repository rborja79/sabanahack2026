#!/bin/bash
# Doble clic en el Finder: muestra que cambio, hace commit y lo sube a GitHub (rama main).
cd "$(dirname "$0")"
echo "=== Subir al repo ==="
git status --short
if [ -z "$(git status --porcelain)" ]; then
  if [ -n "$(git log origin/main..main --oneline 2>/dev/null)" ]; then
    echo "No hay cambios nuevos, pero hay commits sin subir:"; git log origin/main..main --oneline
    git push origin main && echo && echo "SUBIDO a GitHub." || echo "No se pudo subir: revisa el mensaje de arriba (clave de GitHub)."
  else
    echo "No hay cambios."
  fi
  read -r -p "Enter para cerrar" _; exit 0
fi
if git status --porcelain | grep -E '(^|/)\.env$|\.pem$|id_rsa|robots/.+\.(pdf|zip|tar)' >/dev/null; then
  echo "OJO: hay archivos que parecen secretos o material del fabricante. No subo nada."; read -r -p "Enter" _; exit 1
fi
read -r -t 30 -p "Subir estos cambios? (s/n; en 30 s sube solo) [s]: " ok || echo
[ "${ok:-s}" = "s" ] || exit 0
read -r -t 30 -p "Mensaje del commit [Andamio: autonomia, voz, plantillas y seguridad]: " msg || echo
git add -A
git commit -q -m "${msg:-Andamio: autonomia, voz, plantillas y seguridad}" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01U7uj8i5fbPnzx8SNocJX2h" && echo "commit listo"
git pull --rebase -q origin main && git push origin main && echo && echo "SUBIDO a GitHub." || echo "No se pudo subir: revisa el mensaje de arriba (clave de GitHub o conflicto)."
read -r -p "Enter para cerrar" _
