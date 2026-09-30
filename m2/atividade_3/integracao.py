"""
Atividade 3 - integração com o M1 e medição antes/depois, agora para ESCRITA.

Insere N registros do esquema `aluno`:
  antes  - insere() do M1: cada registro lê a página e reescreve a página
           inteira, com fsync (o escreve_pagina do M1 sempre faz fsync)
  depois - insere() pelo cache: altera o buffer, marca suja; o disco só é
           tocado na expulsão e no grava_tudo() final

Contagem: escreve_pagina e le_pagina são embrulhadas por contadores.

Rodar:  python atividade_3/integracao.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import cache as mod_cache  # noqa: E402
import minidb  # noqa: E402
import minidb_m1  # noqa: E402
from minidb import ESQUEMA_ALUNO, aloca as aloca_m1, inicializa_pagina0, insere as insere_m1, varredura  # noqa: E402
from minidb_cache import aloca, insere  # noqa: E402

leituras = escritas = 0
_le, _escreve = minidb_m1.le_pagina, minidb_m1.escreve_pagina


def le_contada(f, n):
    global leituras
    leituras += 1
    return _le(f, n)


def escreve_contada(f, n, dados):
    global escritas
    escritas += 1
    return _escreve(f, n, dados)


for m in (minidb, minidb_m1, mod_cache):
    m.le_pagina = le_contada
    m.escreve_pagina = escreve_contada


def zera():
    global leituras, escritas
    leituras = escritas = 0


def sem_cache(caminho, n):
    zera()
    t = time.perf_counter()
    with open(caminho, "w+b") as f:
        inicializa_pagina0(f)
        atual = aloca_m1(f, ESQUEMA_ALUNO.tamanho)
        for i in range(1, n + 1):
            _, atual = insere_m1(f, ESQUEMA_ALUNO, (i, 20260000 + i), atual)
    return leituras, escritas, time.perf_counter() - t


def com_cache(caminho, n, capacidade):
    zera()
    t = time.perf_counter()
    with open(caminho, "w+b") as f:
        inicializa_pagina0(f)
        c = mod_cache.CachePaginas(f, capacidade)
        atual = aloca(c, ESQUEMA_ALUNO.tamanho)
        for i in range(1, n + 1):
            _, atual = insere(c, ESQUEMA_ALUNO, (i, 20260000 + i), atual)
        antes_do_flush = c.escritas_disco
        c.grava_tudo()
        assert c.fixadas() == 0 and c.acertos + c.faltas == c.chamadas
    return leituras, escritas, time.perf_counter() - t, antes_do_flush, c


def confere(caminho, n):
    with open(caminho, "rb") as f:
        regs, _ = varredura(f, ESQUEMA_ALUNO)
    assert len(regs) == n and regs[0] == (1, 20260001) and regs[-1] == (n, 20260000 + n), "tabela diferente!"


def main():
    with tempfile.TemporaryDirectory() as d:
        for n in (1200, 10000):
            print(f"=== {n} inserts ===")
            print(f"{'configuração':22} {'leituras':>9} {'escritas':>9} {'tempo':>9}   observação")
            print("-" * 86)

            p1 = os.path.join(d, "m1.db")
            lei, esc, dt = sem_cache(p1, n)
            confere(p1, n)
            print(f"{'M1 (sem cache)':22} {lei:>9} {esc:>9} {dt * 1000:>7.0f}ms   toda escrita com fsync")

            for cap in (3, 32):
                p2 = os.path.join(d, f"c{cap}.db")
                lei, esc, dt, antes, c = com_cache(p2, n, cap)
                confere(p2, n)
                assert open(p1, "rb").read() == open(p2, "rb").read(), "arquivos diferentes byte a byte!"
                obs = f"{antes} por expulsão + {c.escritas_disco - antes} no grava_tudo (+1 do bootstrap da pág. 0)"
                print(f"{f'cache {cap} frames':22} {lei:>9} {esc:>9} {dt * 1000:>7.0f}ms   {obs}")
            print("   (arquivo do M1 e os dois do cache são idênticos byte a byte)\n")


if __name__ == "__main__":
    main()
