"""Carga episodios grabados para entrenar o para mirarlos.

    python cargar.py                 # lista lo que hay
    python cargar.py --episodio ...  # resumen de uno
"""
import argparse, json, pathlib

RAIZ = pathlib.Path(__file__).resolve().parent


def episodios(raiz=RAIZ):
    salida = []
    for c in sorted(raiz.iterdir()):
        m = c / "manifiesto.json"
        if c.is_dir() and m.exists():
            salida.append(json.loads(m.read_text()))
    return salida


def tramas(episodio, raiz=RAIZ):
    """Lee un episodio linea por linea."""
    with open(pathlib.Path(raiz) / episodio / "tramas.jsonl", encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                yield json.loads(linea)


def tabla(episodio, raiz=RAIZ):
    """Deja el episodio como DataFrame: una fila por trama, qpos en columnas."""
    import pandas as pd
    filas = []
    for t in tramas(episodio, raiz):
        fila = {"t": t.get("t"), "i": t.get("i")}
        for j, v in enumerate(t["obs"]["qpos"]):
            fila[f"q{j}"] = v
        for lado in ("left", "right"):
            a = t["accion"].get(lado)
            if a:
                fila[f"{lado}_x"], fila[f"{lado}_y"], fila[f"{lado}_z"] = a
        filas.append(fila)
    return pd.DataFrame(filas)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodio", default="")
    a = ap.parse_args()
    if not a.episodio:
        for m in episodios():
            print(f"{m['episodio']}  {m.get('tarea',''):<18} {m.get('robot',''):<12} "
                  f"{m.get('tramas', 0)} tramas")
    else:
        df = tabla(a.episodio)
        print(df.shape)
        print(df.head())
