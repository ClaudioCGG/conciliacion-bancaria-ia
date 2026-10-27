"""
Motor de conciliación en cascada: de lo más seguro a lo más arriesgado.

    Nivel 0  Compensación interna      Un contra-asiento o un reverso bancario se compensa con su
                                       original dentro del mismo origen (errores corregidos en el mes).
    Nivel 1  Por cuenta contable       Si el total de una cuenta cierra entre banco y mayor
                                       (ingresos y egresos SIEMPRE por separado), se concilia entera.
    Nivel 2  Uno a uno por importe     Un movimiento contra un asiento con el mismo importe,
                                       solo si el match es único (sin ambigüedad).
    Nivel 3  Agrupado por fecha        Varias filas de un lado contra una o pocas del otro
                                       (ej.: sueldos pagados en varias transferencias).
    Nivel 4  Por nombre (IA)           Para lo que quedó sin cuenta: extrae el nombre de la
                                       contraparte y concilia por totales de cada nombre.
    Nivel 5  Aislamiento de diferencia Si en una cuenta abierta la diferencia es exactamente
                                       1 o 2 movimientos, concilia el resto y deja esos a la vista.

Lo que ningún nivel resuelve queda Pendiente, con una sugerencia para la
revisión humana. El motor nunca fuerza un match dudoso: preferimos un
pendiente de más a un error escondido.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from . import config as cfg
from .categorias import categorizar
from .extractor_nombres import SIN_NOMBRE, ExtractorReglas, canonicalizar, normalizar_texto

EPS = 1e-6


@dataclass
class ResultadoConciliacion:
    cuenta: str
    movimientos: pd.DataFrame
    conciliados_por_nivel: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.movimientos)

    @property
    def conciliados(self) -> int:
        return int(self.movimientos["conciliado"].sum())

    @property
    def tasa(self) -> float:
        return self.conciliados / self.total if self.total else 0.0

    @property
    def pendientes(self) -> pd.DataFrame:
        return self.movimientos[~self.movimientos["conciliado"]]


class MotorConciliacion:
    def __init__(self, extractor=None, tolerancia: float = cfg.TOLERANCIA_MONTO):
        self.extractor = extractor or ExtractorReglas()
        self.tol = tolerancia + EPS
        self._match = 0

    # ------------------------------------------------------------------
    # Preparación
    # ------------------------------------------------------------------
    def _preparar(self, banco: pd.DataFrame, mayor: pd.DataFrame) -> pd.DataFrame:
        df = pd.concat([banco, mayor], ignore_index=True)
        for col in ("usuario", "fecha_registro"):
            if col not in df:
                df[col] = None
        df["categoria"] = df["concepto"].map(categorizar)
        df["neto"] = df["ingreso"] - df["egreso"]
        df["nombre"] = SIN_NOMBRE
        df["conciliado"] = False
        df["nivel"] = ""
        df["estado"] = "Pendiente"
        df["match"] = np.nan
        df["dias_diferencia"] = np.nan
        return df

    def _nuevo_match(self) -> int:
        self._match += 1
        return self._match

    def _marcar(self, df, idx, nivel, dias=np.nan):
        m = self._nuevo_match()
        tardio = pd.notna(dias) and dias > cfg.DIAS_REGISTRO_TARDIO
        df.loc[idx, ["conciliado", "nivel", "match", "dias_diferencia"]] = [True, nivel, m, dias]
        df.loc[idx, "estado"] = "Conciliado - registro tardío" if tardio else "Conciliado"

    # ------------------------------------------------------------------
    # Nivel 0: compensaciones internas (contra-asientos y reversos)
    # ------------------------------------------------------------------
    def nivel_0_compensaciones(self, df) -> int:
        """Dentro de un mismo origen, un movimiento marcado como anulación o
        reverso se compensa con su original (mismo importe, signo opuesto,
        mismo concepto). Ej.: un pago cargado dos veces y anulado con un
        contra-asiento en el mes, o un débito directo rechazado por el banco.
        Si la corrección no se hizo en el período, no hay par y la diferencia
        queda a la vista."""
        n = 0
        anulaciones = df[~df["conciliado"] & df["concepto"].str.contains(cfg.PATRON_ANULACION, case=False, regex=True)]
        for ia, fa in anulaciones.iterrows():
            if df.at[ia, "conciliado"]:
                continue
            texto_base = normalizar_texto(re.sub(cfg.PATRON_ANULACION, " ", fa["concepto"], flags=re.I))
            cand = df[~df["conciliado"] & (df["origen"] == fa["origen"]) & (df.index != ia)
                      & ((df["neto"] + fa["neto"]).abs() <= self.tol)]
            cand = cand[cand["concepto"].map(
                lambda c: fuzz.token_set_ratio(normalizar_texto(c), texto_base) >= cfg.SIMILITUD_ANULACION)]
            if cand.empty:
                continue
            # Si hay varios originales idénticos (el duplicado), se toma el más cercano en fecha.
            io = (cand["fecha"] - fa["fecha"]).abs().idxmin()
            self._marcar(df, [io, ia], "0 · Compensación interna")
            n += 1
        return n

    # ------------------------------------------------------------------
    # Nivel 1: por cuenta contable
    # ------------------------------------------------------------------
    def _cuentas_que_cierran(self, df, solo_pendientes=True) -> tuple[list[str], list[str]]:
        base = df[~df["conciliado"]] if solo_pendientes else df
        base = base[base["categoria"] != cfg.SIN_CATEGORIA]
        cierran, abiertas = [], []
        for cat, g in base.groupby("categoria"):
            b, c = g[g["origen"] == "Banco"], g[g["origen"] == "Contabilidad"]
            ok_ing = abs(b["ingreso"].sum() - c["ingreso"].sum()) <= self.tol
            ok_egr = abs(b["egreso"].sum() - c["egreso"].sum()) <= self.tol
            (cierran if ok_ing and ok_egr else abiertas).append(cat)
        return cierran, abiertas

    def nivel_1_cuentas(self, df, etiqueta="1 · Cuenta contable") -> list[str]:
        cierran, abiertas = self._cuentas_que_cierran(df)
        for cat in cierran:
            idx = df.index[(df["categoria"] == cat) & ~df["conciliado"]]
            self._marcar(df, idx, etiqueta)
        return abiertas

    # ------------------------------------------------------------------
    # Nivel 2: uno a uno por importe, solo si el match es único
    # ------------------------------------------------------------------
    def nivel_2_uno_a_uno(self, df, cuentas, columna, ventana_dias=None) -> int:
        n = 0
        for cat in cuentas:
            pend = df[~df["conciliado"] & (df["categoria"] == cat) & (df[columna] > 0)]
            banco, mayor = pend[pend["origen"] == "Banco"], pend[pend["origen"] == "Contabilidad"]
            usados_m: set[int] = set()
            for ib, fb in banco.iterrows():
                cand_m = mayor[~mayor.index.isin(usados_m) & ((mayor[columna] - fb[columna]).abs() <= self.tol)]
                mismos_b = banco[(banco[columna] - fb[columna]).abs() <= self.tol]
                if ventana_dias is not None:
                    v = pd.Timedelta(days=ventana_dias)
                    cand_m = cand_m[(cand_m["fecha"] - fb["fecha"]).abs() <= v]
                    mismos_b = mismos_b[(mismos_b["fecha"] - fb["fecha"]).abs() <= v]
                if len(cand_m) == 1 and len(mismos_b) == 1:
                    im = cand_m.index[0]
                    dias = abs((fb["fecha"] - df.at[im, "fecha"]).days)
                    self._marcar(df, [ib, im], "2 · Uno a uno", dias)
                    usados_m.add(im)
                    n += 1
        return n

    # ------------------------------------------------------------------
    # Nivel 3: agrupamiento por fecha
    # ------------------------------------------------------------------
    def _subconjunto_que_suma(self, filas: pd.DataFrame, objetivo: float, columna: str, max_filas: int):
        idx = filas.index.tolist()
        for k in range(2, min(max_filas, len(idx)) + 1):
            for combo in combinations(idx, k):
                if abs(filas.loc[list(combo), columna].sum() - objetivo) <= self.tol:
                    return list(combo)
        return None

    def nivel_3_agrupado(self, df, cuentas, columna) -> int:
        n = 0
        ventana = pd.Timedelta(days=cfg.VENTANA_DIAS_AGRUPADO)
        for cat in cuentas:
            pend = df[~df["conciliado"] & (df["categoria"] == cat) & (df[columna] > 0)]
            for _, fila_unica in pend.iterrows():
                if df.at[fila_unica.name, "conciliado"]:
                    continue
                otro_lado = "Banco" if fila_unica["origen"] == "Contabilidad" else "Contabilidad"
                vecinas = df[~df["conciliado"] & (df["categoria"] == cat) & (df["origen"] == otro_lado)
                             & (df[columna] > 0) & ((df["fecha"] - fila_unica["fecha"]).abs() <= ventana)]
                if len(vecinas) < 2 or len(vecinas) > 20:
                    continue
                grupo = self._subconjunto_que_suma(vecinas, fila_unica[columna], columna, cfg.MAX_FILAS_GRUPO)
                if grupo:
                    self._marcar(df, grupo + [fila_unica.name], "3 · Agrupado por fecha")
                    n += 1
        return n

    # ------------------------------------------------------------------
    # Nivel 4: por nombre de la contraparte (IA)
    # ------------------------------------------------------------------
    def nivel_4_nombres(self, df) -> int:
        mask = ~df["conciliado"] & (df["categoria"] == cfg.SIN_CATEGORIA)
        if not mask.any():
            return 0
        conceptos = df.loc[mask, "concepto"].unique().tolist()
        nombres = self.extractor.extraer(conceptos)
        df.loc[mask, "nombre"] = df.loc[mask, "concepto"].map(nombres).fillna(SIN_NOMBRE)
        df.loc[mask, "nombre"] = canonicalizar(df.loc[mask, "nombre"])

        n = 0
        pend = df[mask & (df["nombre"] != SIN_NOMBRE)]
        for nombre, g in pend.groupby("nombre"):
            b, c = g[g["origen"] == "Banco"], g[g["origen"] == "Contabilidad"]
            if b.empty or c.empty:
                continue
            if abs(b["neto"].sum() - c["neto"].sum()) <= self.tol:
                dias = abs((b["fecha"].max() - c["fecha"].max()).days)
                self._marcar(df, g.index, "4 · Nombre (IA)", dias)
                n += 1
        return n

    # ------------------------------------------------------------------
    # Nivel 5: aislar la diferencia en cuentas que no cierran
    # ------------------------------------------------------------------
    def nivel_5_aislar_diferencias(self, df, cuentas) -> int:
        n = 0
        for cat in cuentas:
            pend = df[~df["conciliado"] & (df["categoria"] == cat)]
            b, c = pend[pend["origen"] == "Banco"], pend[pend["origen"] == "Contabilidad"]
            if b.empty or c.empty:
                continue
            aislar: list[int] = []
            for col in ("ingreso", "egreso"):
                dif = b[col].sum() - c[col].sum()
                if abs(dif) <= self.tol:
                    continue
                lado = b if dif > 0 else c
                candidatas = lado[lado[col] > 0]
                soluciones = [list(combo)
                              for k in range(1, cfg.MAX_FILAS_DIFERENCIA + 1)
                              for combo in combinations(candidatas.index, k)
                              if abs(candidatas.loc[list(combo), col].sum() - abs(dif)) <= self.tol]
                if len(soluciones) != 1:  # ninguna o ambigua: no adivinamos
                    aislar = []
                    break
                aislar += soluciones[0]
            if aislar:
                resto = pend.index.difference(aislar)
                self._marcar(df, resto, "5 · Diferencia aislada")
                df.loc[aislar, "estado"] = "Pendiente - diferencia aislada"
                n += 1
        return n

    # ------------------------------------------------------------------
    # Orquestación
    # ------------------------------------------------------------------
    def conciliar(self, banco: pd.DataFrame, mayor: pd.DataFrame, cuenta: str) -> ResultadoConciliacion:
        df = self._preparar(banco, mayor)

        self.nivel_0_compensaciones(df)
        abiertas = self.nivel_1_cuentas(df)
        objetivo = abiertas + [cfg.SIN_CATEGORIA]
        for col in ("ingreso", "egreso"):
            self.nivel_2_uno_a_uno(df, objetivo, col)
            self.nivel_2_uno_a_uno(df, objetivo, col, ventana_dias=1)
        abiertas = self.nivel_1_cuentas(df, etiqueta="2 · Uno a uno")  # cuentas que cerraron tras el 1 a 1

        for col in ("ingreso", "egreso"):
            self.nivel_3_agrupado(df, abiertas, col)
        abiertas = self.nivel_1_cuentas(df, etiqueta="3 · Agrupado por fecha")

        self.nivel_4_nombres(df)
        self.nivel_5_aislar_diferencias(df, abiertas)

        df["conciliado"] = df["conciliado"].astype(bool)
        df["match"] = df["match"].astype("Int64")
        por_nivel = (df[df["conciliado"]].groupby("nivel").size().to_dict())
        return ResultadoConciliacion(cuenta=cuenta, movimientos=df, conciliados_por_nivel=por_nivel)
