"""
Atividade 2 - o que a política de expulsão e a capacidade mudam de verdade.

Usa o CachePaginas real sobre um arquivo real de 21 páginas (o tamanho da
tabela de 10 mil registros: página 0 + 20 de dados), e conta acertos.

  A. o trace do slide "Quando o cache enche" (1, 2, 3, 1, 4, 1) em FIFO e LRU
  B. carga com páginas quentes (80% dos acessos em 5 páginas)
  C. varredura repetida da tabela inteira, capacidade de 1 a 24 frames
  D. páginas quentes + uma varredura completa de vez em quando

Rodar:  python atividade_2/comparacao.py
"""

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from apoio import cria_arquivo_de_paginas  # noqa: E402
from cache import CachePaginas  # noqa: E402

PAGINAS = 21


def roda(f, trace, capacidade, politica):
    c = CachePaginas(f, capacidade, politica)
    for n in trace:
        c.fixa(n)
        c.solta(n)
    return c


def taxa(c):
    return 100.0 * c.acertos / c.chamadas


def carga_quente(rng, n, quentes=5, p_quente=0.8):
    return [rng.randrange(quentes) if rng.random() < p_quente else rng.randrange(PAGINAS)
            for _ in range(n)]


def barra(pct, largura=30):
    return "█" * round(pct / 100 * largura)


def main():
    with tempfile.TemporaryDirectory() as d:
        caminho = os.path.join(d, "t.db")
        cria_arquivo_de_paginas(caminho, PAGINAS)
        with open(caminho, "r+b") as f:

            print("A. trace do slide 'Quando o cache enche': 3 frames, acessos 1, 2, 3, 1, 4, 1")
            for pol in ("fifo", "lru"):
                c = roda(f, [1, 2, 3, 1, 4, 1], 3, pol)
                print(f"   {pol.upper():4}  acertos={c.acertos} faltas={c.faltas} "
                      f"leituras de disco={c.leituras_disco}  no cache no fim: {c.residentes()}")

            print("\nB. carga com páginas quentes: 20000 acessos, 80% em 5 páginas, 21 no total")
            print(f"   {'frames':>6} {'FIFO':>8} {'LRU':>8}")
            rng = random.Random(7)
            trace = carga_quente(rng, 20000)
            for cap in (3, 4, 6, 8, 12, 21):
                a, b = (taxa(roda(f, trace, cap, p)) for p in ("fifo", "lru"))
                print(f"   {cap:>6} {a:>7.1f}% {b:>7.1f}%")

            print("\nC. varredura completa da tabela (21 páginas) repetida 10 vezes, LRU")
            print(f"   {'frames':>6} {'acertos':>8}  ")
            trace = list(range(PAGINAS)) * 10
            for cap in list(range(1, 25)):
                c = roda(f, trace, cap, "lru")
                print(f"   {cap:>6} {taxa(c):>7.1f}%  {barra(taxa(c))}")

            print("\nD. as mesmas páginas quentes, agora com uma varredura completa a cada 400 acessos")
            rng = random.Random(7)
            quente = carga_quente(rng, 20000)
            mista = []
            for i, n in enumerate(quente):
                mista.append(n)
                if i % 400 == 399:
                    mista.extend(range(PAGINAS))
            print(f"   {'frames':>6} {'só quentes':>11} {'quentes+varredura':>18}")
            for cap in (4, 8, 12, 16):
                a = taxa(roda(f, quente, cap, "lru"))
                b = taxa(roda(f, mista, cap, "lru"))
                print(f"   {cap:>6} {a:>10.1f}% {b:>17.1f}%")


if __name__ == "__main__":
    main()
