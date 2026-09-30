"""
Atividade 3 - e se o cache morrer? Os dados são perdidos?

Mesmo desenho do kill.py do M1: um filho faz o trabalho e se mata com
kill -9 SEM fechar nada; o pai olha o que ficou no arquivo. A diferença é
que agora a memória que morre é o cache de páginas.

  A. altera uma página, não grava nada             -> kill -9
  B. altera uma página, grava_tudo()               -> kill -9
  C. altera uma página, o cache enche e a expulsa  -> kill -9 (sem grava_tudo)
  D. só leituras, nenhuma alteração                -> kill -9
  E. a tabela do M1 (1200 registros) montada pelo cache, sem grava_tudo -> kill -9,
     depois aberta com o código do M1

Rodar:  python atividade_3/morte.py
"""

import hashlib
import os
import signal
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from apoio import cria_arquivo_de_paginas  # noqa: E402
from cache import CachePaginas  # noqa: E402
from minidb import ESQUEMA_ALUNO, inicializa_pagina0, le_cabecalho, le_metadados, varredura  # noqa: E402
from minidb_cache import aloca, insere  # noqa: E402

PAGE = 4096
BYTE = 100
NOVO = 0xEE
PAGINAS = 6


def morre(msg):
    print(f"   [filho pid={os.getpid()}] {msg} -> kill -9", flush=True)
    os.kill(os.getpid(), signal.SIGKILL)   # nunca fecha o arquivo, nunca roda finally


def caso_a(c):
    buf = c.fixa(1); buf[BYTE] = NOVO; c.solta(1, sujo=True)
    morre("página 1 alterada em memória (suja), nada gravado")


def caso_b(c):
    buf = c.fixa(1); buf[BYTE] = NOVO; c.solta(1, sujo=True)
    n = c.grava_tudo()
    morre(f"página 1 alterada e grava_tudo() gravou {n} página")


def caso_c(c):
    buf = c.fixa(1); buf[BYTE] = NOVO; c.solta(1, sujo=True)
    for n in (2, 3, 4):                    # 3 frames: a terceira falta expulsa a 1
        c.fixa(n); c.solta(n)
    morre(f"página 1 alterada, depois 3 leituras forçaram a expulsão dela "
          f"(expulsões sujas: {c.expulsoes_sujas}); sem grava_tudo()")


def caso_d(c):
    for n in (1, 2, 3, 4, 5):
        c.fixa(n); c.solta(n)
    morre("5 leituras, nenhuma alteração")


def executa_filho(caminho, caso):
    f = open(caminho, "r+b")
    c = CachePaginas(f, 3)
    caso(c)


def roda_caso(rotulo, caso, altera=True):
    with tempfile.TemporaryDirectory() as d:
        caminho = os.path.join(d, "t.db")
        cria_arquivo_de_paginas(caminho, PAGINAS)
        antes = hashlib.sha256(open(caminho, "rb").read()).hexdigest()

        print(f"--- {rotulo}")
        pid = os.fork()
        if pid == 0:
            executa_filho(caminho, caso)
            os._exit(0)                    # nunca chega aqui
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL

        with open(caminho, "rb") as f:
            f.seek(1 * PAGE + BYTE)
            valor = f.read(1)[0]
        depois = hashlib.sha256(open(caminho, "rb").read()).hexdigest()
        if not altera:
            print(f"   [pai] página 1 no disco: byte {BYTE} = 0x{valor:02x}  -> nada foi alterado, nada a perder")
        elif valor == NOVO:
            print(f"   [pai] página 1 no disco: byte {BYTE} = 0x{valor:02x}  -> a alteração SOBREVIVEU")
        else:
            print(f"   [pai] página 1 no disco: byte {BYTE} = 0x{valor:02x}  -> a alteração foi PERDIDA")
        print(f"   [pai] arquivo idêntico ao de antes do filho: {antes == depois}\n")


def caso_e():
    """A tabela inteira do M1, montada só pelo cache, sem gravar no fim."""
    with tempfile.TemporaryDirectory() as d:
        caminho = os.path.join(d, "aluno.db")
        with open(caminho, "w+b") as f:
            inicializa_pagina0(f)
        print("--- E. tabela do M1: 1200 registros inseridos pelo cache (3 frames), sem grava_tudo()")
        pid = os.fork()
        if pid == 0:
            f = open(caminho, "r+b")
            c = CachePaginas(f, 3)
            atual = aloca(c, ESQUEMA_ALUNO.tamanho)
            for i in range(1, 1201):
                _, atual = insere(c, ESQUEMA_ALUNO, (i, 20260000 + i), atual)
            s = c.estatisticas()
            morre(f"1200 inserts feitos; o cache gravou {s['escritas_disco']} página(s) por conta própria "
                  f"e {sum(fr.sujo for fr in c.frames)} continuam sujas")
        os.waitpid(pid, 0)

        with open(caminho, "rb") as f:
            _, _, total = le_metadados(f)
            regs, leituras = varredura(f, ESQUEMA_ALUNO)
            tamanho = os.path.getsize(caminho)
        print(f"   [pai] o M1 abre o arquivo: página 0 diz {total} páginas (o certo seriam 4); "
              f"arquivo tem {tamanho // PAGE} páginas")
        with open(caminho, "rb") as f:
            for n in range(1, tamanho // PAGE):
                f.seek(n * PAGE)
                n_slots, _, _ = le_cabecalho(f.read(PAGE))
                print(f"   [pai] página {n} no disco: cabeçalho diz {n_slots} registros")
        print(f"   [pai] varredura do M1 encontrou {len(regs)} registros de 1200 "
              f"({1200 - len(regs)} sumiram)")
        if regs:
            ids = [r[0] for r in regs]
            print(f"   [pai] ids recuperados: {ids[0]}..{ids[-1]}, contíguos: {ids == list(range(1, len(ids) + 1))}")


def main():
    print("Cache com 3 frames. Filho mata a si mesmo; pai confere o arquivo.\n")
    roda_caso("A. suja, sem gravar", caso_a)
    roda_caso("B. suja, com grava_tudo()", caso_b)
    roda_caso("C. suja, mas expulsa antes da morte", caso_c)
    roda_caso("D. só leituras (páginas limpas)", caso_d, altera=False)
    caso_e()


if __name__ == "__main__":
    main()
