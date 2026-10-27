"""Gráfico de cascada: cuánto aporta cada nivel del motor."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

AZUL = "#2a78d6"
GRIS_PEND = "#c3c2b7"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
GRILLA = "#e4e3df"
FONDO = "#fcfcfb"


def _pct(x: float) -> str:
    return f"{x:.1f}%".replace(".", ",")


def grafico_cascada(movimientos: pd.DataFrame, ruta: str | Path | None = None):
    total = len(movimientos)
    por_nivel = movimientos[movimientos["conciliado"]].groupby("nivel").size().sort_index()
    pendientes = total - por_nivel.sum()

    etiquetas = [n.split(" · ")[1] for n in por_nivel.index] + ["Pendientes\n(revisión humana)"]
    etiquetas = [e.replace(" (IA)", "\n(IA)").replace(" por fecha", "\npor fecha")
                 .replace("Cuenta contable", "Por cuenta\ncontable").replace("Diferencia aislada", "Diferencia\naislada")
                 for e in etiquetas]
    aportes = [v / total * 100 for v in por_nivel] + [pendientes / total * 100]

    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=200)
    fig.patch.set_facecolor(FONDO)
    ax.set_facecolor(FONDO)

    base = 0.0
    for i, (etq, valor) in enumerate(zip(etiquetas, aportes)):
        es_pend = i == len(aportes) - 1
        ax.bar(i, valor, bottom=base, width=0.62, color=GRIS_PEND if es_pend else AZUL,
               edgecolor=FONDO, linewidth=2)
        ax.text(i, base + valor + 1.2, ("" if es_pend else "+") + _pct(valor),
                ha="center", va="bottom", fontsize=9, color=TINTA)
        if not es_pend and i < len(aportes) - 1:
            ax.plot([i + 0.31, i + 0.69], [base + valor] * 2, color=TINTA_2, linewidth=0.8, linestyle=":")
        base += valor

    auto = 100 - aportes[-1]
    ax.set_title(f"El motor concilia el {_pct(auto)} de los movimientos sin intervención humana",
                 loc="left", fontsize=12, color=TINTA, pad=24, fontweight="bold")
    ax.text(0, 1.02, f"Aporte de cada nivel de la cascada, % de {total} movimientos (datos sintéticos, marzo 2026)",
            transform=ax.transAxes, fontsize=9, color=TINTA_2)
    ax.set_xticks(range(len(etiquetas)), etiquetas, fontsize=9, color=TINTA_2)
    ax.set_ylim(0, 112)
    ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"], fontsize=9, color=TINTA_2)
    ax.yaxis.grid(True, color=GRILLA, linewidth=0.8)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(GRILLA)
    ax.tick_params(length=0)
    fig.tight_layout()
    if ruta:
        fig.savefig(ruta, facecolor=FONDO, bbox_inches="tight")
    return fig
