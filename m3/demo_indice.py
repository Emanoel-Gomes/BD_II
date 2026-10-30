"""
M3 - demo: quantas páginas lê achar um registro, com e sem índice.

Parte 1: a tabela `aluno` do M1 com N registros. Mede, com cache FRIO
(só a leitura do disco conta), WHERE id = X e WHERE id BETWEEN A AND B:

    sem índice   varre()           lê a tabela inteira, página por página
    com índice   busca_registro()  desce a árvore e lê UMA página da tabela

Parte 2: a altura do índice conforme a tabela cresce, com o tamanho de nó
de verdade (408 chaves por folha, 510 por nó interno), só a árvore.

Rodar:  python demo_indice.py [N]        (padrão 10000)
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apoio import cria_tabela_m1  # noqa: E402
from btree import ArvoreBMais, CAP_FOLHA, CAP_INTERNO  # noqa: E402
from cache import CachePaginas  # noqa: E402
from minidb import ESQUEMA_ALUNO, PAGE_SIZE, inicializa_pagina0  # noqa: E402
from minidb_cache import varre  # noqa: E402
from minidb_indice import busca_registro, faixa_registros, indexa_tabela  # noqa: E402


def mede(cache, funcao):
    """Roda `funcao` e devolve (resultado, páginas pedidas ao cache, leituras de disco)."""
    cache.zera_contadores()
    r = funcao()
    if hasattr(r, "__next__"):
        r = list(r)
    return r, cache.chamadas, cache.leituras_disco


def parte1(n):
    with tempfile.TemporaryDirectory() as d:
        sem = os.path.join(d, "sem_indice.db")
        com = os.path.join(d, "com_indice.db")
        cria_tabela_m1(sem, n)                         # feita pelo M1, sem cache nem índice
        cria_tabela_m1(com, n)
        with open(com, "r+b") as f:                    # o mesmo arquivo, agora com índice
            c = CachePaginas(f, 32)
            arv = ArvoreBMais.cria(c)
            t0 = time.perf_counter()
            indexados = indexa_tabela(c, ESQUEMA_ALUNO, arv)
            c.grava_tudo()
            t_indexa = time.perf_counter() - t0
        tab = os.path.getsize(sem) // PAGE_SIZE
        tot = os.path.getsize(com) // PAGE_SIZE

        print(f"Tabela aluno com {n} registros: {tab} páginas (a 0 é metadado)")
        print(f"Índice construído em {t_indexa:.2f}s sobre {indexados} registros; "
              f"o arquivo foi de {tab} para {tot} páginas ({tot - tab} de índice)")
        print()

        alvo = n * 3 // 4
        a, b = n // 2, n // 2 + 99
        print(f"{'consulta':36s} {'pedidas ao cache':>17s} {'leituras de disco':>18s}")

        def linha(rotulo, ch, le, resultado):
            print(f"{rotulo:36s} {ch:17d} {le:18d}   -> {resultado}")

        # cada medida abre o arquivo com um cache NOVO: frio, nada sobrou da anterior
        with open(sem, "r+b") as f:
            c = CachePaginas(f, 32)
            regs, ch, le = mede(c, lambda: list(varre(c, ESQUEMA_ALUNO)))
            linha(f"sem índice  id = {alvo}", ch, le, [r for r in regs if r[0] == alvo][0])
        with open(sem, "r+b") as f:
            c = CachePaginas(f, 32)
            regs, ch, le = mede(c, lambda: [r for r in varre(c, ESQUEMA_ALUNO) if a <= r[0] <= b])
            linha(f"sem índice  id entre {a} e {b}", ch, le, f"{len(regs)} registros")
        with open(com, "r+b") as f:
            c = CachePaginas(f, 32)
            arv = ArvoreBMais.abre(c)                  # só lê a página 0
            reg, ch, le = mede(c, lambda: busca_registro(c, ESQUEMA_ALUNO, arv, alvo))
            linha(f"com índice  id = {alvo}", ch, le, reg)
            altura = arv.altura()
        with open(com, "r+b") as f:
            c = CachePaginas(f, 32)
            arv = ArvoreBMais.abre(c)
            regs, ch, le = mede(c, lambda: faixa_registros(c, ESQUEMA_ALUNO, arv, a, b))
            linha(f"com índice  id entre {a} e {b}", ch, le, f"{len(regs)} registros")
        with open(com, "r+b") as f:
            c = CachePaginas(f, 32)
            arv = ArvoreBMais.abre(c)
            _, ch, le = mede(c, lambda: busca_registro(c, ESQUEMA_ALUNO, arv, n + 1))
            linha(f"com índice  id = {n + 1} (não existe)", ch, le, None)
        print()
        print(f"Altura do índice: {altura}. Achar um registro = {altura} páginas do índice + 1 da tabela.")
        print("Na faixa, cada registro pede a sua página ao cache de novo (as 100 pedidas), mas é")
        print("tudo a mesma página de dados: o que vai ao disco são 'leituras de disco'.")
        print("'Sem índice' foi medida na tabela do M1 sem índice (a varredura num arquivo COM")
        print("índice também fixa as páginas dele, só para pulá-las).")


def parte2():
    print()
    print(f"Altura do índice (nó de página inteira: {CAP_FOLHA} chaves na folha, {CAP_INTERNO} no nó interno)")
    print(f"{'chaves':>10s} {'folhas':>8s} {'nós internos':>13s} {'altura':>7s} {'tempo':>8s}")
    with tempfile.TemporaryDirectory() as d:
        for n in (400, 5_000, 100_000, 120_000):
            p = os.path.join(d, f"i{n}.db")
            with open(p, "w+b") as f:
                inicializa_pagina0(f)
                c = CachePaginas(f, 4096)               # grande: aqui o que se mede é a forma da árvore
                arv = ArvoreBMais.cria(c)
                t0 = time.perf_counter()
                for k in range(1, n + 1):               # em ordem: o pior caso de ocupação (folhas pela metade)
                    arv.insere(k, (k // 500 + 1, k % 500))
                dt = time.perf_counter() - t0
                folhas = sum(1 for _ in arv.folhas())
                internos = sum(len(nivel) for nivel in arv.niveis()[:-1])
                print(f"{n:10d} {folhas:8d} {internos:13d} {arv.altura():7d} {dt:7.1f}s")
    print()
    print("Em ordem crescente cada folha divide ao meio e fica com ~204 chaves, e cada nó interno")
    print("com ~255 filhos. Conta (estimativa, não medida): 10 milhões de chaves dão ~49 mil folhas e")
    print("~190 nós internos, que cabem numa raiz só: 3 níveis, como no slide.")


if __name__ == "__main__":
    parte1(int(sys.argv[1]) if len(sys.argv) > 1 else 10_000)
    parte2()
