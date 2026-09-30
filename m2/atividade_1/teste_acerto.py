"""
Atividade 1 - teste 1 do slide "Como saber que está certo":

    1. Acerto. Ler a mesma página duas vezes faz uma leitura de disco só.

mais o par fixa/solta e a conta de acertos e faltas.

Rodar:  python atividade_1/teste_acerto.py -v
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from apoio import ArquivoQueFalha, cria_arquivo_de_paginas, cria_tabela_m1  # noqa: E402
from cache import CachePaginas  # noqa: E402
from minidb import ESQUEMA_ALUNO  # noqa: E402
from minidb_cache import varre  # noqa: E402


class TesteAcerto(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.caminho = os.path.join(self.dir.name, "t.db")
        cria_arquivo_de_paginas(self.caminho, 10)
        self.f = open(self.caminho, "r+b")

    def tearDown(self):
        self.f.close()
        self.dir.cleanup()

    def cache(self, capacidade=3, politica="lru"):
        return CachePaginas(self.f, capacidade, politica)

    # ---- o teste 1 do slide ----
    def test_ler_a_mesma_pagina_duas_vezes_faz_uma_leitura_de_disco(self):
        c = self.cache()
        c.fixa(5); c.solta(5)
        c.fixa(5); c.solta(5)
        self.assertEqual(c.leituras_disco, 1)
        self.assertEqual((c.faltas, c.acertos), (1, 1))

    def test_conteudo_vindo_do_cache_e_o_da_pagina_certa(self):
        c = self.cache()
        buf = c.fixa(7)
        self.assertEqual(len(buf), 4096)
        self.assertEqual(bytes(buf), bytes([7]) * 4096)
        c.solta(7)

    # ---- armadilha "Devolver uma cópia" do slide de armadilhas ----
    def test_fixa_devolve_a_mesma_referencia_no_acerto(self):
        c = self.cache()
        a = c.fixa(2)
        b = c.fixa(2)
        self.assertIs(a, b)
        c.solta(2); c.solta(2)

    # ---- contadores (parte "Para saber mais" do slide) ----
    def test_acertos_mais_faltas_e_igual_ao_numero_de_chamadas(self):
        c = self.cache(capacidade=3)
        for n in (0, 1, 2, 0, 1, 3, 4, 0, 0, 9, 1):
            c.fixa(n); c.solta(n)
        self.assertEqual(c.acertos + c.faltas, c.chamadas)
        self.assertEqual(c.chamadas, 11)
        self.assertEqual(c.faltas, c.leituras_disco)  # sem erro: toda falta lê o disco

    # ---- fixa / solta ----
    def test_pins_contam_fixacoes_abertas(self):
        c = self.cache()
        c.fixa(1); c.fixa(1); c.fixa(2)
        self.assertEqual(c.fixadas(), 3)
        c.solta(1); c.solta(1); c.solta(2)
        self.assertEqual(c.fixadas(), 0)

    def test_solta_sem_fixa_e_erro(self):
        c = self.cache()
        with self.assertRaises(ValueError):
            c.solta(4)                      # nem está no cache
        c.fixa(4); c.solta(4)
        with self.assertRaises(ValueError):
            c.solta(4)                      # está, mas já foi solta

    def test_usa_solta_mesmo_quando_o_bloco_estoura(self):
        c = self.cache()
        with self.assertRaises(RuntimeError):
            with c.usa(3):
                raise RuntimeError("erro no meio do uso")
        self.assertEqual(c.fixadas(), 0)

    def test_falha_de_leitura_nao_deixa_pagina_pela_metade(self):
        arq = ArquivoQueFalha(self.f)
        c = CachePaginas(arq, 2)
        arq.falha_leitura = True
        with self.assertRaises(OSError):
            c.fixa(3)
        self.assertNotIn(3, c)
        self.assertEqual(len(c.livres), 2)   # o frame voltou: capacidade intacta
        arq.falha_leitura = False
        c.fixa(3); c.solta(3)                # e o cache segue utilizável
        self.assertIn(3, c)


class TesteVarreduraPeloCache(unittest.TestCase):
    """O par fixa/solta do slide "Fixar e soltar", dentro da varredura do M1."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.caminho = os.path.join(self.dir.name, "aluno.db")
        self.paginas = cria_tabela_m1(self.caminho, 1200)   # 1 + 3 páginas, como no M1
        self.f = open(self.caminho, "r+b")

    def tearDown(self):
        self.f.close()
        self.dir.cleanup()

    def test_varredura_acha_os_1200_registros_e_nao_deixa_pin(self):
        c = CachePaginas(self.f, 3)
        regs = list(varre(c, ESQUEMA_ALUNO))
        self.assertEqual(len(regs), 1200)
        self.assertEqual(regs[0], (1, 20260001))
        self.assertEqual(regs[-1], (1200, 20261200))
        self.assertEqual(self.paginas, 4)
        self.assertEqual(c.fixadas(), 0)

    def test_gerador_abandonado_no_meio_solta_a_pagina(self):
        c = CachePaginas(self.f, 3)
        it = varre(c, ESQUEMA_ALUNO)
        for _ in range(600):                 # passa da 1ª página de dados, para na 2ª
            next(it)
        self.assertEqual(c.fixadas(), 1)     # parado entre o fixa e o solta
        it.close()                           # o finally roda aqui
        self.assertEqual(c.fixadas(), 0)

    def test_segunda_varredura_com_cache_grande_nao_toca_o_disco(self):
        c = CachePaginas(self.f, 8)
        list(varre(c, ESQUEMA_ALUNO))
        antes = c.leituras_disco
        list(varre(c, ESQUEMA_ALUNO))
        self.assertEqual(c.leituras_disco, antes)


if __name__ == "__main__":
    unittest.main()
