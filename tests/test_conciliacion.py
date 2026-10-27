import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from conciliacion.categorias import categorizar  # noqa: E402
from conciliacion.extractor_nombres import ExtractorReglas, canonicalizar  # noqa: E402
from conciliacion.metricas import evaluar  # noqa: E402
from conciliacion.motor import MotorConciliacion  # noqa: E402
from conciliacion.normalizador import (control_de_saldos, monto_ar_a_float,  # noqa: E402
                                       normalizar_banco_alfa, normalizar_banco_beta)
from conciliacion.pipeline import conciliar_periodo  # noqa: E402

DATOS = RAIZ / "data" / "raw"


# --- Normalización ----------------------------------------------------
@pytest.mark.parametrize("texto, esperado", [
    ("1.234.567,89", 1234567.89), ("-2.084,47", -2084.47), ("0,50", 0.5), ("", None), (None, None),
])
def test_monto_formato_argentino(texto, esperado):
    assert monto_ar_a_float(texto) == esperado


@pytest.mark.parametrize("normalizador, archivo", [
    (normalizar_banco_alfa, "banco_alfa_202603.xlsx"),
    (normalizar_banco_beta, "banco_beta_202603.xlsx"),
])
def test_extractos_cierran_contra_el_saldo(normalizador, archivo):
    df, saldo_inicial = normalizador(DATOS / archivo)
    assert len(df) > 0
    assert control_de_saldos(df, saldo_inicial).empty


def test_beta_une_descripciones_partidas():
    df, _ = normalizar_banco_beta(DATOS / "banco_beta_202603.xlsx")
    assert df["concepto"].str.match(r"^\d+$").sum() == 0  # ninguna fila quedó con solo el resto del texto


# --- Categorías y nombres --------------------------------------------
@pytest.mark.parametrize("concepto, cuenta", [
    ("COMISION MANTENIMIENTO OPERACIONES QR", "Comisiones y gastos bancarios"),  # gana la clave más larga
    ("Imp. Ley 25.413 deb y cred marzo", "Impuesto Ley 25.413"),
    ("Pago de haberes 1ra quincena", "Haberes"),
    ("TRANSF RECIBIDA OLIVARES ANA", "Sin Categoría"),  # 'iva' dentro de un apellido no categoriza
])
def test_categorizar(concepto, cuenta):
    assert categorizar(concepto) == cuenta


def test_extractor_reglas_y_canonicalizacion():
    conceptos = ["TRANSF RECIBIDA GOMEZ LUCIA BEATRIZ CUIT 20-1234-5 CBU 123", "Cobro FC A 0001-00001234 Gómez",
                 "TRANSF RECIBIDA CBU 0110 SIN DATOS ORDENANTE"]
    nombres = ExtractorReglas().extraer(conceptos)
    assert nombres[conceptos[2]] == "N/A"
    canon = canonicalizar(pd.Series([nombres[conceptos[0]], nombres[conceptos[1]]]))
    assert canon.nunique() == 1


# --- Motor ------------------------------------------------------------
def _mov(origen, fecha, concepto, monto, ref):
    return {"fecha": pd.Timestamp(fecha), "concepto": concepto, "ref": ref,
            "ingreso": max(monto, 0.0), "egreso": max(-monto, 0.0), "saldo": None,
            "origen": origen, "cuenta": "Test"}


def test_no_concilia_cuando_el_importe_es_ambiguo_y_no_hay_nombre():
    banco = pd.DataFrame([_mov("Banco", "2026-03-02", "TRANSF RECIBIDA CBU 1", 100.0, "b1"),
                          _mov("Banco", "2026-03-02", "TRANSF RECIBIDA CBU 2", 100.0, "b2")])
    mayor = pd.DataFrame([_mov("Contabilidad", "2026-03-02", "Cobro varios", 100.0, "m1")])
    r = MotorConciliacion().conciliar(banco, mayor, "Test")
    assert r.conciliados == 0  # dos candidatos para un asiento: no se adivina


def test_agrupa_sueldos_por_fecha():
    banco = pd.DataFrame([_mov("Banco", "2026-03-05", f"PAGO HABERES LEGAJO {i}", -m, f"b{i}")
                          for i, m in enumerate([1000.0, 2000.0, 3000.0])])
    mayor = pd.DataFrame([_mov("Contabilidad", "2026-03-05", "Pago de haberes", -6000.0, "m1"),
                          _mov("Contabilidad", "2026-03-20", "Pago de haberes", -999.0, "m2")])
    r = MotorConciliacion().conciliar(banco, mayor, "Test")
    assert set(r.movimientos.loc[r.movimientos["conciliado"], "ref"]) == {"b0", "b1", "b2", "m1"}


# --- De punta a punta, contra la respuesta conocida -------------------
def test_pipeline_sin_falsos_positivos_y_detecta_todas_las_excepciones():
    resultados, pendientes, _ = conciliar_periodo(DATOS, "202603", usar_ia=False, verbose=False)
    verdad = pd.read_csv(RAIZ / "data" / "verdad" / "verdad_202603.csv")
    m = evaluar(pd.concat([r.movimientos for r in resultados], ignore_index=True), verdad)
    assert m["falsos_positivos"] == 0
    assert m["precision"] == 1.0
    assert m["excepciones_detectadas"] == m["excepciones"]
    assert m["tasa_automatica"] >= 0.95
    assert pendientes["sugerencia"].str.len().gt(0).all()


# --- Nivel 0 y control de matches -------------------------------------
def test_duplicado_corregido_en_el_mes_se_compensa():
    banco = pd.DataFrame([_mov("Banco", "2026-03-10", "TRANSF ENVIADA A ACME SA", -500.0, "b1")])
    mayor = pd.DataFrame([
        _mov("Contabilidad", "2026-03-10", "Pago OP 0001-000001 Acme SA", -500.0, "m1"),
        _mov("Contabilidad", "2026-03-11", "Pago OP 0001-000001 Acme SA", -500.0, "m2"),
        _mov("Contabilidad", "2026-03-15", "Anulación asiento duplicado Pago OP 0001-000001 Acme SA", 500.0, "m3"),
    ])
    r = MotorConciliacion().conciliar(banco, mayor, "Test")
    assert r.conciliados == 4
    niveles = r.movimientos.set_index("ref")["nivel"]
    assert niveles["m2"] == niveles["m3"] == "0 · Compensación interna"


def test_duplicado_sin_corregir_queda_pendiente():
    banco = pd.DataFrame([_mov("Banco", "2026-03-10", "TRANSF ENVIADA A ACME SA", -500.0, "b1")])
    mayor = pd.DataFrame([_mov("Contabilidad", "2026-03-10", "Pago OP 0001-000001 Acme SA", -500.0, "m1"),
                          _mov("Contabilidad", "2026-03-11", "Pago OP 0001-000001 Acme SA", -500.0, "m2")])
    r = MotorConciliacion().conciliar(banco, mayor, "Test")
    assert r.conciliados == 0


def test_todos_los_matches_cierran_en_cero():
    from conciliacion.revision import control_de_matches
    resultados, _, _ = conciliar_periodo(DATOS, "202603", usar_ia=False, verbose=False)
    control = control_de_matches(pd.concat([r.movimientos for r in resultados], ignore_index=True))
    assert len(control) > 0
    assert control["Cierra"].all()
