"""
Atividade 3 - teste 3 do slide "Como saber que está certo":

    3. Suja. Alterar, expulsar, reabrir em outro processo: a alteração está lá.

mais o controle negativo (sem expulsão e sem gravação, o outro processo NÃO
vê a alteração), a gravação que falha, e a compatibilidade com o M1.

"Outro processo" é um `python -c` de verdade (subprocess), que lê o arquivo
direto do disco, sem passar por cache nenhum.

Rodar:  python atividade_3/teste_suja.py -v
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from apoio import ArquivoQueFalha, cria_arquivo_de_paginas  # noqa: E402
from cache import CachePaginas  # noqa: E402
from minidb import ESQUEMA_ALUNO, inicializa_pagina0, le_metadados, varredura  # noqa: E402
from minidb_cache import aloca, insere  # noqa: E402

PAGE = 4096
BYTE = 100          # posição alterada dentro da página
NOVO = 0xEE


def le_de_outro_processo(caminho, pagina):
    """Lê o byte alterado com um interpretador novo, direto do arquivo."""
    codigo = (
        "import sys; f = open(sys.argv[1], 'rb'); f.seek(int(sys.argv[2]) * 4096 + int(sys.argv[3]));"
        "print(f.read(1)[0])"
    )
    saida = subprocess.run([sys.executable, "-c", codigo, caminho, str(pagina), str(BYTE)],
                           capture_output=True, text=True, check=True)
    return int(saida.stdout)


class TesteSuja(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.caminho = os.path.join(self.dir.name, "t.db")
        cria_arquivo_de_paginas(self.caminho, 10)     # página k = byte k
        self.f = open(self.caminho, "r+b")

    def tearDown(self):
        self.f.close()
        self.dir.cleanup()

    def altera(self, c, n, sujo=True):
        buf = c.fixa(n)
        buf[BYTE] = NOVO
        c.solta(n, sujo=sujo)

    def toca(self, c, *paginas):
        for n in paginas:
            c.fixa(n)
            c.solta(n)

    # ---- o teste 3 do slide ----
    def test_alterar_expulsar_reabrir_em_outro_processo(self):
        c = CachePaginas(self.f, 3)
        self.altera(c, 1)
        self.toca(c, 2, 3, 4)                         # 3 páginas novas: a 1 é expulsa
        self.assertNotIn(1, c)
        self.assertEqual(c.expulsoes_sujas, 1)
        self.assertEqual(le_de_outro_processo(self.caminho, 1), NOVO)

    def test_controle_negativo_sem_expulsao_o_disco_nao_sabe_de_nada(self):
        c = CachePaginas(self.f, 3)
        self.altera(c, 1)
        self.assertTrue(c.suja(1))
        self.assertEqual(c.escritas_disco, 0)
        self.assertEqual(le_de_outro_processo(self.caminho, 1), 1)   # ainda o valor antigo
        # ...mas quem lê pelo cache enxerga a alteração
        self.assertEqual(c.fixa(1)[BYTE], NOVO)
        c.solta(1)

    def test_grava_tudo_leva_as_sujas_ao_disco_e_limpa_o_bit(self):
        c = CachePaginas(self.f, 4)
        self.altera(c, 1)
        self.altera(c, 2)
        self.toca(c, 3)                               # limpa: não deve ser gravada
        self.assertEqual(c.grava_tudo(), 2)
        self.assertEqual(c.escritas_disco, 2)
        self.assertFalse(c.suja(1) or c.suja(2))
        self.assertEqual(c.grava_tudo(), 0)           # segunda vez: nada a fazer
        self.assertEqual(le_de_outro_processo(self.caminho, 1), NOVO)
        self.assertEqual(le_de_outro_processo(self.caminho, 2), NOVO)
        self.assertEqual(le_de_outro_processo(self.caminho, 3), 3)

    # ---- quem paga a gravação ----
    def test_expulsar_pagina_limpa_nao_escreve(self):
        c = CachePaginas(self.f, 2)
        self.toca(c, 1, 2, 3, 4)
        self.assertEqual(c.expulsoes, 2)
        self.assertEqual(c.escritas_disco, 0)

    def test_varias_alteracoes_na_mesma_pagina_viram_uma_gravacao(self):
        c = CachePaginas(self.f, 2)
        for _ in range(500):
            self.altera(c, 1)
        self.assertEqual(c.escritas_disco, 0)         # no-force: nada foi ao disco ainda
        self.toca(c, 2, 3)
        self.assertEqual(c.escritas_disco, 1)         # 500 alterações, 1 gravação

    def test_bit_de_sujeira_so_sobe_ate_gravar(self):
        c = CachePaginas(self.f, 3)
        self.altera(c, 1, sujo=True)
        c.fixa(1); c.solta(1, sujo=False)             # uma leitura depois não limpa
        self.assertTrue(c.suja(1))

    def test_alterar_sem_avisar_perde_a_alteracao(self):
        """O contrato: quem altera o buffer AVISA em solta(sujo=True).
        Sem aviso, a expulsão joga fora o que foi mudado."""
        c = CachePaginas(self.f, 2)
        self.altera(c, 1, sujo=False)
        self.toca(c, 2, 3)
        self.assertEqual(c.escritas_disco, 0)
        self.assertEqual(le_de_outro_processo(self.caminho, 1), 1)

    def test_usa_escreve_true_marca_suja(self):
        c = CachePaginas(self.f, 2)
        with c.usa(1, escreve=True) as buf:
            buf[BYTE] = NOVO
        self.assertTrue(c.suja(1))

    # ---- armadilha "Expulsar suja sem gravar" do slide de armadilhas ----
    def test_se_a_gravacao_na_expulsao_falha_a_pagina_suja_continua_no_cache(self):
        arq = ArquivoQueFalha(self.f)
        c = CachePaginas(arq, 2)
        self.altera(c, 1)
        self.toca(c, 2)
        arq.falha_escrita = True
        with self.assertRaises(OSError):
            c.fixa(3)                                 # tentaria expulsar a 1 (suja)
        self.assertIn(1, c)                           # não sumiu
        self.assertTrue(c.suja(1))
        self.assertEqual(c.fixa(1)[BYTE], NOVO)       # e o conteúdo está intacto
        c.solta(1)
        arq.falha_escrita = False
        self.toca(c, 3, 4)                            # o disco voltou; a 1 foi tocada acima, então
                                                      # a 3 expulsa a 2 (limpa) e a 4 expulsa a 1 (suja)
        self.assertEqual(le_de_outro_processo(self.caminho, 1), NOVO)


class TesteIntegracaoComM1(unittest.TestCase):
    """Tabela feita 100% através do cache (páginas sujas, sem nenhum
    escreve_pagina direto) e depois aberta pelo código do M1."""

    def test_1200_registros_pelo_cache_abrem_no_m1(self):
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "aluno.db")
            with open(caminho, "w+b") as f:
                inicializa_pagina0(f)                 # o bootstrap ainda é do M1
                c = CachePaginas(f, 3)
                atual = aloca(c, ESQUEMA_ALUNO.tamanho)
                for i in range(1, 1201):
                    _, atual = insere(c, ESQUEMA_ALUNO, (i, 20260000 + i), atual)
                self.assertEqual(c.fixadas(), 0)
                c.grava_tudo()
            with open(caminho, "rb") as f:            # agora sem cache: o M1 puro
                _, _, total = le_metadados(f)
                regs, leituras = varredura(f, ESQUEMA_ALUNO)
            self.assertEqual(total, 4)
            self.assertEqual(leituras, 3)
            self.assertEqual(len(regs), 1200)
            self.assertEqual(regs[0], (1, 20260001))
            self.assertEqual(regs[-1], (1200, 20261200))


if __name__ == "__main__":
    unittest.main()
