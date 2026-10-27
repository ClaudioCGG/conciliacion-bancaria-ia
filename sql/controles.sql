-- Controles de gestión sobre el resultado de la conciliación.
-- Se ejecutan con DuckDB sobre la tabla `movimientos` (ver scripts/controles_sql.py).

-- name: tasa_por_banco
-- % conciliado automáticamente por cuenta bancaria
SELECT cuenta,
       COUNT(*)                                        AS movimientos,
       CAST(SUM(CASE WHEN conciliado THEN 1 ELSE 0 END) AS INTEGER) AS conciliados,
       ROUND(100.0 * AVG(CASE WHEN conciliado THEN 1 ELSE 0 END), 1) AS pct_automatico
FROM movimientos
GROUP BY cuenta
ORDER BY cuenta;

-- name: aporte_por_nivel
-- Cuánto aporta cada nivel de la cascada (y el acumulado)
WITH por_nivel AS (
    SELECT nivel, COUNT(*) AS filas
    FROM movimientos
    WHERE conciliado
    GROUP BY nivel
)
SELECT nivel,
       filas,
       SUM(filas) OVER (ORDER BY nivel)                              AS acumulado,
       ROUND(100.0 * SUM(filas) OVER (ORDER BY nivel)
             / (SELECT COUNT(*) FROM movimientos), 1)                AS pct_acumulado
FROM por_nivel
ORDER BY nivel;

-- name: registros_tardios
-- Asientos cargados más de 10 días después del movimiento bancario
SELECT cuenta, fecha, concepto, ingreso - egreso AS importe, dias_diferencia
FROM movimientos
WHERE estado = 'Conciliado - registro tardío' AND origen = 'Contabilidad'
ORDER BY dias_diferencia DESC;

-- name: demora_de_carga_por_usuario
-- Días promedio entre la fecha del movimiento y su carga en el sistema
SELECT usuario,
       COUNT(*)                                                    AS asientos,
       ROUND(AVG(DATE_DIFF('day', CAST(fecha AS DATE), CAST(fecha_registro AS DATE))), 1) AS dias_promedio_carga,
       MAX(DATE_DIFF('day', CAST(fecha AS DATE), CAST(fecha_registro AS DATE)))           AS dias_maximo
FROM movimientos
WHERE origen = 'Contabilidad' AND usuario IS NOT NULL
GROUP BY usuario
ORDER BY dias_promedio_carga DESC;

-- name: pendientes_por_importe
-- Pendientes ordenados por impacto en pesos
SELECT cuenta, origen, fecha, concepto, ingreso - egreso AS importe, estado
FROM movimientos
WHERE NOT conciliado
ORDER BY ABS(ingreso - egreso) DESC;
