"""Asignación de cuenta contable a cada movimiento según su concepto."""

from __future__ import annotations

import re
from functools import lru_cache

from .config import REGLAS_CATEGORIAS, SIN_CATEGORIA


def patron_con_limite(clave: str) -> str:
    """Arma una regex que respeta límites de palabra 'de verdad'.

    `\\b` falla en dos casos que aparecen en extractos reales:
    1. Claves que empiezan o terminan con un símbolo ("0,6%"): ahí `\\b` nunca matchea.
    2. Claves pegadas a números ("078american"): `\\b` considera que dígito y
       letra son el mismo tipo de carácter y no ve el límite.
    Por eso se exige, solo cuando el extremo es una letra, que del otro lado
    no haya otra letra.
    """
    primero, ultimo = clave[:1], clave[-1:]
    if primero.isalpha():
        prefijo = r"(?<![^\W\d])"
    elif primero.isdigit():
        prefijo = r"\b"
    else:
        prefijo = ""
    if ultimo.isalpha():
        sufijo = r"(?![^\W\d])"
    elif ultimo.isdigit():
        sufijo = r"\b"
    else:
        sufijo = ""
    return prefijo + re.escape(clave) + sufijo


@lru_cache(maxsize=1)
def _reglas_compiladas(reglas: tuple[tuple[str, str], ...]):
    ordenadas = sorted(reglas, key=lambda kv: len(kv[0]), reverse=True)
    return [(re.compile(patron_con_limite(k.lower().strip())), v) for k, v in ordenadas]


def categorizar(concepto: str, reglas: dict[str, str] | None = None) -> str:
    reglas = reglas or REGLAS_CATEGORIAS
    texto = str(concepto).lower()
    for patron, categoria in _reglas_compiladas(tuple(reglas.items())):
        if patron.search(texto):
            return categoria
    return SIN_CATEGORIA


def detectar_conflictos(reglas: dict[str, str]) -> list[tuple[str, str, str, str]]:
    """Encuentra claves contenidas en otras que apuntan a cuentas distintas.
    No es un error en sí (gana la más larga), pero conviene revisarlas."""
    conflictos = []
    claves = list(reglas)
    for i, a in enumerate(claves):
        for b in claves[i + 1:]:
            corta, larga = sorted((a, b), key=len)
            if re.search(patron_con_limite(corta.lower()), larga.lower()) and reglas[a] != reglas[b]:
                conflictos.append((corta, reglas[corta], larga, reglas[larga]))
    return conflictos
