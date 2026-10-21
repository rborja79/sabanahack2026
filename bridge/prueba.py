"""Prueba que el robot y la cinematica inversa funcionen. La corre setup."""
import pathlib, sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from sim import Robot


def revisar_vision():
    """Confirma que el detector que viene en el repo carga y corre."""
    import numpy as np
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "vision"))
    try:
        import objetos
        objetos.por_onnx(np.zeros((360, 640, 3), dtype="uint8"))
        print("    vision ok · detector yolo11n cargado desde el repo")
    except Exception as e:
        print(f"    vision con problema: {type(e).__name__}: {e}")


def main(modelo="unitree_g1"):
    r = Robot(modelo)
    lado = "right" if "right" in r.efectores else next(iter(r.efectores), None)
    if lado is None:
        print(f"    robot ok · {modelo} · bodies {len(r.nombres_body)} · sin efector definido")
        return 0
    r.fijar_objetivo(lado, r.pos_efector(lado) + np.array([0.0, 0.0, 0.12]))
    for _ in range(400):
        r.paso()
    err = float(np.linalg.norm(r.pos_efector(lado) - r.objetivos[lado]))
    p, q = r.estado()
    print(f"    robot ok · bodies {len(r.nombres_body)} · error IK {err * 1000:.2f} mm"
          f" · estado {len(p)}+{len(q)} valores")
    revisar_vision()
    return 0 if err < 0.01 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "unitree_g1"))
