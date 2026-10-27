"""Flujo completo: extractos + mayor -> conciliación -> pendientes -> Excel."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from .config import CUENTAS_MAYOR
from .extractor_nombres import crear_extractor
from .motor import MotorConciliacion
from .normalizador import NORMALIZADORES, control_de_saldos, leer_mayor
from .reporte import exportar_excel
from .revision import clasificar_pendientes

ARCHIVOS = {
    "Banco Alfa": "banco_alfa_{periodo}.xlsx",
    "Banco Beta": "banco_beta_{periodo}.xlsx",
}


def conciliar_periodo(dir_datos: str | Path, periodo: str, salida: str | Path | None = None,
                      usar_ia: bool = True, verbose: bool = True):
    dir_datos = Path(dir_datos)
    inicio = time.perf_counter()
    motor = MotorConciliacion(extractor=crear_extractor(preferir_ia=usar_ia))
    log = print if verbose else (lambda *a, **k: None)
    log(f"Extractor de nombres: {motor.extractor.nombre}")

    resultados = []
    for banco, plantilla in ARCHIVOS.items():
        extracto, saldo_inicial = NORMALIZADORES[banco](dir_datos / plantilla.format(periodo=periodo))
        errores = control_de_saldos(extracto, saldo_inicial)
        if len(errores):
            raise ValueError(f"{banco}: {len(errores)} filas no cierran contra el saldo. Revisar el extracto.")
        mayor = leer_mayor(dir_datos / f"mayor_bancos_{periodo}.xlsx", CUENTAS_MAYOR[banco], banco)
        r = motor.conciliar(extracto, mayor, banco)
        resultados.append(r)
        log(f"{banco}: {r.conciliados}/{r.total} movimientos conciliados ({r.tasa:.1%}), "
            f"{r.total - r.conciliados} pendientes")

    pendientes = clasificar_pendientes(pd.concat([r.movimientos for r in resultados], ignore_index=True))
    segundos = time.perf_counter() - inicio
    if salida:
        ruta = exportar_excel(resultados, pendientes, salida)
        log(f"Informe: {ruta}")
    log(f"Tiempo total: {segundos:.1f} s")
    return resultados, pendientes, segundos
