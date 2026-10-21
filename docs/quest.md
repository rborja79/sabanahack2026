# Entrar en VR o AR desde el Quest

El navegador del Quest solo deja usar WebXR en **HTTPS** o en **localhost**. La
forma que menos problemas da es `adb reverse`, porque convierte tu portatil en el
localhost del visor: no hay certificados, no hay wifi de por medio y no hay
tunel que se caiga a mitad de la demo.

## Camino recomendado: adb reverse

1. En el Quest: Configuracion, Sistema, Modo desarrollador, encendido. Necesitas
   una cuenta de desarrollador de Meta, es gratis y se saca en 5 minutos.
2. Conecta el Quest al portatil por USB y acepta el aviso de depuracion que
   aparece dentro del visor.
3. En el portatil:

```bash
adb devices                      # debe aparecer el Quest
adb reverse tcp:5173 tcp:5173    # el visor
adb reverse tcp:8765 tcp:8765    # el puente
```

4. Arranca el puente y el visor como siempre.
5. En el navegador del Quest abre `http://localhost:5173`.
6. En el campo **servidor** deja `ws://localhost:8765` y pulsa Conectar.
7. Pulsa **ENTER VR**. Si el Quest tiene seguimiento de manos encendido, el robot
   sigue tus manos; si no, sigue los mandos.

Si no tienes `adb`: en macOS `brew install android-platform-tools`, en Ubuntu
`sudo apt-get install adb`.

## Camino alterno: HTTPS en la red local

```bash
cd web && npm run dev:https
```

Levanta con certificado propio. El Quest va a reclamar que el certificado no es
de confianza; hay que aceptar la advertencia a mano. Funciona, pero en una demo
en vivo es un paso mas que puede salir mal.

El servidor tambien tiene que ir cifrado si la pagina va por HTTPS. Lo mas facil
es un tunel:

```bash
cloudflared tunnel --url http://localhost:5173
cloudflared tunnel --url http://localhost:8765   # usa la URL resultante con wss://
```

## Seguimiento de manos

Se enciende en Configuracion, Movimiento, Seguimiento de manos. El visor lo pide
como opcional, asi que si esta apagado entra igual pero usando los mandos.

Lo que lee de cada mano:

- la muneca da la posicion
- la distancia entre el pulgar y el indice da la pinza, de 0 cerrada a 1 abierta

## AR con passthrough

El boton **START AR** aparece solo si el visor lo soporta. En AR se apaga el piso
y la rejilla, y el robot se coloca unos 90 cm al frente para verlo entero encima
de la mesa real. Es el modo que mejor se ve en una sustentacion.

## Calibrar

Ponte en una posicion comoda, con las manos donde las tendrias para trabajar, y
pulsa **Calibrar**. Desde ahi tus manos y las del robot se mueven juntas. Si el
robot queda estirado o no alcanza, vuelve a calibrar: casi siempre es eso.

Para ajustar cuanto se mueve el robot por cada centimetro tuyo:

```bash
python server.py --escala 0.7    # el robot se mueve menos que tu
```

## Antes de la demo

- `adb reverse` puesto y probado
- el Quest cargado y con el brillo alto
- la tarea escrita en el campo `tarea` antes de grabar
- un episodio grabado de prueba, para que nadie dude de que graba
