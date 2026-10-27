"""
Evaluación del motor contra datos con respuesta conocida.

- Tasa automática: % de movimientos que el motor concilió solo.
- Precisión: de lo que concilió, cuánto estaba bien. Es la métrica crítica:
  un falso positivo esconde un error contable. Objetivo: 100%.
- Cobertura: de lo que debía conciliar, cuánto encontró.
- Detección de excepciones: de lo que NO debía conciliar, cuánto dejó a la vista.
"""

from __future__ import annotations

import pandas as pd


def evaluar(movimientos: pd.DataFrame, verdad: pd.DataFrame) -> dict[str, float]:
    df = movimientos.join(verdad.set_index("ref")[["debe_conciliar"]], on="ref")
    df["debe_conciliar"] = df["debe_conciliar"].fillna(False).astype(bool)

    conciliados = df["conciliado"]
    deben = df["debe_conciliar"]
    vp = int((conciliados & deben).sum())
    fp = int((conciliados & ~deben).sum())

    return {
        "movimientos": len(df),
        "conciliados": int(conciliados.sum()),
        "tasa_automatica": conciliados.mean(),
        "precision": vp / (vp + fp) if (vp + fp) else 1.0,
        "cobertura": vp / int(deben.sum()) if deben.any() else 1.0,
        "falsos_positivos": fp,
        "excepciones": int((~deben).sum()),
        "excepciones_detectadas": int((~deben & ~conciliados).sum()),
    }
