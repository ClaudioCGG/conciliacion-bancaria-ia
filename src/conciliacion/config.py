"""Parámetros del motor. Todo lo que un usuario ajustaría vive acá."""

TOLERANCIA_MONTO = 0.01          # diferencia máxima aceptada entre importes ($)
DIAS_REGISTRO_TARDIO = 10        # más días que esto entre banco y mayor = "registro tardío"
VENTANA_DIAS_AGRUPADO = 1        # ventana de fechas para el agrupamiento (nivel 3)
MAX_FILAS_GRUPO = 6              # máximo de filas que se combinan en un grupo
MAX_FILAS_DIFERENCIA = 2         # máximo de filas para aislar una diferencia (nivel 5)

SIN_CATEGORIA = "Sin Categoría"

# Nivel 0: palabras que identifican una anulación o reverso, y similitud
# mínima (0-100) entre su concepto y el del movimiento original.
PATRON_ANULACION = r"\b(?:anulaci[oó]n|anula|reverso|contra-?asiento|extorno)\b(?:\s+asiento)?(?:\s+duplicado)?"
SIMILITUD_ANULACION = 90

# Reglas de categorización: palabra clave -> cuenta contable.
# Se aplican de la más larga a la más corta, así una clave específica
# ("comision mantenimiento") gana sobre una genérica ("qr").
# En producción esta tabla vive en una hoja del Excel (AuxConc) para que
# el equipo contable la mantenga sin tocar código.
REGLAS_CATEGORIAS: dict[str, str] = {
    "comision": "Comisiones y gastos bancarios",
    "comisiones": "Comisiones y gastos bancarios",
    "iva 21% s/comision": "Comisiones y gastos bancarios",
    "gastos bancarios": "Comisiones y gastos bancarios",
    "impuesto ley 25.413": "Impuesto Ley 25.413",
    "ley 25.413": "Impuesto Ley 25.413",
    "sircreb": "Retenciones SIRCREB",
    "getnet": "Tarjetas Getnet",
    "fiserv": "Cobros QR",
    "acreditacion comercio fiserv": "Cobros QR",
    "qr": "Cobros QR",
    "haberes": "Haberes",
}

# Cuenta del mayor que corresponde a cada extracto.
CUENTAS_MAYOR = {
    "Banco Alfa": "1.1.02.01 Banco Alfa Cta Cte",
    "Banco Beta": "1.1.02.02 Banco Beta Cta Cte",
}
