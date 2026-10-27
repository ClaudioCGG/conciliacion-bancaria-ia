"""
Uso:
    python conciliar.py                       # demo con los datos de ejemplo (marzo 2026)
    python conciliar.py --periodo 202604 --datos ruta/a/mis/archivos
    python conciliar.py --sin-ia              # fuerza el extractor por reglas

Con la variable de entorno GEMINI_API_KEY configurada, la etapa de nombres usa Gemini.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from conciliacion.pipeline import conciliar_periodo  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Conciliación bancaria automatizada")
    p.add_argument("--datos", default="data/raw", help="carpeta con extractos y mayor")
    p.add_argument("--periodo", default="202603", help="período AAAAMM")
    p.add_argument("--salida", default=None, help="ruta del Excel de salida")
    p.add_argument("--sin-ia", action="store_true", help="no usar Gemini aunque haya API key")
    a = p.parse_args()
    salida = a.salida or f"ejemplos/conciliacion_{a.periodo}.xlsx"
    conciliar_periodo(a.datos, a.periodo, salida, usar_ia=not a.sin_ia)


if __name__ == "__main__":
    main()
