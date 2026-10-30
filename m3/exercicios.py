"""
Exercícios 1 e 2 do M3, rodados na árvore B+ de verdade (btree.py) com no
máximo 3 chaves por nó. Mostra a árvore depois de cada inserção que dividiu
algum nó, e responde as perguntas medindo.

Rodar:  python exercicios.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from btree import ArvoreBMais  # noqa: E402
from cache import CachePaginas  # noqa: E402
from minidb import inicializa_pagina0  # noqa: E402


def n_nos(arv):
    return sum(len(nivel) for nivel in arv.niveis())


def insere_mostrando(arv, chaves):
    """Insere uma a uma e desenha a árvore. Uma divisão cria um nó novo; a raiz
    nova (quando a árvore cresce) é só o nó extra da última divisão, não outra."""
    for k in chaves:
        nos, altura = n_nos(arv), arv.altura()
        arv.insere(k, (1, k))
        novos = n_nos(arv) - nos
        cresceu = arv.altura() > altura
        divisoes = novos - (1 if cresceu else 0)
        if divisoes == 0:
            print(f"\ninsere {k}: cabe, sem divisão")
        else:
            print(f"\ninsere {k}: {divisoes} divisão(ões)" +
                  ("; a última chegou à raiz e a árvore ganhou um nível" if cresceu else ""))
        print(arv.desenha())


def main():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "ex.db"), "w+b") as f:
            inicializa_pagina0(f)
            cache = CachePaginas(f, 3)
            arv = ArvoreBMais.cria(cache, max_chaves=3)

            print("=" * 70)
            print("EXERCÍCIO 1: 10, 20, 5, 30, 25, 40, 15   (máx. 3 chaves por nó)")
            print("=" * 70)
            insere_mostrando(arv, [10, 20, 5, 30, 25, 40, 15])
            print(f"\nAltura ao fim: {arv.altura()}")
            cache.zera_contadores()
            arv.busca(25)
            print(f"Páginas lidas pela busca por 25: {cache.chamadas} (raiz + folha [20 25])")

            print()
            print("=" * 70)
            print("EXERCÍCIO 2: a partir dela, 35, 45, 50, 55")
            print("=" * 70)
            insere_mostrando(arv, [35, 45, 50, 55])
            print(f"\nAltura ao fim: {arv.altura()}")
            cache.zera_contadores()
            achadas = [k for k, _ in arv.faixa(12, 33)]
            print(f"WHERE id BETWEEN 12 AND 33 devolve {achadas} e lê {cache.chamadas} páginas")
            print("  raiz [40] -> nó interno [20 30] -> folhas [5 10 15], [20 25], [30 35]")
            arv.confere()
            print("\nInvariantes conferidas (folhas na mesma profundidade, ordem, encadeamento).")


if __name__ == "__main__":
    main()
