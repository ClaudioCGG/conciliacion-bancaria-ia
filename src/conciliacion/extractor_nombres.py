"""
Extracción del nombre de la contraparte (cliente o proveedor) desde el
texto libre del concepto.

El banco escribe "TRANSF RECIBIDA PEREYRA MARTIN ALEJANDRO CUIT 20-... CBU ..."
y el administrativo carga "Cobro FC A 0001-00001234 Pereyra". Para el motor,
son la misma persona. Esta etapa resuelve los casos que el match por importe
no puede: importes repetidos, pagos en cuotas, etc.

Dos implementaciones con la misma interfaz:
- ExtractorGemini: usa un LLM (Gemini). Es la que corre en producción;
  tolera textos muy desordenados.
- ExtractorReglas: limpieza por reglas, sin costo ni API key. Es la que
  usa la demo por defecto para que cualquiera pueda correrla.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata

import pandas as pd
from rapidfuzz import fuzz, process

SIN_NOMBRE = "N/A"

_RUIDO = {
    "TRANSF", "TRANSFERENCIA", "RECIBIDA", "ENVIADA", "DEBITO", "CREDITO", "A", "DE",
    "COBRO", "PAGO", "FC", "OP", "CHEQUE", "CUIT", "CBU", "SIN", "DATOS", "ORDENANTE",
    "INMEDIATA", "DEB", "CRED",
}
_CORTE = re.compile(r"\b(CUIT|CBU|CUIL|DNI)\b.*$")


def normalizar_texto(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper()).strip()


class ExtractorReglas:
    """Quita términos bancarios, códigos y números; lo que queda es el nombre."""

    nombre = "reglas"

    def extraer(self, conceptos: list[str]) -> dict[str, str]:
        resultado = {}
        for c in conceptos:
            t = _CORTE.sub("", normalizar_texto(c))
            palabras = [p for p in re.split(r"[\s\-/]+", t)
                        if p and p not in _RUIDO and not any(ch.isdigit() for ch in p)]
            nombre = " ".join(palabras)
            resultado[c] = nombre if len(nombre) >= 3 else SIN_NOMBRE
        return resultado


class ExtractorGemini:
    """Extracción con LLM, en lotes y con reintentos (versión de producción).
    Requiere la variable de entorno GEMINI_API_KEY y el paquete google-genai."""

    nombre = "gemini"
    PROMPT = """Para cada leyenda bancaria o contable de la lista, extraé el nombre
principal del cliente, persona o proveedor (para personas, apellido y nombres;
para empresas, la razón social sin el tipo societario).
Ignorá términos bancarios (TRANSF, DEB, CRED, CBU, CUIT, OP, IVA, SIRCREB,
CHEQUE), números, fechas e importes. Si no hay un nombre identificable,
devolvé null.
Respondé SOLO con un JSON array en el mismo orden:
[{{"leyenda": "<leyenda original>", "nombre": "<nombre o null>"}}]
Lista: {lista}"""

    def __init__(self, modelo: str | None = None, lote: int = 25, reintentos: int = 3):
        from google import genai  # import diferido: solo si se usa

        self.cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.modelo = modelo or os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
        self.lote, self.reintentos = lote, reintentos

    def _llamar(self, lote: list[str]) -> dict[str, str | None]:
        respuesta = self.cliente.models.generate_content(
            model=self.modelo,
            contents=self.PROMPT.format(lista=json.dumps(lote, ensure_ascii=False)),
            config={"temperature": 0, "response_mime_type": "application/json"},
        )
        return {item["leyenda"]: item.get("nombre") for item in json.loads(respuesta.text)}

    def extraer(self, conceptos: list[str]) -> dict[str, str]:
        resultado: dict[str, str] = {}
        for i in range(0, len(conceptos), self.lote):
            lote = conceptos[i:i + self.lote]
            for intento in range(self.reintentos):
                try:
                    salida = self._llamar(lote)
                    for c in lote:
                        nombre = salida.get(c)
                        resultado[c] = normalizar_texto(nombre) if nombre else SIN_NOMBRE
                    break
                except Exception:  # noqa: BLE001 - se reintenta y, si falla, queda para revisión
                    if intento == self.reintentos - 1:
                        resultado.update({c: SIN_NOMBRE for c in lote})
                    else:
                        time.sleep(2 ** intento)
        return resultado


def crear_extractor(preferir_ia: bool = True):
    """Usa Gemini si hay API key configurada; si no, el extractor por reglas."""
    if preferir_ia and os.environ.get("GEMINI_API_KEY"):
        try:
            return ExtractorGemini()
        except ImportError:
            pass
    return ExtractorReglas()


def canonicalizar(nombres: pd.Series, umbral: int = 90) -> pd.Series:
    """Unifica variantes del mismo nombre: 'PEREYRA' y 'PEREYRA MARTIN ALEJANDRO'
    quedan como uno solo. Usa similitud de conjuntos de palabras (rapidfuzz)."""
    unicos = sorted((n for n in nombres.dropna().unique() if n != SIN_NOMBRE), key=len)
    mapa: dict[str, str] = {}
    canonicos: list[str] = []
    for n in unicos:
        match = process.extractOne(n, canonicos, scorer=fuzz.token_set_ratio, score_cutoff=umbral)
        if match:
            mapa[n] = match[0]
        else:
            canonicos.append(n)
            mapa[n] = n
    return nombres.map(lambda n: mapa.get(n, n))
