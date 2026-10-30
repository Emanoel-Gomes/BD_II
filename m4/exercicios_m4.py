"""
Exercícios 1 e 2 do M4, rodados no tokenizador, no parser e no executor de
verdade (e não só no papel). Mostra, para cada pergunta, o que o código responde.

Rodar:  python exercicios_m4.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cache import CachePaginas  # noqa: E402
from catalogo import Catalogo  # noqa: E402
from erros import ErroSQL  # noqa: E402
from executor import executa  # noqa: E402
from minidb import inicializa_pagina0  # noqa: E402
from sql import analisa, tokeniza  # noqa: E402


def mostra_tokens(tokens):
    for tipo, valor in tokens:
        print(f"    {tipo:<8} {valor!r}")


def etapa_do_erro(sql):
    """Roda só as etapas 1 e 2 e diz onde parou (a 3 só com o catálogo, adiante)."""
    try:
        tokens = tokeniza(sql)
    except ErroSQL as e:
        return f"etapa 1, ERRO {e.etapa}: {e}"
    try:
        analisa(sql)
    except ErroSQL as e:
        return f"etapa 2, ERRO {e.etapa}: {e}   ({len(tokens)} tokens passaram na etapa 1)"
    return "passou nas etapas 1 e 2"


def main():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "t.db"), "w+b") as f:
            inicializa_pagina0(f)
            cache = CachePaginas(f, 8)
            cat = Catalogo(cache)
            executa("CREATE TABLE aluno (id INT, matricula INT, nome CHAR(20))", cat, cache)
            executa("INSERT INTO aluno VALUES (1, 20260001, 'Ana')", cat, cache)

            print("=" * 70)
            print("EXERCÍCIO 1:  INSERT INTO aluno VALUES (3, 20260003, 'Carla');")
            print("=" * 70)
            sql = "INSERT INTO aluno VALUES (3, 20260003, 'Carla');"
            print("\n1. Os tokens:")
            mostra_tokens(tokeniza(sql))
            print("\n2. A árvore que o parser monta:")
            print(f"    {analisa(sql)}")
            print("    INSERT, INTO, VALUES, os parênteses, as vírgulas e o ; somem: serviram")
            print("    para o parser decidir, e acabou.")
            sem_aspas = "INSERT INTO aluno VALUES (3, 20260003, Carla);"
            print("\n3. Sem as aspas de Carla:")
            print(f"    {sem_aspas}")
            print("    tokens que mudam: ('TEXTO', 'Carla') vira ('NOME', 'Carla')")
            print(f"    tokenizador: passa ({len(tokeniza(sem_aspas))} tokens, nenhum erro)")
            print(f"    {etapa_do_erro(sem_aspas)}")
            print("    O erro só aparece no parser: ele sabe que depois de VALUES ( vem valor,")
            print("    e um NOME não é valor. No minidb 0.0 tudo era texto, e por isso nada")
            print("    era errado: Carla sem aspas funcionava porque não havia o que conferir.")

            print()
            print("=" * 70)
            print("EXERCÍCIO 2, item 1: em que etapa cada um falha")
            print("=" * 70)
            casos = [
                "SELECT nome FROM aluno WHERE id == 42",
                "SELECT * FROM WHERE id = 42",
                "SELECT idade FROM aluno",
                "SELECT * FROM aluno WHERE nome = 'O'Brien'",
            ]
            for sql in casos:
                print(f"\n  {sql}")
                r = etapa_do_erro(sql)
                if r.startswith("passou"):          # só a etapa 3 (catálogo) enxerga o erro
                    print(f"    {r}")
                    print(f"    etapa 3 (catálogo): {executa(sql, cat, cache)}")
                else:
                    print(f"    {r}")

            print()
            print("=" * 70)
            print("EXERCÍCIO 2, item 2: injeção")
            print("=" * 70)
            nome = "x' OR '1'='1"
            consulta = "SELECT * FROM aluno WHERE nome = '" + nome + "'"
            print(f"\n  nome = {nome}")
            print(f"  texto montado por concatenação:\n    {consulta}")
            print("\n  Tokens:")
            mostra_tokens(tokeniza(consulta))
            print(f"\n  O minidb responde:\n    {executa(consulta, cat, cache)}")
            print("\n  O texto do usuário virou gramática: a aspa dele fechou o texto 'x' e o OR")
            print("  é um token de fora de qualquer texto. O ataque só falhou porque a")
            print("  gramática do minidb não tem OR. Isso não é proteção, é falta de alvo.")

            print("\n  Mesma técnica num INSERT, que a gramática aceita:")
            executa("CREATE TABLE quatro (id INT, a CHAR(10), b CHAR(10), c CHAR(10))", cat, cache)
            nome = "Zé', 'extra"
            insercao = "INSERT INTO quatro VALUES (1, 'a', '" + nome + "')"
            print(f"    nome = {nome}")
            print(f"    {insercao}")
            print(f"    -> {executa(insercao, cat, cache)}")
            print(f"    SELECT * FROM quatro -> {executa('SELECT * FROM quatro', cat, cache)!r}")
            print("  O usuário gravou um valor que o programa nunca previu. Aqui nem o")
            print("  parser nem o catálogo se queixaram: 4 valores para 4 colunas.")
            cache.grava_tudo()


if __name__ == "__main__":
    main()
