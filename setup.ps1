# Instalacion en Windows. Abre PowerShell en la carpeta del repo y corre:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Info  ($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Aviso ($t) { Write-Host "    $t" -ForegroundColor Yellow }

# ---------------------------------------------------------------- requisitos
Info "revisando requisitos"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "falta git. Instalalo desde https://git-scm.com y vuelve a abrir PowerShell."
}

# En Windows puede haber 'python' (el real) o solo el atajo de la Microsoft Store,
# que no sirve. Se prueba de verdad antes de seguir.
$python = $null
foreach ($cand in @("python", "python3", "py")) {
  if (-not (Get-Command $cand -ErrorAction SilentlyContinue)) { continue }
  $salida = & $cand -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>$null
  if ($LASTEXITCODE -eq 0 -and $salida) {
    $n = $salida.Trim().Split(" ")
    if ([int]$n[0] -eq 3 -and [int]$n[1] -ge 10) { $python = $cand; break }
  }
}
if (-not $python) {
  throw "no hay Python 3.10 o superior. Instalalo desde https://www.python.org/downloads/ marcando 'Add python.exe to PATH'."
}
Write-Host "    python: $python"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Aviso "falta node: el visor no va a compilar. Instala Node 20 o superior desde https://nodejs.org"
}

# ---------------------------------------------------------------- python
Info "entorno de python"
if (-not (Test-Path ".venv")) { & $python -m venv .venv }
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "no se creo el entorno en .venv" }
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "fallo la instalacion de paquetes de Python" }
Write-Host "    paquetes listos"

# ---------------------------------------------------------------- modelos de robot
Info "modelos de robot"
if (-not (Test-Path "sim\mujoco_menagerie")) {
  git clone --depth 1 https://github.com/google-deepmind/mujoco_menagerie.git sim\mujoco_menagerie
} else {
  Write-Host "    ya estaba"
}

# ---------------------------------------------------------------- mallas del visor
Info "mallas del visor"
foreach ($m in @("unitree_g1", "unitree_go2", "unitree_z1")) {
  if (Test-Path "web\public\robots\$m.glb") { Write-Host "    $m ya estaba"; continue }
  Push-Location bridge
  & $py export_robot.py --modelo $m --salida "..\web\public\robots\$m.glb" --decimar 6000
  Pop-Location
}

# ---------------------------------------------------------------- modelos de vision
Info "modelos de vision"
New-Item -ItemType Directory -Force -Path "vision\modelos" | Out-Null
function Bajar ($nombre, $url) {
  if (Test-Path "vision\modelos\$nombre") { Write-Host "    $nombre ya estaba"; return }
  try {
    Invoke-WebRequest -Uri $url -OutFile "vision\modelos\$nombre" -UseBasicParsing
    Write-Host "    $nombre listo"
  } catch {
    Aviso "no se pudo bajar $nombre. El modo onnx y ArUco funcionan sin el."
  }
}
Bajar "hand_landmarker.task" "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
Bajar "efficientdet_lite0.tflite" "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float32/1/efficientdet_lite0.tflite"

# ---------------------------------------------------------------- visor
Info "visor web"
if (Get-Command node -ErrorAction SilentlyContinue) {
  Push-Location web
  npm install --silent
  Pop-Location
  Write-Host "    node_modules listo"
}

# ---------------------------------------------------------------- prueba
Info "prueba rapida"
& $py "bridge\prueba.py"
if ($LASTEXITCODE -ne 0) { throw "la prueba del robot no paso" }

Write-Host ""
Write-Host "Listo. Para arrancar, dos ventanas de PowerShell:" -ForegroundColor Green
Write-Host ""
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  cd bridge; python server.py --modelo unitree_g1"
Write-Host ""
Write-Host "  cd web; npm run dev"
Write-Host ""
Write-Host "Abre lo que imprima vite y pulsa Conectar. Lee README.md."
