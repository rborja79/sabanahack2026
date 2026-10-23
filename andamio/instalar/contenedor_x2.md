# Andamio dentro del contenedor del X2

El manual del X2 recomienda desarrollar **dentro de un contenedor en la unidad de desarrollo** (Orin NX, `10.0.1.41`),
no en el PC de movimiento (`10.0.1.40`). Así el código está en la misma red que el robot y no depende del portátil.

1. Conecta el cable Gigabit y pon tu IP en `10.0.1.2/24`. Comprueba `ping 10.0.1.41`.
2. Usuario y clave de la unidad: los dan los organizadores.
3. Copia Andamio: `./andamio/instalar/copiar_al_robot.sh USUARIO` (usa `tar` por `ssh`, sin Git en el robot).
4. Entra al contenedor (el procedimiento exacto está en el manual AimDK, "modo contenedor") y asegúrate de que:
   - el puerto **8790** del contenedor está publicado (o el contenedor usa la red del host);
   - el SDK está compilado: `source /opt/ros/humble/setup.bash && source ~/aimdk/install/local_setup.bash`;
   - `export RMW_IMPLEMENTATION=rmw_fastrtps_cpp`.
5. En el robot:
   ```
   cd ~/andamio_robot
   export ANDAMIO_TOKEN='...mismo que en tu .env...'
   python3 -m andamio.servidor_robot --robot x2
   ```
   El servidor solo usa la librería estándar de Python (más `rclpy` del SDK): no hay que instalar nada con pip.
6. En tu portátil (Mac o Windows): `python -m andamio.doctor --robot remoto` y luego
   `python -m andamio saludar --robot remoto --panel`.

Seguridad del servidor: exige el token, acepta **un** cliente, repite la velocidad a 50 Hz y la **caduca a los 0.3 s** si el
cliente se calla, y frena el robot si se cae la conexión. Aun así: botón de emergencia físico a la mano.

No lances varios nodos ROS seguidos con el robot de pie (congestiona DDS y puede tumbarlo): el servidor usa **un solo nodo**.
