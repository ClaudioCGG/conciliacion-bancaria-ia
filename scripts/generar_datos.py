"""
Genera datos SINTÉTICOS para la demo de conciliación bancaria.

Simula un mes de operación (marzo 2026) de una empresa ficticia,
"Distribuidora del Sur SRL", con dos cuentas bancarias:

- Banco Alfa: cuenta principal. Exportación tipo "PDF pasado a Excel",
  con encabezados repetidos por página, montos como texto en formato
  argentino (1.234,56) y filas de ruido (SALDO ANTERIOR, TOTALES).
- Banco Beta: cuenta secundaria. Una sola columna de importe con signo,
  fechas dd/mm/aa y descripciones que a veces se cortan en dos filas.

También genera el libro mayor contable de ambas cuentas y un archivo de
"verdad" que indica, para cada movimiento, si DEBERÍA conciliar. Eso
permite medir la precisión del motor de forma objetiva.

Las excepciones (lo que un buen motor NO debe conciliar) se siembran a
propósito y están documentadas en EXCEPCIONES.

Todos los nombres, CUIT, CBU e importes son inventados.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SEMILLA = 2026
RAIZ = Path(__file__).resolve().parents[1]
DIR_RAW = RAIZ / "data" / "raw"
DIR_VERDAD = RAIZ / "data" / "verdad"

ANIO, MES = 2026, 3

CLIENTES = [
    "PEREYRA MARTIN ALEJANDRO", "GOMEZ LUCIA BEATRIZ", "FERNANDEZ JUAN PABLO",
    "RODRIGUEZ SILVINA", "LOPEZ HERNAN DARIO", "MARTINEZ CAROLINA",
    "SANCHEZ ROBERTO CARLOS", "ROMERO PATRICIA", "TORRES GUSTAVO ADRIAN",
    "ALVAREZ MARIANA", "RUIZ FEDERICO", "BENITEZ ANALIA SOLEDAD",
    "ACOSTA DIEGO", "MEDINA VALERIA", "HERRERA NICOLAS", "AGUIRRE ROMINA",
    "CASTRO EZEQUIEL", "MOLINA FLORENCIA", "SUAREZ MATIAS", "ROJAS GABRIELA",
    "OJEDA SEBASTIAN", "QUIROGA NATALIA", "FIGUEROA PABLO", "CABRERA JULIETA",
    "VILLALBA ESTEBAN", "LEDESMA ROCIO", "CORIA MAXIMILIANO", "PERALTA AGUSTINA",
    "SOSA LEANDRO", "ZALAZAR CAMILA",
    "ALMACEN LA ESQUINA SRL", "MERCADITO DON PEPE SA", "AUTOSERVICIO NORTE SRL",
    "KIOSCO EL TREBOL SH", "SUPER FAMILIA SA", "DESPENSA LOS ANDES SRL",
]

PROVEEDORES = [
    "LACTEOS DEL VALLE SA", "PANIFICADORA TRIGAL SRL", "BEBIDAS PAMPA SA",
    "FRIGORIFICO EL CEIBO SA", "DISTRIBUIDORA LITORAL SRL", "TRANSPORTES RIOPLATENSE SA",
    "PAPELERA CENTRAL SRL", "LIMPIEZA TOTAL SA", "ENVASES DEL PLATA SRL",
    "SERVICIOS INFORMATICOS GALAXIA SRL", "SEGUROS PROTECCION SA", "ENERGIA URBANA SA",
]

EMPLEADOS = 5  # por quincena

random.seed(SEMILLA)


def _dias_habiles() -> list[date]:
    d, dias = date(ANIO, MES, 1), []
    while d.month == MES:
        if d.weekday() < 5:
            dias.append(d)
        d += timedelta(days=1)
    return dias


DIAS = _dias_habiles()


def _monto(minimo: float, maximo: float) -> float:
    return round(random.uniform(minimo, maximo), 2)


def _cuit(prefijo: str) -> str:
    return f"{prefijo}-{random.randint(10_000_000, 39_999_999)}-{random.randint(0, 9)}"


def _cbu() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(22))


def _apellido_contable(nombre_banco: str) -> str:
    """Cómo lo escribiría un administrativo en el mayor: apellido con
    mayúscula inicial y tilde, o razón social en formato título."""
    tildes = {"FERNANDEZ": "Fernández", "RODRIGUEZ": "Rodríguez", "LOPEZ": "López",
              "MARTINEZ": "Martínez", "SANCHEZ": "Sánchez", "ALVAREZ": "Álvarez",
              "BENITEZ": "Benítez", "GOMEZ": "Gómez", "SUAREZ": "Suárez"}
    palabras = nombre_banco.split()
    if palabras[-1] in {"SRL", "SA", "SH"}:
        return " ".join(p.capitalize() for p in palabras[:-1]) + " " + palabras[-1]
    return tildes.get(palabras[0], palabras[0].capitalize())


# ----------------------------------------------------------------------
# Construcción de movimientos "reales" de cada cuenta
# Cada movimiento bancario y cada asiento llevan una referencia única.
# La verdad se guarda como: ref -> debe_conciliar (bool) + motivo.
# ----------------------------------------------------------------------
movs_alfa: list[dict] = []
movs_beta: list[dict] = []
mayor: list[dict] = []
verdad: list[dict] = []
EXCEPCIONES: list[str] = []

_ref_banco = iter(range(810_001, 900_000))
_nro_asiento = iter(range(4_501, 9_999))


def banco(lista, fecha, concepto, monto, debe=True, motivo="match esperado"):
    """monto > 0 = crédito (ingreso); monto < 0 = débito (egreso)."""
    ref = f"B{next(_ref_banco)}"
    lista.append({"fecha": fecha, "concepto": concepto, "monto": monto, "ref": ref})
    verdad.append({"ref": ref, "origen": "banco", "debe_conciliar": debe, "motivo": motivo})
    return ref


def asiento(cuenta, fecha, detalle, monto, debe=True, motivo="match esperado",
            dias_carga=None, usuario=None):
    nro = next(_nro_asiento)
    ref = f"A{nro}"
    if dias_carga is None:
        dias_carga = random.randint(0, 2)
    mayor.append({
        "Fch Mov": fecha, "Nro Asiento": nro, "Cuenta": cuenta, "Detalle": detalle,
        "Debe": monto if monto > 0 else 0.0, "Haber": -monto if monto < 0 else 0.0,
        "Usuario": usuario or random.choice(["mgarcia", "lsosa", "admin2"]),
        "Fecha Registro": fecha + timedelta(days=dias_carga),
    })
    verdad.append({"ref": ref, "origen": "mayor", "debe_conciliar": debe, "motivo": motivo})
    return ref


CTA_ALFA = "1.1.02.01 Banco Alfa Cta Cte"
CTA_BETA = "1.1.02.02 Banco Beta Cta Cte"

# 1) Cobros de clientes por transferencia (Banco Alfa) ------------------
nro_factura = 1_200
cobros_hechos: list[tuple[str, float, date]] = []
for _ in range(118):
    cliente = random.choice(CLIENTES)
    f = random.choice(DIAS[:-2])
    m = _monto(45_000, 2_400_000)
    nro_factura += 1
    es_empresa = cliente.split()[-1] in {"SRL", "SA", "SH"}
    banco(movs_alfa, f, f"TRANSF RECIBIDA {cliente} CUIT {_cuit('30' if es_empresa else '20')} CBU {_cbu()}", m)
    f_mayor = f + timedelta(days=random.choice([0, 0, 0, 1, 1, 2]))
    asiento(CTA_ALFA, f_mayor, f"Cobro FC A 0001-{nro_factura:08d} {_apellido_contable(cliente)}", m)
    cobros_hechos.append((cliente, m, f))

# 1b) Cobros registrados tarde (más de 10 días después) -----------------
for _ in range(5):
    cliente = random.choice(CLIENTES)
    f = random.choice(DIAS[:8])
    m = _monto(80_000, 900_000)
    nro_factura += 1
    banco(movs_alfa, f, f"TRANSF RECIBIDA {cliente} CUIT {_cuit('20')} CBU {_cbu()}", m,
          motivo="match esperado (registro tardío)")
    asiento(CTA_ALFA, f + timedelta(days=random.randint(12, 18)),
            f"Cobro FC A 0001-{nro_factura:08d} {_apellido_contable(cliente)}", m,
            motivo="match esperado (registro tardío)")

# 1c) Mismo importe pagado por dos clientes distintos la misma semana:
#     el match por monto es ambiguo; lo resuelve la etapa de nombres.
for monto_repetido in (150_000.00, 300_000.00, 75_500.00):
    c1, c2 = random.sample(CLIENTES[:30], 2)
    f = random.choice(DIAS[5:15])
    for c in (c1, c2):
        nro_factura += 1
        banco(movs_alfa, f, f"TRANSF RECIBIDA {c} CUIT {_cuit('20')} CBU {_cbu()}", monto_repetido,
              motivo="match esperado (monto repetido, requiere nombre)")
        asiento(CTA_ALFA, f + timedelta(days=random.randint(0, 3)),
                f"Cobro FC A 0001-{nro_factura:08d} {_apellido_contable(c)}", monto_repetido,
                motivo="match esperado (monto repetido, requiere nombre)")

# 1d) Una factura pagada en dos transferencias en días distintos:
#     el mayor tiene un solo asiento por el total.
for _ in range(4):
    cliente = random.choice(CLIENTES[30:])  # empresas
    total = _monto(600_000, 1_800_000)
    parte1 = round(total * random.uniform(0.4, 0.6), 2)
    parte2 = round(total - parte1, 2)
    f1 = random.choice(DIAS[:10])
    f2 = f1 + timedelta(days=random.randint(5, 9))
    for parte, fx in ((parte1, f1), (parte2, f2)):
        banco(movs_alfa, fx, f"TRANSF RECIBIDA {cliente} CUIT {_cuit('30')} CBU {_cbu()}", parte,
              motivo="match esperado (pago en cuotas, requiere nombre)")
    nro_factura += 1
    asiento(CTA_ALFA, f2, f"Cobro FC A 0001-{nro_factura:08d} {_apellido_contable(cliente)}", total,
            motivo="match esperado (pago en cuotas, requiere nombre)")

# 2) Pagos a proveedores ----------------------------------------------
nro_op = 300
for _ in range(46):
    prov = random.choice(PROVEEDORES)
    f = random.choice(DIAS)
    m = _monto(120_000, 3_500_000)
    nro_op += 1
    banco(movs_alfa, f, f"TRANSF ENVIADA A {prov} CUIT {_cuit('30')}", -m)
    asiento(CTA_ALFA, f - timedelta(days=random.choice([0, 0, 1])),
            f"Pago OP 0001-{nro_op:06d} {_apellido_contable(prov)}", -m)

# 3) Liquidaciones de tarjetas Getnet (diarias, Banco Alfa) --------------
for f in DIAS:
    m = _monto(180_000, 950_000)
    banco(movs_alfa, f, f"ACREDITACION GETNET LIQ {random.randint(100000, 999999)}", m)
    asiento(CTA_ALFA, f, f"Liquidación Getnet {f:%d/%m}", m)

# 4) Haberes en dos tandas: el banco muestra una transferencia por
#    empleado; el mayor, un solo asiento por tanda.
for f_pago in (DIAS[3], DIAS[14]):
    sueldos = [_monto(850_000, 1_650_000) for _ in range(EMPLEADOS)]
    for i, s in enumerate(sueldos, 1):
        banco(movs_alfa, f_pago, f"PAGO HABERES LEGAJO {100 + i}", -s,
              motivo="match esperado (agrupado por fecha)")
    asiento(CTA_ALFA, f_pago, f"Pago de haberes {'1ra' if f_pago == DIAS[3] else '2da'} quincena", -round(sum(sueldos), 2),
            motivo="match esperado (agrupado por fecha)")

# 5) Gastos bancarios e impuestos: muchas filas chicas en el banco,
#    un asiento mensual en el mayor.
comisiones, impuestos, sircreb = [], [], []
for f in DIAS:
    for _ in range(random.randint(1, 3)):
        c = _monto(850, 6_500)
        iva = round(c * 0.21, 2)
        banco(movs_alfa, f, "COMISION TRANSFERENCIA INMEDIATA", -c)
        banco(movs_alfa, f, "IVA 21% S/COMISION", -iva)
        comisiones += [c, iva]
    imp = _monto(9_000, 48_000)
    banco(movs_alfa, f, "IMPUESTO LEY 25.413 DEBITO 0,6%", -imp)
    impuestos.append(imp)
    imp2 = _monto(7_000, 40_000)
    banco(movs_alfa, f, "IMPUESTO LEY 25.413 CREDITO 0,6%", -imp2)
    impuestos.append(imp2)
for f in DIAS[::5]:
    s = _monto(15_000, 60_000)
    banco(movs_alfa, f, "REGIMEN DE RECAUDACION SIRCREB", -s)
    sircreb.append(s)

fin_mes = DIAS[-1]
asiento(CTA_ALFA, fin_mes, "Comisiones y gastos bancarios marzo", -round(sum(comisiones), 2), dias_carga=3)
asiento(CTA_ALFA, fin_mes, "Imp. Ley 25.413 deb y cred marzo", -round(sum(impuestos), 2), dias_carga=3)
asiento(CTA_ALFA, fin_mes, "Retenciones Sircreb marzo", -round(sum(sircreb), 2), dias_carga=3)

# 6) Banco Beta: acreditaciones QR y pagos menores ----------------------
qr_total = []
for f in DIAS:
    m = _monto(60_000, 420_000)
    banco(movs_beta, f, f"ACREDITACION COMERCIO FISERV QR LOTE {random.randint(1000, 9999)}", m)
    qr_total.append(m)
asiento(CTA_BETA, fin_mes, "Acreditaciones QR Fiserv marzo", round(sum(qr_total), 2), dias_carga=2)

com_beta = []
for f in DIAS:
    c = _monto(400, 2_200)
    banco(movs_beta, f, "COMISION MANTENIMIENTO OPERACIONES QR", -c)
    com_beta.append(c)
asiento(CTA_BETA, fin_mes, "Comisiones bancarias Beta marzo", -round(sum(com_beta), 2), dias_carga=2)

for _ in range(14):
    prov = random.choice(PROVEEDORES[6:])
    f = random.choice(DIAS)
    m = _monto(40_000, 650_000)
    nro_op += 1
    banco(movs_beta, f, f"DEBITO TRANSFERENCIA A {prov}", -m)
    asiento(CTA_BETA, f, f"Pago OP 0001-{nro_op:06d} {_apellido_contable(prov)}", -m)

# ----------------------------------------------------------------------
# EXCEPCIONES SEMBRADAS: lo que el motor NO debe conciliar
# ----------------------------------------------------------------------
# E1. Liquidación Getnet acreditada pero nunca registrada.
f = DIAS[17]
banco(movs_alfa, f, f"ACREDITACION GETNET LIQ {random.randint(100000, 999999)}", _monto(300_000, 600_000),
      debe=False, motivo="E1 ingreso en banco no contabilizado")
EXCEPCIONES.append("E1: liquidación Getnet acreditada sin registrar en el mayor")

# E2. Liquidación final de un empleado pagada, sin asiento.
banco(movs_alfa, DIAS[-3], "PAGO HABERES LEGAJO 199 LIQ FINAL", -_monto(1_900_000, 2_600_000),
      debe=False, motivo="E2 egreso en banco no contabilizado")
EXCEPCIONES.append("E2: liquidación final de haberes pagada sin asiento")

# E3. Cheque emitido y registrado, todavía no debitado por el banco.
nro_op += 1
asiento(CTA_ALFA, DIAS[-2], f"Pago OP 0001-{nro_op:06d} cheque 00045871 Transportes Rioplatense SA",
        -_monto(700_000, 1_200_000), debe=False, motivo="E3 egreso contable sin débito bancario")
EXCEPCIONES.append("E3: cheque emitido aún no debitado")

# E4. Error de tipeo: el banco dice 1.250.000 y el mayor 1.205.000.
cliente = "QUIROGA NATALIA"
f = DIAS[11]
banco(movs_alfa, f, f"TRANSF RECIBIDA {cliente} CUIT {_cuit('27')} CBU {_cbu()}", 1_250_000.00,
      debe=False, motivo="E4 diferencia de importe (tipeo)")
nro_factura += 1
asiento(CTA_ALFA, f, f"Cobro FC A 0001-{nro_factura:08d} Quiroga", 1_205_000.00,
        debe=False, motivo="E4 diferencia de importe (tipeo)")
EXCEPCIONES.append("E4: cobro con importe mal tipeado en el mayor")

# E5. Transferencia recibida sin datos del ordenante, no registrada.
banco(movs_alfa, DIAS[9], f"TRANSF RECIBIDA CBU {_cbu()} SIN DATOS ORDENANTE", _monto(50_000, 250_000),
      debe=False, motivo="E5 ingreso no identificado")
EXCEPCIONES.append("E5: transferencia recibida sin identificar")

# E6. Cobro registrado dos veces en el mayor.
cliente = "CABRERA JULIETA"
f = DIAS[6]
m = 412_350.00
banco(movs_alfa, f, f"TRANSF RECIBIDA {cliente} CUIT {_cuit('27')} CBU {_cbu()}", m,
      motivo="E6 cobro duplicado en mayor (el original sí debería conciliar)")
nro_factura += 1
asiento(CTA_ALFA, f, f"Cobro FC A 0001-{nro_factura:08d} Cabrera", m,
        motivo="E6 cobro duplicado en mayor (el original sí debería conciliar)")
asiento(CTA_ALFA, f + timedelta(days=1), f"Cobro FC A 0001-{nro_factura:08d} Cabrera", m,
        debe=False, motivo="E6 asiento duplicado")
EXCEPCIONES.append("E6: cobro cargado dos veces en el mayor")

# E7. Comisión de mantenimiento cobrada y no incluida en el asiento mensual.
banco(movs_alfa, DIAS[-1], "COMISION MANTENIMIENTO CUENTA", -18_500.00,
      debe=False, motivo="E7 gasto bancario no incluido en el asiento mensual")
banco(movs_alfa, DIAS[-1], "IVA 21% S/COMISION", -3_885.00,
      debe=False, motivo="E7 gasto bancario no incluido en el asiento mensual")
EXCEPCIONES.append("E7: comisión de mantenimiento fuera del asiento mensual de gastos")

# ----------------------------------------------------------------------
# CORRECCIONES DENTRO DEL MES: errores que ya fueron corregidos y que el
# motor SÍ debe conciliar (compensándolos entre sí).
# ----------------------------------------------------------------------
# C1. Pago registrado dos veces y anulado con un contra-asiento en el mes.
prov = "SEGUROS PROTECCION SA"
f = DIAS[12]
m = 287_640.00
nro_op += 1
banco(movs_alfa, f, f"TRANSF ENVIADA A {prov} CUIT {_cuit('30')}", -m,
      motivo="C1 duplicado corregido en el mes")
asiento(CTA_ALFA, f, f"Pago OP 0001-{nro_op:06d} {_apellido_contable(prov)}", -m,
        motivo="C1 duplicado corregido en el mes")
asiento(CTA_ALFA, f + timedelta(days=1), f"Pago OP 0001-{nro_op:06d} {_apellido_contable(prov)}", -m,
        motivo="C1 duplicado corregido en el mes")
asiento(CTA_ALFA, f + timedelta(days=6), f"Anulación asiento duplicado Pago OP 0001-{nro_op:06d} "
        f"{_apellido_contable(prov)}", m, motivo="C1 duplicado corregido en el mes", usuario="mgarcia")

# C2. Débito directo rechazado: el banco lo debita y lo revierte en el mes.
f = DIAS[16]
m = 96_420.50
banco(movs_alfa, f, "DEBITO DIRECTO ENERGIA URBANA SA CLIENTE 778812", -m,
      motivo="C2 débito y reverso en el mes")
banco(movs_alfa, f + timedelta(days=2), "REVERSO DEBITO DIRECTO ENERGIA URBANA SA CLIENTE 778812", m,
      motivo="C2 débito y reverso en el mes")


# ----------------------------------------------------------------------
# Exportación con el "desorden" típico de cada banco
# ----------------------------------------------------------------------
def _fmt_ar(x: float) -> str:
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def exportar_banco_alfa(movs, saldo_inicial, ruta):
    movs = sorted(movs, key=lambda r: (r["fecha"], r["ref"]))
    filas = [
        ["Banco Alfa S.A. - Resumen de cuenta", None, None, None, None, None],
        ["CC $ 0123-004567/8 (Cta.Cte.Bancaria) DISTRIBUIDORA DEL SUR SRL", None, None, None, None, None],
        [f"SALDO ANTERIOR {_fmt_ar(saldo_inicial)}", None, None, None, None, None],
    ]
    encabezado = ["FECHA", "CONCEPTO", "REFERENCIA", "DEBITO", "CREDITO", "SALDO"]
    saldo = saldo_inicial
    for i, r in enumerate(movs):
        if i % 45 == 0:
            if i:
                filas.append([f"SALDO AL {r['fecha']:%d/%m}", None, None, None, None, _fmt_ar(saldo)])
            filas.append(encabezado)
        saldo = round(saldo + r["monto"], 2)
        filas.append([
            f"{r['fecha']:%d/%m}", r["concepto"], r["ref"],
            _fmt_ar(r["monto"]) if r["monto"] < 0 else "",
            _fmt_ar(r["monto"]) if r["monto"] > 0 else "",
            _fmt_ar(saldo),
        ])
    filas.append(["TOTAL MOVIMIENTOS", None, None, None, None, None])
    filas.append(["Legales y avisos: el impuesto a los débitos y créditos se informa a título informativo.",
                  None, None, None, None, None])
    pd.DataFrame(filas).to_excel(ruta, index=False, header=False, sheet_name="Table 1")
    return saldo


def exportar_banco_beta(movs, saldo_inicial, ruta):
    movs = sorted(movs, key=lambda r: (r["fecha"], r["ref"]))
    filas = [["Fecha", "Descripción", "Nro Operación", "Importe", "Saldo"]]
    saldo = saldo_inicial
    for r in movs:
        saldo = round(saldo + r["monto"], 2)
        signo = "-" if r["monto"] < 0 else ""
        concepto = r["concepto"]
        # Algunas descripciones largas se cortan en dos filas
        if len(concepto) > 38 and random.random() < 0.5:
            corte = concepto.rfind(" ", 0, 38)
            filas.append([f"{r['fecha']:%d/%m/%y}", concepto[:corte], r["ref"],
                          signo + _fmt_ar(r["monto"]), _fmt_ar(saldo)])
            filas.append([None, concepto[corte + 1:], None, None, None])
        else:
            filas.append([f"{r['fecha']:%d/%m/%y}", concepto, r["ref"],
                          signo + _fmt_ar(r["monto"]), _fmt_ar(saldo)])
    pd.DataFrame(filas).to_excel(ruta, index=False, header=False, sheet_name="Movimientos")
    return saldo


def main():
    DIR_RAW.mkdir(parents=True, exist_ok=True)
    DIR_VERDAD.mkdir(parents=True, exist_ok=True)

    exportar_banco_alfa(movs_alfa, 18_452_310.45, DIR_RAW / "banco_alfa_202603.xlsx")
    exportar_banco_beta(movs_beta, 2_315_870.10, DIR_RAW / "banco_beta_202603.xlsx")

    df_mayor = pd.DataFrame(mayor).sort_values(["Cuenta", "Fch Mov", "Nro Asiento"])
    df_mayor["Fch Mov"] = pd.to_datetime(df_mayor["Fch Mov"])
    df_mayor["Fecha Registro"] = pd.to_datetime(df_mayor["Fecha Registro"])
    df_mayor.to_excel(DIR_RAW / "mayor_bancos_202603.xlsx", index=False, sheet_name="Mayor")

    pd.DataFrame(verdad).to_csv(DIR_VERDAD / "verdad_202603.csv", index=False)

    print(f"Banco Alfa: {len(movs_alfa)} movimientos")
    print(f"Banco Beta: {len(movs_beta)} movimientos")
    print(f"Mayor:      {len(mayor)} asientos")
    print("Excepciones sembradas:")
    for e in EXCEPCIONES:
        print("  -", e)


if __name__ == "__main__":
    main()
