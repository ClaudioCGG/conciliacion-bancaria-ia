"""
Clasificación de pendientes y sugerencias para la revisión manual.

El motor no fuerza matches dudosos; en su lugar deja cada pendiente con
una explicación de qué es y qué conviene hacer. Así la persona que revisa
arranca con una hipótesis en vez de una planilla en blanco.
"""

from __future__ import annotations

import pandas as pd

from .extractor_nombres import SIN_NOMBRE


def _tipo(fila) -> str:
    if fila["origen"] == "Banco":
        return "Ingreso en banco no contabilizado" if fila["neto"] > 0 else "Egreso en banco no contabilizado"
    return ("Ingreso contable sin registro en banco" if fila["neto"] > 0
            else "Egreso contable sin registro en banco")


def _fmt(x: float) -> str:
    return f"$ {abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def clasificar_pendientes(movs: pd.DataFrame) -> pd.DataFrame:
    pend = movs[~movs["conciliado"]].copy()
    if pend.empty:
        return pend.assign(tipo=[], sugerencia=[])
    pend["tipo"] = pend.apply(_tipo, axis=1)
    pend["sugerencia"] = ""

    # Asientos duplicados en el mayor
    mayor = pend[pend["origen"] == "Contabilidad"]
    dup = mayor[mayor.duplicated(["concepto", "neto"], keep=False)]
    for idx in dup.index:
        n = int((dup["concepto"] == dup.at[idx, "concepto"]).sum())
        pend.at[idx, "sugerencia"] = f"Posible asiento duplicado ({n} asientos iguales). Revisar y anular el sobrante."
        gemelos_banco = pend[(pend["origen"] == "Banco") & ((pend["neto"] - dup.at[idx, "neto"]).abs() < 0.01)
                             & (pend["nombre"] == dup.at[idx, "nombre"])]
        for ib in gemelos_banco.index:
            pend.at[ib, "sugerencia"] = ("Coincide con un asiento que figura duplicado en el mayor: "
                                         "conciliar con uno y anular el otro.")

    # Mismo nombre en ambos lados con importes cercanos -> error de tipeo
    con_nombre = pend[(pend["nombre"] != SIN_NOMBRE) & (pend["sugerencia"] == "")]
    for nombre, g in con_nombre.groupby("nombre"):
        b, c = g[g["origen"] == "Banco"], g[g["origen"] == "Contabilidad"]
        if len(b) == 1 and len(c) == 1:
            mb, mc = b["neto"].iloc[0], c["neto"].iloc[0]
            if mb * mc > 0 and abs(mb - mc) <= 0.10 * abs(mb):
                texto = (f"Posible error de importe con {nombre.title()}: banco {_fmt(mb)} vs "
                         f"contabilidad {_fmt(mc)} (diferencia {_fmt(mb - mc)}).")
                pend.loc[g.index, "sugerencia"] = texto

    for idx, f in pend[pend["sugerencia"] == ""].iterrows():
        concepto = str(f["concepto"]).lower()
        if f["estado"] == "Pendiente - diferencia aislada":
            s = f"Movimiento no incluido en el asiento de '{f['categoria']}'. Registrar el ajuste."
        elif f["origen"] == "Contabilidad" and "cheque" in concepto:
            s = "Posible cheque en tránsito (emitido, aún no debitado). Verificar en el extracto siguiente."
        elif f["origen"] == "Banco" and f["neto"] > 0 and f["nombre"] == SIN_NOMBRE and f["categoria"] == "Sin Categoría":
            s = "Ingreso sin ordenante identificado. Pedir el comprobante al banco o consultar a cobranzas."
        elif f["origen"] == "Banco" and f["nombre"] != SIN_NOMBRE:
            otros = pend[(pend["nombre"] == f["nombre"]) & (pend.index != idx)]
            s = ("Cobro sin asiento propio; hay otros pendientes del mismo cliente: revisar en conjunto."
                 if len(otros) else "Movimiento sin asiento. Registrar o justificar.")
        elif f["origen"] == "Banco":
            s = f"Movimiento de '{f['categoria']}' sin asiento. Registrar o justificar."
        else:
            s = "Asiento sin movimiento bancario. Verificar fecha valor o anular."
        pend.at[idx, "sugerencia"] = s

    return pend


def control_de_matches(movs: pd.DataFrame, tolerancia: float = 0.01) -> pd.DataFrame:
    """Tabla de control: una fila por match, con el Debe y el Haber de cada
    origen. Todo match tiene que cerrar en cero:

        (Banco Debe - Banco Haber) - (Contabilidad Debe - Contabilidad Haber) = 0

    Debe = ingreso a la cuenta bancaria, Haber = egreso. Un match de
    compensación interna (nivel 0) cierra dentro del mismo origen: su Debe
    se cancela con su Haber. Si alguna fila no cierra, hay un error que
    revisar antes de dar la conciliación por buena."""
    conc = movs[movs["conciliado"]]
    if conc.empty:
        return pd.DataFrame()
    piv = conc.pivot_table(index=["cuenta", "match", "nivel"], columns="origen",
                           values=["ingreso", "egreso"], aggfunc="sum", fill_value=0.0)
    tabla = pd.DataFrame(index=piv.index)
    for origen in ("Banco", "Contabilidad"):
        tabla[f"{origen} Debe"] = piv[("ingreso", origen)] if ("ingreso", origen) in piv else 0.0
        tabla[f"{origen} Haber"] = piv[("egreso", origen)] if ("egreso", origen) in piv else 0.0
    tabla["Filas"] = conc.groupby(["cuenta", "match", "nivel"]).size()
    tabla["Diferencia"] = ((tabla["Banco Debe"] - tabla["Banco Haber"])
                           - (tabla["Contabilidad Debe"] - tabla["Contabilidad Haber"])).round(2)
    tabla["Cierra"] = tabla["Diferencia"].abs() <= tolerancia
    return tabla.reset_index().rename(columns={"cuenta": "Banco", "match": "Match", "nivel": "Nivel"})
