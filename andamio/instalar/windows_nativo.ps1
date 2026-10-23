# Andamio en Windows SIN WSL: simulador 3D del X2, panel, voz, camara y modo remoto.
# (Para hablar con el X2 por cable con ROS 2 hace falta WSL2: andamio\instalar\windows.ps1)
# Abre PowerShell en la carpeta del repo y corre:
#   powershell -ExecutionPolicy Bypass -File .\andamio\instalar\windows_nativo.ps1
$ErrorActionPreference = "Stop"
$raiz = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $raiz
function Info  ($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Aviso ($t) { Write-Host "    $t" -ForegroundColor Yellow }

Info "requisitos"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "falta git: instalalo desde https://git-scm.com y abre PowerShell de nuevo" }
$python = $null
if (Test-Path ".venv\Scripts\python.exe") {
  $python = (Resolve-Path ".venv\Scripts\python.exe").Path      # ya hay un entorno (por ejemplo del setup.ps1): se reutiliza
} else {
  # el lanzador 'py' primero (elige una version concreta); luego python / python3
  $candidatos = @(@("py", "-3.12"), @("py", "-3.11"), @("py", "-3.13"), @("py", "-3.10"), @("python"), @("python3"), @("py"))
  foreach ($c in $candidatos) {
    if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
    $extra = @($c | Select-Object -Skip 1)
    $v = & $c[0] @extra -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $v) {
      $n = "$v".Trim().Split(" ")
      if ([int]$n[0] -eq 3 -and [int]$n[1] -ge 10) {
        $exe = & $c[0] @extra -c "import sys; print(sys.executable)"
        $python = "$exe".Trim(); break
      }
    }
  }
}
if (-not $python) {
  throw "no encontre Python 3.10 o mas nuevo. Prueba en esta ventana:  py --version  y  python --version  (si dice 'Microsoft Store', instala Python desde python.org marcando 'Add python.exe to PATH')"
}
Write-Host "    python: $python"

Info "entorno de python (.venv)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $python -m venv .venv }
if (-not (Test-Path ".venv\Scripts\python.exe")) { throw "no se pudo crear .venv con $python" }
$py = Join-Path $raiz ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r andamio\requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "fallo la instalacion de paquetes de Python" }
Write-Host "    paquetes listos"

Info "modelo 3D del X2"
if ((Test-Path "robots\X2_URDF\scene.xml") -and (Test-Path "robots\X2_URDF\meshes\pelvis.stl")) {
  Write-Host "    ya estaba"
} else {
  $tmp = Join-Path $env:TEMP ("x2urdf_" + [guid]::NewGuid().ToString("N"))
  git clone -q --depth 1 --filter=blob:none --sparse https://github.com/AgibotTech/agibot_x2_urdf.git $tmp
  if ($LASTEXITCODE -ne 0) { Aviso "no se pudo bajar el modelo del X2: el simulador 3D no funcionara" }
  else {
    git -C $tmp sparse-checkout set X2_URDF-v1.4.0 | Out-Null
    New-Item -ItemType Directory -Force -Path "robots" | Out-Null
    if (Test-Path "robots\X2_URDF") { Remove-Item -Recurse -Force "robots\X2_URDF" }
    Copy-Item -Recurse (Join-Path $tmp "X2_URDF-v1.4.0") "robots\X2_URDF"
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Write-Host "    listo en robots\X2_URDF"
  }
}

Info "archivo .env"
if (-not (Test-Path ".env")) {
  Copy-Item "andamio\.env.ejemplo" ".env"
  Aviso "se creo .env: pon la ANTHROPIC_API_KEY y el ANDAMIO_TOKEN del equipo (notepad .env)"
} else { Write-Host "    ya estaba" }

Info "pruebas (1-2 minutos)"
& $py -m pytest andamio\tests -q 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Aviso "algunas pruebas fallaron: manda una captura" }

Write-Host ""
Write-Host "Listo. Doble clic en 'Probar en Windows.bat' (en la carpeta del repo) para el menu de pruebas." -ForegroundColor Green
