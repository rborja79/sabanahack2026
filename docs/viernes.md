# Plan del dia

## Las dos horas antes

Cada uno en su maquina, antes de que empiece:

1. la instalacion corrida y con `robot ok` y `vision ok` en pantalla
2. `python bridge/cliente_prueba.py` terminando en `prueba OK`
3. el visor abriendo, conectando y moviendo el robot con el raton
4. la pagina con `?emular` entrando a VR
5. quien lleve el Quest: `adb reverse` probado y entrando a VR de verdad

Si alguien no logra el paso 1, que no se quede peleando: que trabaje sobre la
maquina de otro y que se reparta distinto el trabajo.

Si alguien no sabe que hace una pieza, esta en `docs/manual.md`.

## Reparto que funciona

| Rol | Que hace |
|---|---|
| Puente | `bridge/`: IK, restricciones, el robot que toque |
| Visor | `web/src/`: lo que se ve, la interaccion, la demo |
| Datos | `datos/`: formato, metricas, el modelo que se entrene |
| Historia | el problema, la sustentacion, las laminas |

El rol de Historia no es relleno. En la hackathon anterior el jurado premia lo
que entiende, y el que arma el relato tiene que estar viendo la demo desde
temprano, no escribiendo al final.

## Que ya esta resuelto y no hay que volver a hacer

- mover un robot con las manos, en VR, AR, camara, raton o terminal
- probar VR sin visor, con el emulador que trae la pagina
- guardar episodios en un formato que se carga con pandas en una linea
- tres robots listos, cambiar de uno a otro es un argumento
- detectar objetos con YOLO11n sobre OpenCV, sin descargas ni torch

## Donde esta el valor que si hay que construir

Lo de arriba es el andamio. Lo que diferencia es lo que se monte encima:

- **aprender de las demostraciones**: con 20 o 30 episodios de una tarea sencilla
  ya se puede entrenar una politica de clonacion de comportamiento y mostrar al
  robot repitiendo solo lo que le ensenaste
- **medir la calidad del dato**: cuantos episodios, que tan parecidos entre si,
  cuales sirven y cuales no. Es un problema de datos, que es lo nuestro
- **cerrar el lazo con vision**: que el objetivo salga de lo que ve la camara y
  no de donde esta tu mano
- **el caso de uso**: un robot que ayuda en una tarea concreta y verificable vale
  mas que uno que hace gestos bonitos

## Para la sustentacion

Lo que se ve bien, en orden:

1. alguien con el visor puesto moviendo el robot en la pantalla grande
2. el contador de episodios subiendo mientras se graba
3. el robot repitiendo la tarea solo, con lo aprendido
4. una grafica de que tanto mejora con mas episodios

Tener grabado un video de respaldo de los puntos 1 y 3. El wifi del auditorio
siempre falla.

## Reglas para no perder tiempo

- nadie toca `bridge/sim.py` y `web/src/main.js` al tiempo sin avisar
- commits pequenos y seguido, rama por persona
- si algo lleva mas de 30 minutos sin avanzar, se cambia de camino
- la demo se congela una hora antes de presentar
