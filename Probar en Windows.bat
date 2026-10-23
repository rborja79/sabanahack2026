@echo off
rem Doble clic: menu de pruebas del andamio en Windows (sin WSL).
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo Instalando por primera vez, tarda unos minutos...
  powershell -ExecutionPolicy Bypass -File ".\andamio\instalar\windows_nativo.ps1"
)
set PY=.venv\Scripts\python.exe
echo.
echo === Andamio - probar en Windows ===
echo Se abre el panel en el navegador (PARAR, Confirmar, alertas) y en 1-3 una ventana 3D.
echo   1) Simulador 3D del X2: busca a una persona (verde) y camina hacia ella
echo   2) Simulador 3D + voz: en el panel escribe camina, gira a la izquierda, saluda, para
echo   3) Simulador 3D + brazos y manos
echo   4) Autonomia con TU CAMARA (alejate 2-3 m y camina hacia el portatil)
echo   5) Pantalla, sonido y luces del X2 (solo anuncia lo que haria)
echo   6) Solo el panel con la camara
echo   7) Modo remoto: este equipo hace de robot (servidor) para que otro lo maneje
choice /c 1234567 /t 20 /d 1 /m "Elige (si no eliges en 20 s arranca la 1)"
set OP=%errorlevel%
if %OP%==1 %PY% -m andamio buscar_persona --robot sim --ojo simulado --ver3d --panel --confirmo
if %OP%==2 %PY% -m andamio voz --robot sim --ver3d --panel --oido panel --confirmo
if %OP%==3 %PY% -m andamio manos --robot sim --ver3d --panel --confirmo
if %OP%==4 %PY% -m andamio buscar_persona --robot falso --ojo camara --panel
if %OP%==5 %PY% -m andamio medios --robot falso --panel
if %OP%==6 %PY% -m andamio --robot falso --ojo camara --panel
if %OP%==7 %PY% -m andamio.servidor_robot --robot sim
echo.
pause
