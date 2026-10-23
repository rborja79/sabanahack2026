"""Linea de comandos:  python -m andamio PLANTILLA [--robot falso|sim|x2|d1|remoto] [opciones]"""
import argparse
import json
import sys

from .aplicacion import Aplicacion, cargar_env, listar_plantillas, resolver_plantilla
from .fabrica import ROBOTS
from .nucleo.errores import ErrorAndamio


def _params(lista):
    out = {}
    for item in lista or []:
        k, sep, v = item.partition("=")
        if not sep:
            raise ErrorAndamio(f"parametro invalido: {item}", pista="usa --param nombre=valor")
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def principal(argv=None):
    ap = argparse.ArgumentParser(prog="python -m andamio", description="Ejecuta una plantilla de mision sobre un robot")
    ap.add_argument("plantilla", nargs="?", help="archivo .yaml o nombre dentro de andamio/plantillas")
    ap.add_argument("--robot", default="falso", choices=ROBOTS)
    ap.add_argument("--seco", action="store_true", help="solo muestra lo que haria, no envia nada")
    ap.add_argument("--validar", action="store_true", help="solo revisa la plantilla")
    ap.add_argument("--listar", action="store_true", help="lista las plantillas")
    ap.add_argument("--panel", action="store_true", help="abre el panel web (127.0.0.1)")
    ap.add_argument("--oido", choices=["texto", "panel", "whisper"])
    ap.add_argument("--confirmo", action="store_true", help="confirma solo (NO usar con el robot real)")
    ap.add_argument("--param", action="append", help="sobrescribe un parametro: --param velocidad=0.3")
    ap.add_argument("--modelo", default="", help="MJCF para sim, IK y limites")
    ap.add_argument("--config")
    ap.add_argument("--log", help="archivo JSONL de alertas")
    ap.add_argument("--ver3d", action="store_true",
                    help="ventana 3D del robot simulado (con --robot sim; en el Mac usa .venv/bin/mjpython)")
    ap.add_argument("--ojo", choices=["ninguno", "camara", "simulado", "x2", "remoto"],
                    help="vision: camara (webcam), simulado, x2 (camara del robot) o remoto")
    args = ap.parse_args(argv)
    cargar_env()

    if args.listar:
        print("\n".join(listar_plantillas()))
        return 0
    if not args.plantilla and not args.panel:
        ap.print_help()
        return 1
    if args.confirmo and args.robot in ("x2", "d1", "remoto"):
        print("--confirmo se salta las confirmaciones humanas y no se permite con el robot real", file=sys.stderr)
        return 2

    app = None
    try:
        app = Aplicacion(args.robot, args.config, args.modelo, args.seco, args.confirmo,
                         "panel" if args.panel and not args.oido else args.oido, args.log, ojo=args.ojo)
        if args.validar:
            problemas = app.validar(args.plantilla)
            for p in problemas:
                print("-", p)
            print("plantilla correcta" if not problemas else f"{len(problemas)} problema(s)")
            return 0 if not problemas else 1
        visor = False
        if args.ver3d:
            if not hasattr(app.robot, "abrir_visor_3d"):
                raise ErrorAndamio("--ver3d solo funciona con --robot sim",
                                   pista="usa: .venv/bin/mjpython -m andamio PLANTILLA --robot sim --ver3d")
            if app.ojo is not None and hasattr(app.ojo, "objetivos"):
                app.robot.marcadores = app.ojo.objetivos
            app.robot.abrir_visor_3d()
            visor = True
        panel = None
        if args.panel:
            from .panel import Panel
            panel = Panel(app)
            panel.iniciar()
            if app.ojo is not None:
                app.iniciar()        # para ver la camara en el panel desde ya
        if args.plantilla:
            resultado = app.ejecutar(args.plantilla, _params(args.param))
            if panel is None and not visor:
                return 0 if resultado["ok"] else 1
        try:
            import time
            while panel is not None or (visor and app.robot.visor_abierto()):
                if visor and panel is None and not app.robot.visor_abierto():
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        return 0
    except ErrorAndamio as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if e.pista:
            print(f"  pista: {e.pista}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        if app is not None:
            app.cerrar()


if __name__ == "__main__":
    sys.exit(principal())
