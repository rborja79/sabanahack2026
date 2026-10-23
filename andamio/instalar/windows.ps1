# Instalacion para los portatiles con Windows 10/11: instala WSL2 + Ubuntu 22.04 y Andamio dentro.
# Abre PowerShell COMO ADMINISTRADOR y corre:
#   powershell -ExecutionPolicy Bypass -File .\andamio\instalar\windows.ps1
# Si pide reiniciar, reinicia y vuelve a correr el mismo comando.
$ErrorActionPreference = "Stop"
$distro = "Ubuntu-22.04"
$repo   = "https://github.com/rborja79/sabanahack2026.git"

function Info  ($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Aviso ($t) { Write-Host "    $t" -ForegroundColor Yellow }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "abre PowerShell como administrador (clic derecho > Ejecutar como administrador)" }

Info "version de Windows"
$build = [int](Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").CurrentBuildNumber
Write-Host "    build $build"
if ($build -lt 19041) { throw "se necesita Windows 10 2004 (build 19041) o superior para WSL2" }
$espejo = $build -ge 22621     # Windows 11 22H2 o mas nuevo: red en modo espejo
if (-not $espejo) { Aviso "Tu Windows no soporta la red en modo espejo. WSL2 usara NAT: el robot por cable puede NO verse desde Ubuntu. Plan B: usa el contenedor del robot (andamio\instalar\contenedor_x2.md) o un Ubuntu en SSD." }

Info "WSL2"
$lista = (wsl.exe --list --quiet 2>$null) -join "`n"
$lista = $lista -replace "`0", ""
if ($lista -notmatch [regex]::Escape($distro)) {
  wsl.exe --install -d $distro --no-launch
  if ($LASTEXITCODE -ne 0) { throw "wsl --install fallo. Reinicia y vuelve a correr el script." }
  Aviso "Se instalo $distro. Si Windows pide reiniciar, hazlo y corre este script otra vez."
  wsl.exe -d $distro -u root -- echo listo 2>$null | Out-Null
} else { Write-Host "    $distro ya estaba" }

if ($espejo) {
  Info "red en modo espejo (para ver el robot por cable)"
  $cfg = Join-Path $env:USERPROFILE ".wslconfig"
  if ((Test-Path $cfg) -and (Select-String -Path $cfg -Pattern "networkingMode" -Quiet)) {
    Aviso ".wslconfig ya define networkingMode; revisalo a mano si el robot no responde"
  } else {
    if (Test-Path $cfg) { Copy-Item $cfg "$cfg.bak" -Force }
    Add-Content -Path $cfg -Value "`n[wsl2]`nnetworkingMode=mirrored`n"
    wsl.exe --shutdown
    Write-Host "    .wslconfig actualizado y WSL reiniciado"
  }
}

Info "Andamio dentro de Ubuntu (puede tardar 10 a 20 minutos)"
$bash = @"
set -e
cd ~
[ -d sabanahack2026 ] || git clone $repo
cd sabanahack2026 && git pull --ff-only || true
chmod +x andamio/instalar/ubuntu.sh
./andamio/instalar/ubuntu.sh --ros
"@
$bash = $bash -replace "`r", ""
# se pasa como archivo: los saltos de linea y comillas por la linea de comandos de wsl.exe se danan
$tmp = Join-Path $env:TEMP "andamio_wsl.sh"
[IO.File]::WriteAllText($tmp, $bash, (New-Object Text.UTF8Encoding($false)))
$wslTmp = (wsl.exe -d $distro -- wslpath -a ($tmp -replace '\\', '/')).Trim()
wsl.exe -d $distro -- bash $wslTmp
if ($LASTEXITCODE -ne 0) { throw "la instalacion dentro de Ubuntu fallo (revisa los mensajes de arriba)" }

Write-Host @"

Listo. Para trabajar abre 'Ubuntu-22.04' desde el menu Inicio y:
  cd ~/sabanahack2026 && source .venv/bin/activate
  python -m andamio.doctor --robot x2

El SDK AimDK (carpeta aimdk o el .tar.gz que baja de x2-aimdk.agibot.com) no esta en Git. Copialo asi y compilalo:
  cp /mnt/c/Users/TU_USUARIO/Downloads/aimdk*.tar.gz ~/ && tar xf ~/aimdk*.tar.gz -C ~/
  ./andamio/instalar/ubuntu.sh --sdk ~/aimdk
"@ -ForegroundColor Green
