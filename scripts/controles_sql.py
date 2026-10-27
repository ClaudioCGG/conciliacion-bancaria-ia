"""Ejecuta los controles de sql/controles.sql con DuckDB sobre el resultado de la conciliación."""

import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from conciliacion.pipeline import conciliar_periodo  # noqa: E402


def cargar_consultas(ruta: Path) -> dict[str, str]:
    texto = ruta.read_text(encoding="utf-8")
    bloques = re.split(r"^-- name: (\w+)\s*$", texto, flags=re.M)[1:]
    return {nombre: sql.strip() for nombre, sql in zip(bloques[::2], bloques[1::2])}


def main():
    resultados, _, _ = conciliar_periodo(RAIZ / "data" / "raw", "202603", usar_ia=False, verbose=False)
    movimientos = pd.concat([r.movimientos for r in resultados], ignore_index=True)  # noqa: F841 (lo usa DuckDB)
    con = duckdb.connect()
    con.register("movimientos", movimientos)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 60)
    for nombre, sql in cargar_consultas(RAIZ / "sql" / "controles.sql").items():
        print(f"\n=== {nombre} ===")
        print(con.execute(sql).df().to_string(index=False))


if __name__ == "__main__":
    main()
