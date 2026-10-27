"""
Normalización de extractos bancarios y del libro mayor.

Cada banco exporta distinto (y peor aún cuando el extracto viene de un PDF
convertido a Excel). Este módulo lleva todos los formatos a un esquema
único:

    fecha | concepto | ref | ingreso | egreso | saldo | origen | cuenta

y verifica fila por fila que el saldo cierre:

    saldo_anterior + ingreso - egreso == saldo
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

COLUMNAS = ["fecha", "concepto", "ref", "ingreso", "egreso", "saldo", "origen", "cuenta"]


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def monto_ar_a_float(valor) -> float | None:
    """'1.234.567,89' -> 1234567.89 ; '-2.084,47' -> -2084.47 ; '' -> None."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip().replace(" ", "")
    if not s:
        return None
    negativo = s.startswith("-") or s.endswith("-")
    s = s.strip("-").replace(".", "").replace(",", ".")
    try:
        numero = float(s)
    except ValueError:
        return None
    return -numero if negativo else numero


def detectar_periodo(nombre_archivo: str) -> tuple[int, int]:
    """Busca un patrón AAAAMM en el nombre del archivo: 'banco_alfa_202603.xlsx' -> (2026, 3)."""
    m = re.search(r"(20\d{2})(0[1-9]|1[0-2])", nombre_archivo)
    if not m:
        raise ValueError(f"No encuentro el período AAAAMM en '{nombre_archivo}'")
    return int(m.group(1)), int(m.group(2))


def control_de_saldos(df: pd.DataFrame, saldo_inicial: float, tolerancia: float = 0.01) -> pd.DataFrame:
    """Devuelve las filas donde el saldo informado no coincide con el calculado.
    Un DataFrame vacío significa que el extracto se leyó completo y sin errores."""
    esperado = saldo_inicial + (df["ingreso"] - df["egreso"]).cumsum()
    diferencias = (esperado - df["saldo"]).abs()
    return df.loc[diferencias > tolerancia]


# ----------------------------------------------------------------------
# Banco Alfa: PDF convertido a Excel, montos como texto, encabezados
# repetidos en cada página y filas de ruido.
# ----------------------------------------------------------------------
_FECHA_CORTA = re.compile(r"^\d{2}/\d{2}$")
_SALDO_ANTERIOR = re.compile(r"^SALDO ANTERIOR\s+([\d\.]+,\d{2})")


def normalizar_banco_alfa(ruta: str | Path) -> tuple[pd.DataFrame, float]:
    ruta = Path(ruta)
    anio, _ = detectar_periodo(ruta.name)
    crudo = pd.read_excel(ruta, header=None, dtype=str)

    saldo_inicial = None
    filas = []
    for _, r in crudo.iterrows():
        primera = str(r[0]).strip() if pd.notna(r[0]) else ""
        m = _SALDO_ANTERIOR.match(primera)
        if m:
            saldo_inicial = monto_ar_a_float(m.group(1))
            continue
        if not _FECHA_CORTA.match(primera):
            continue  # encabezados, "SALDO AL", totales, textos legales
        dia, mes = map(int, primera.split("/"))
        debito = monto_ar_a_float(r[3]) or 0.0
        credito = monto_ar_a_float(r[4]) or 0.0
        filas.append({
            "fecha": pd.Timestamp(anio, mes, dia),
            "concepto": re.sub(r"\s+", " ", str(r[1])).strip(),
            "ref": str(r[2]).strip(),
            "ingreso": credito,
            "egreso": abs(debito),
            "saldo": monto_ar_a_float(r[5]),
        })

    if saldo_inicial is None:
        raise ValueError("No se encontró la línea 'SALDO ANTERIOR' en el extracto de Banco Alfa")
    df = pd.DataFrame(filas)
    df["origen"], df["cuenta"] = "Banco", "Banco Alfa"
    return df[COLUMNAS], saldo_inicial


# ----------------------------------------------------------------------
# Banco Beta: una columna de importe con signo, fecha dd/mm/aa y
# descripciones largas partidas en dos filas.
# ----------------------------------------------------------------------
def normalizar_banco_beta(ruta: str | Path) -> tuple[pd.DataFrame, float]:
    crudo = pd.read_excel(ruta, header=0, dtype=str)
    crudo.columns = ["fecha", "concepto", "ref", "importe", "saldo"]

    filas: list[dict] = []
    for _, r in crudo.iterrows():
        if pd.isna(r["fecha"]):
            # Continuación de la descripción de la fila anterior
            if filas and pd.notna(r["concepto"]):
                filas[-1]["concepto"] += " " + str(r["concepto"]).strip()
            continue
        importe = monto_ar_a_float(r["importe"])
        filas.append({
            "fecha": pd.to_datetime(r["fecha"], format="%d/%m/%y"),
            "concepto": str(r["concepto"]).strip(),
            "ref": str(r["ref"]).strip(),
            "ingreso": importe if importe > 0 else 0.0,
            "egreso": -importe if importe < 0 else 0.0,
            "saldo": monto_ar_a_float(r["saldo"]),
        })
    df = pd.DataFrame(filas)
    # El extracto no informa saldo inicial: se deduce de la primera fila.
    saldo_inicial = round(df.loc[0, "saldo"] - df.loc[0, "ingreso"] + df.loc[0, "egreso"], 2)
    df["origen"], df["cuenta"] = "Banco", "Banco Beta"
    return df[COLUMNAS], saldo_inicial


# ----------------------------------------------------------------------
# Libro mayor contable
# ----------------------------------------------------------------------
def leer_mayor(ruta: str | Path, cuenta_contable: str, nombre_cuenta: str) -> pd.DataFrame:
    """Lee el mayor exportado del sistema y se queda con una cuenta bancaria.
    Debe = ingreso al banco, Haber = egreso."""
    crudo = pd.read_excel(ruta)
    crudo = crudo[crudo["Cuenta"] == cuenta_contable]
    df = pd.DataFrame({
        "fecha": pd.to_datetime(crudo["Fch Mov"]),
        "concepto": crudo["Detalle"].astype(str).str.strip(),
        "ref": "A" + crudo["Nro Asiento"].astype(str),
        "ingreso": crudo["Debe"].fillna(0.0).astype(float),
        "egreso": crudo["Haber"].fillna(0.0).astype(float),
        "saldo": float("nan"),
        "origen": "Contabilidad",
        "cuenta": nombre_cuenta,
        "usuario": crudo["Usuario"],
        "fecha_registro": pd.to_datetime(crudo["Fecha Registro"]),
    })
    return df.reset_index(drop=True)


NORMALIZADORES = {
    "Banco Alfa": normalizar_banco_alfa,
    "Banco Beta": normalizar_banco_beta,
}
