"""
Atividade 1 - medição antes e depois (slide "Dez mil registros"): 10 mil registros do M1,
duas varreduras seguidas no mesmo processo. Quantas leituras de disco?

Contagem de leituras: `le_pagina` do minidb_m1 é embrulhada por um contador
(no minidb, no minidb_m1 e no cache), então o número é o de chamadas reais
ao arquivo, incluindo a página 0 de metadados. O slide conta só as 20 páginas
de dados; aqui o total é 21.

Rodar:  python atividade_1/medicao.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from apoio import cria_tabela_m1  # noqa: E402

import cache as mod_cache  # noqa: E402
import minidb  # noqa: E402
import minidb_m1  # noqa: E402
from minidb import ESQUEMA_ALUNO, HEADER_SIZE, PAGE_SIZE, le_cabecalho, le_metadados, varredura  # noqa: E402
from minidb_cache import varre  # noqa: E402

N_REGISTROS = 10_000
NOMES = ("M1 lendo página por registro", "M1 varredura (1 leitura/página)",
         "cache 3 frames", "cache 32 frames")

leituras = 0
_le_original = minidb_m1.le_pagina


def _le_contada(f, n):
    global leituras
    leituras += 1
    return _le_original(f, n)


# todo mundo que chama le_pagina por nome passa a chamar a contada
minidb.le_pagina = _le_contada
minidb_m1.le_pagina = _le_contada
mod_cache.le_pagina = _le_contada


def varredura_ingenua(f, esquema):
    """O que o slide chama de "lê a página de novo a cada registro"."""
    _, _, total = le_metadados(f)
    regs = []
    for n in range(1, total):
        pagina = minidb.le_pagina(f, n)              # a leitura que traz o cabeçalho e o 1º registro
        n_slots, tam, _ = le_cabecalho(pagina)
        for slot in range(n_slots):
            if slot > 0:
                pagina = minidb.le_pagina(f, n)      # releitura a cada registro seguinte
            off = HEADER_SIZE + slot * tam
            regs.append(esquema.desserializa(pagina[off:off + tam]))
    return regs


def soma_ids(regs):
    return sum(r[0] for r in regs)


def uma_varredura(rodar):
    global leituras
    leituras = 0
    t = time.perf_counter()
    regs = rodar()
    dt = time.perf_counter() - t
    return len(regs), soma_ids(regs), leituras, dt


def main():
    with tempfile.TemporaryDirectory() as d:
        caminho = os.path.join(d, "aluno.db")
        paginas = cria_tabela_m1(caminho, N_REGISTROS)
        print(f"tabela: {N_REGISTROS} registros em {paginas - 1} páginas de dados "
              f"(+ página 0) = {paginas} páginas de {PAGE_SIZE} bytes\n")

        linhas = []
        with open(caminho, "r+b") as f:
            linhas.append((NOMES[0], [uma_varredura(lambda: varredura_ingenua(f, ESQUEMA_ALUNO)) for _ in range(2)]))
            linhas.append((NOMES[1], [uma_varredura(lambda: varredura(f, ESQUEMA_ALUNO)[0]) for _ in range(2)]))
            for nome, cap in ((NOMES[2], 3), (NOMES[3], 32)):
                c = mod_cache.CachePaginas(f, cap)
                linhas.append((nome, [uma_varredura(lambda: list(varre(c, ESQUEMA_ALUNO))) for _ in range(2)]))
                assert c.fixadas() == 0
                assert c.acertos + c.faltas == c.chamadas

        print(f"{'configuração':34} {'varredura':>9} {'registros':>9} {'leituras de disco':>18} {'tempo':>9}")
        print("-" * 84)
        for nome, varr in linhas:
            for i, (n, soma, lei, dt) in enumerate(varr, 1):
                print(f"{nome if i == 1 else '':34} {i:>9} {n:>9} {lei:>18} {dt * 1000:>7.1f}ms")
        somas = {v[1] for _, varr in linhas for v in varr}
        print(f"\nmesma resposta em todas as configurações (soma dos ids): {somas}")

        ing = linhas[0][1][0][2]
        m1 = linhas[1][1][0][2]
        print(f"\nleituras por registro / leituras por página: {ing} / {m1} = {ing / m1:.0f}x")

        print("\nA mesma contagem, com as latências do slide da tabela de tempos (100 µs NVMe, 10 ms disco magnético):")
        print(f"{'configuração':34} {'2 varreduras':>13} {'em NVMe':>10} {'em disco magn.':>15}")
        for nome, varr in linhas:
            total = sum(v[2] for v in varr)
            print(f"{nome:34} {total:>13} {total * 100e-6:>9.3f}s {total * 10e-3:>14.1f}s")
        print("\n(o tempo medido acima é do cache do sistema operacional, não do disco;"
              " a coluna confiável é a contagem de leituras)")


if __name__ == "__main__":
    main()
