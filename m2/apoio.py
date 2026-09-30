"""apoio.py - utilidades dos testes e das demos do M2 (não faz parte do cache)."""

import os
import sys

# permite `python atividade_N/teste_x.py` de qualquer diretório
RAIZ = os.path.dirname(os.path.abspath(__file__))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from minidb import ESQUEMA_ALUNO, aloca, inicializa_pagina0, insere  # noqa: E402
from minidb_m1 import PAGE_SIZE  # noqa: E402


def cria_arquivo_de_paginas(caminho, n_paginas):
    """Arquivo cuja página k é toda feita do byte k (k < 256): dá para
    saber de qual página um buffer veio só olhando o primeiro byte."""
    with open(caminho, "wb") as f:
        for k in range(n_paginas):
            f.write(bytes([k % 256]) * PAGE_SIZE)


def cria_tabela_m1(caminho, n_registros):
    """Tabela `aluno` feita pelo código do M1 (insere direto no arquivo,
    sem cache). Devolve o total de páginas do arquivo."""
    with open(caminho, "w+b") as f:
        inicializa_pagina0(f)
        atual = aloca(f, ESQUEMA_ALUNO.tamanho)
        for i in range(1, n_registros + 1):
            _, atual = insere(f, ESQUEMA_ALUNO, (i, 20260000 + i), atual)
    return os.path.getsize(caminho) // PAGE_SIZE


class ArquivoQueFalha:
    """Embrulha um arquivo aberto e falha sob comando, para exercitar os
    caminhos de erro do cache (leitura e escrita que dão OSError)."""

    def __init__(self, f):
        self._f = f
        self.falha_leitura = False
        self.falha_escrita = False

    def read(self, *a):
        if self.falha_leitura:
            raise OSError("leitura falhou (simulada)")
        return self._f.read(*a)

    def write(self, *a):
        if self.falha_escrita:
            raise OSError("escrita falhou (simulada)")
        return self._f.write(*a)

    def __getattr__(self, nome):   # seek, tell, flush, fileno, name...
        return getattr(self._f, nome)
