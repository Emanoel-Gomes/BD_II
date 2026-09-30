"""
Atividade 2 - teste 2 do slide "Como saber que está certo":

    2. Expulsão. Com 3 frames, tocar 4 páginas expulsa a menos usada.

mais: página fixada nunca sai, cache todo fixado levanta erro em vez de
expulsar, e LRU conferido contra um modelo de referência.

Rodar:  python atividade_2/teste_expulsao.py -v
"""

import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from apoio import ArquivoQueFalha, cria_arquivo_de_paginas, cria_tabela_m1  # noqa: E402
from cache import CacheCheio, CachePaginas  # noqa: E402
from minidb import ESQUEMA_ALUNO  # noqa: E402
from minidb_cache import varre  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.caminho = os.path.join(self.dir.name, "t.db")
        cria_arquivo_de_paginas(self.caminho, 40)
        self.f = open(self.caminho, "r+b")

    def tearDown(self):
        self.f.close()
        self.dir.cleanup()

    def toca(self, c, *paginas):
        for n in paginas:
            c.fixa(n)
            c.solta(n)


class TesteExpulsao(Base):
    # ---- o teste 2 do slide ----
    def test_4_paginas_em_3_frames_expulsa_a_menos_usada(self):
        c = CachePaginas(self.f, 3)
        self.toca(c, 0, 1, 2)
        self.assertEqual(c.expulsoes, 0)
        self.toca(c, 3)
        self.assertNotIn(0, c)                       # a mais antiga saiu
        self.assertEqual(sorted(c.residentes()), [1, 2, 3])
        self.assertEqual(c.expulsoes, 1)

    def test_trace_do_slide_1_2_3_1_4(self):
        c = CachePaginas(self.f, 3)
        self.toca(c, 1, 2, 3, 1)
        self.assertEqual(c.residentes(), [2, 3, 1])  # o acerto levou a 1 para o fim da fila
        self.toca(c, 4)
        self.assertEqual(c.residentes(), [3, 1, 4])  # saiu a 2, não a 1
        self.assertEqual((c.acertos, c.faltas, c.expulsoes), (1, 4, 1))

    def test_fifo_expulsaria_a_pagina_que_acabou_de_ser_lida(self):
        c = CachePaginas(self.f, 3, politica="fifo")
        self.toca(c, 1, 2, 3, 1, 4)
        self.assertEqual(c.residentes(), [2, 3, 4])  # a 1 saiu, mesmo com o acerto
        self.toca(c, 1)
        self.assertEqual(c.faltas, 5)                # e foi buscada de novo no disco

    def test_capacidade_grande_nunca_expulsa(self):
        c = CachePaginas(self.f, 64)                 # o aviso do slide
        self.toca(c, *range(40), *range(40))
        self.assertEqual(c.expulsoes, 0)

    def test_capacidade_1(self):
        c = CachePaginas(self.f, 1)
        self.toca(c, 5, 5, 6, 5)
        self.assertEqual((c.acertos, c.faltas, c.expulsoes), (1, 3, 2))

    # ---- fixadas ----
    def test_pagina_fixada_nao_sai_mesmo_sendo_a_mais_antiga(self):
        c = CachePaginas(self.f, 3)
        c.fixa(1)                                    # a mais antiga E em uso
        self.toca(c, 2, 3)
        self.toca(c, 4)                              # precisa expulsar: a 1 é pulada
        self.assertIn(1, c)
        self.assertNotIn(2, c)
        c.solta(1)

    def test_cenario_fixar_e_soltar_iterador_parado_e_cache_cheio(self):
        """(slide "Fixar e soltar") A varredura parada entre fixa e solta; outra consulta pede uma
        página nova com o cache cheio. A página da varredura não pode sair."""
        arq = os.path.join(self.dir.name, "aluno.db")
        cria_tabela_m1(arq, 1200)
        with open(arq, "r+b") as f:
            c = CachePaginas(f, 3)
            it = varre(c, ESQUEMA_ALUNO)
            for _ in range(511):                     # 510 da 1ª página + 1 da 2ª: parado na 2
                next(it)
            self.assertEqual(c.fixadas(), 1)
            self.toca(c, 0, 1, 3)                    # outra "consulta" enche e expulsa
            self.assertIn(2, c)                      # a página do iterador continua
            self.assertEqual(next(it), (512, 20260512))   # e o iterador segue certo
            it.close()
            self.assertEqual(c.fixadas(), 0)

    def test_todas_fixadas_levanta_erro_em_vez_de_expulsar(self):
        c = CachePaginas(self.f, 3)
        c.fixa(0); c.fixa(1); c.fixa(2)
        antes = c.residentes()
        with self.assertRaises(CacheCheio):
            c.fixa(3)
        self.assertEqual(c.residentes(), antes)      # nada foi expulso pelo caminho
        self.assertEqual(c.expulsoes, 0)
        self.assertEqual(c.fixadas(), 3)             # e a chamada falha não fixou nada
        c.solta(0)
        c.fixa(3)                                    # liberou uma: agora cabe
        self.assertNotIn(0, c)
        c.solta(1); c.solta(2); c.solta(3)

    def test_falta_com_cache_todo_fixado_conta_como_falta(self):
        c = CachePaginas(self.f, 1)
        c.fixa(0)
        with self.assertRaises(CacheCheio):
            c.fixa(1)
        self.assertEqual(c.acertos + c.faltas, c.chamadas)   # a soma vale mesmo no erro
        c.solta(0)

    # ---- caminho de erro na falta ----
    def test_leitura_que_falha_depois_da_expulsao_devolve_o_frame(self):
        arq = ArquivoQueFalha(self.f)
        c = CachePaginas(arq, 2)
        self.toca(c, 1, 2)                           # cheio
        arq.falha_leitura = True
        with self.assertRaises(OSError):
            c.fixa(3)                                # expulsa a 1, e a leitura da 3 falha
        arq.falha_leitura = False
        self.assertEqual(c.residentes(), [2])
        self.assertEqual(len(c.livres), 1)           # o frame da vítima voltou aos livres
        self.toca(c, 4)                              # cabe sem expulsar de novo
        self.assertEqual(c.expulsoes, 1)


class TesteContraModeloDeReferencia(Base):
    """Cache real vs. um LRU de 8 linhas, em traces aleatórios."""

    @staticmethod
    def modelo_lru(trace, capacidade):
        fila, acertos, faltas = [], 0, 0             # fila[0] = mais antiga
        for n in trace:
            if n in fila:
                acertos += 1
                fila.remove(n)
            else:
                faltas += 1
                if len(fila) == capacidade:
                    fila.pop(0)
            fila.append(n)
        return fila, acertos, faltas

    def test_lru_bate_com_o_modelo(self):
        rng = random.Random(42)
        for capacidade in (1, 2, 3, 4, 7, 16):
            trace = [rng.randrange(20) for _ in range(500)]
            c = CachePaginas(self.f, capacidade)
            self.toca(c, *trace)
            fila, acertos, faltas = self.modelo_lru(trace, capacidade)
            self.assertEqual(c.residentes(), fila, f"capacidade {capacidade}")
            self.assertEqual((c.acertos, c.faltas), (acertos, faltas))
            self.assertEqual(c.acertos + c.faltas, c.chamadas)
            self.assertEqual(c.faltas, c.leituras_disco)
            self.assertEqual(c.expulsoes, c.faltas - len(c.residentes()))
            self.assertEqual(c.fixadas(), 0)


if __name__ == "__main__":
    unittest.main()
