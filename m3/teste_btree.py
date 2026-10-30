"""
M3 - testes da árvore B+ (btree.py) e da ligação com a tabela (minidb_indice.py).

Os três pontos do slide "O que temos, e o que falta":

    achar um registro sem ler a tabela   -> TesteSemLerATabela
    busca e inserção com divisão          -> TesteBusca, TesteDivisao, TesteFaixa
    sem remoção                           -> (não existe `remove`: ver TesteEscopo)

mais os exercícios 1 e 2 (TesteExercicios), o formato do nó na página
(TestePagina) e o que acontece com o cache e com o disco (TesteCache,
TestePersistencia).

Os testes usam um cache de 3 frames, de propósito (o mesmo argumento do M2):
com capacidade grande a expulsão nunca acontece, e os testes não provariam
que a árvore fixa e solta as páginas direito. Para exercitar divisões sem
milhares de chaves, a maioria usa `max_chaves` pequeno (3, como nos exercícios).

Rodar:  python teste_btree.py -v
"""

import os
import random
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
from apoio import cria_tabela_m1  # noqa: E402
from btree import (  # noqa: E402
    CAP_FOLHA, CAP_INTERNO, FOLHA, INTERNO, ArvoreBMais, ChaveDuplicada, No, SemIndice,
    codifica_no, decodifica_no,
)
from cache import CachePaginas  # noqa: E402
from minidb import ESQUEMA_ALUNO, PAGE_SIZE, inicializa_pagina0  # noqa: E402
from minidb_cache import insere as insere_cache, aloca as aloca_cache, le_metadados, varre  # noqa: E402
from minidb_indice import (  # noqa: E402
    busca_registro, faixa_registros, indexa_tabela, insere_indexado, le_registro,
)


class Base(unittest.TestCase):
    """Arquivo temporário com a página 0 do M1 e um cache de 3 frames."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.caminho = os.path.join(self.dir.name, "t.db")
        self.f = open(self.caminho, "w+b")
        inicializa_pagina0(self.f)
        self.cache = CachePaginas(self.f, 3)

    def tearDown(self):
        self.f.close()
        self.dir.cleanup()

    def reinicia(self):
        """Arquivo e cache novos no meio de um teste (para os subTest)."""
        self.tearDown()
        self.setUp()

    def arvore(self, max_chaves=3):
        return ArvoreBMais.cria(self.cache, max_chaves)

    def insere_todas(self, arv, chaves):
        for k in chaves:
            arv.insere(k, (k % 1000 + 1, k % 50))

    def paginas_lidas(self, funcao):
        """Quantas páginas a função pediu ao cache (acertos + faltas)."""
        self.cache.zera_contadores()
        r = funcao()
        return self.cache.chamadas, r


# ---------------------------------------------------------------- exercícios

class TesteExercicios(Base):
    """Os exercícios dos slides, com no máximo 3 chaves por nó."""

    ORDEM_1 = [10, 20, 5, 30, 25, 40, 15]

    def test_exercicio_1_passo_a_passo(self):
        arv = self.arvore(3)
        for k in (10, 20, 5):
            arv.insere(k, (1, k))
        self.assertEqual(arv.niveis(), [[[5, 10, 20]]])            # cabem numa folha só

        arv.insere(30, (1, 30))                                     # divisão 1
        self.assertEqual(arv.niveis(), [[[20]], [[5, 10], [20, 30]]])

        arv.insere(25, (1, 25))
        self.assertEqual(arv.niveis(), [[[20]], [[5, 10], [20, 25, 30]]])

        arv.insere(40, (1, 40))                                     # divisão 2
        self.assertEqual(arv.niveis(), [[[20, 30]], [[5, 10], [20, 25], [30, 40]]])

        arv.insere(15, (1, 15))                                     # cabe, sem divisão
        self.assertEqual(arv.niveis(), [[[20, 30]], [[5, 10, 15], [20, 25], [30, 40]]])
        arv.confere()

    def test_exercicio_1_altura_e_paginas_lidas_pela_busca_do_25(self):
        arv = self.arvore(3)
        self.insere_todas(arv, self.ORDEM_1)
        self.assertEqual(arv.altura(), 2)
        lidas, rid = self.paginas_lidas(lambda: arv.busca(25))
        self.assertEqual(lidas, 2)                                  # raiz + folha [20 25]
        self.assertIsNotNone(rid)

    def test_exercicio_2_passo_a_passo(self):
        arv = self.arvore(3)
        self.insere_todas(arv, self.ORDEM_1)

        arv.insere(35, (1, 35))                                     # cabe: [30 35 40]
        self.assertEqual(arv.niveis(), [[[20, 30]], [[5, 10, 15], [20, 25], [30, 35, 40]]])

        arv.insere(45, (1, 45))                                     # divisão 1: o 40 sobe
        self.assertEqual(arv.niveis(),
                         [[[20, 30, 40]], [[5, 10, 15], [20, 25], [30, 35], [40, 45]]])

        arv.insere(50, (1, 50))                                     # cabe: [40 45 50]
        self.assertEqual(arv.niveis(),
                         [[[20, 30, 40]], [[5, 10, 15], [20, 25], [30, 35], [40, 45, 50]]])

        arv.insere(55, (1, 55))                                     # divisões 2 e 3: chega à raiz
        self.assertEqual(arv.niveis(), [
            [[40]],
            [[20, 30], [50]],
            [[5, 10, 15], [20, 25], [30, 35], [40, 45], [50, 55]],
        ])
        arv.confere()

    def test_exercicio_2_altura_e_paginas_lidas_pela_faixa_12_a_33(self):
        arv = self.arvore(3)
        self.insere_todas(arv, self.ORDEM_1 + [35, 45, 50, 55])
        self.assertEqual(arv.altura(), 3)

        def le_faixa():
            return [k for k, _ in arv.faixa(12, 33)]

        lidas, chaves = self.paginas_lidas(le_faixa)
        self.assertEqual(chaves, [15, 20, 25, 30])
        # raiz, nó interno, folhas [5 10 15], [20 25] e [30 35] (o 35 já passou de 33)
        self.assertEqual(lidas, 5)

        # o máximo cai no meio da folha [20 25]: o 25 já mostra que passou, não lê a [30 35]
        lidas, chaves = self.paginas_lidas(lambda: [k for k, _ in arv.faixa(12, 24)])
        self.assertEqual((chaves, lidas), ([15, 20], 4))
        # o máximo é o último valor da folha [20 25]: só a folha seguinte mostra que acabou
        lidas, chaves = self.paginas_lidas(lambda: [k for k, _ in arv.faixa(12, 25)])
        self.assertEqual((chaves, lidas), ([15, 20, 25], 5))


# ---------------------------------------------------------------------- busca

class TesteBusca(Base):
    def test_busca_numa_arvore_vazia(self):
        arv = self.arvore()
        self.assertIsNone(arv.busca(1))
        self.assertEqual(arv.altura(), 1)
        self.assertEqual(list(arv.faixa(0, 100)), [])

    def test_busca_sem_divisao_acha_o_rid_certo(self):
        arv = self.arvore(3)
        arv.insere(20, (7, 1))
        arv.insere(10, (3, 5))
        arv.insere(30, (9, 0))
        self.assertEqual(arv.altura(), 1)           # cabem 3: nenhuma divisão
        self.assertEqual(arv.busca(10), (3, 5))
        self.assertEqual(arv.busca(20), (7, 1))
        self.assertEqual(arv.busca(30), (9, 0))

    def test_chave_ausente_devolve_none_em_todas_as_posicoes(self):
        arv = self.arvore(3)
        self.insere_todas(arv, [10, 20, 30, 40, 50, 60])
        for ausente in (-5, 0, 15, 25, 35, 45, 55, 65, 10 ** 6):
            self.assertIsNone(arv.busca(ausente), ausente)

    def test_chave_igual_ao_separador_vai_para_a_direita(self):
        # slide: "À esquerda de 30, chaves menores que 30. Entre 30 e 60, de 30 a 59."
        arv = self.arvore(3)
        self.insere_todas(arv, [10, 20, 30, 40, 50, 60, 70])
        raiz = arv._le(arv.raiz)
        self.assertFalse(raiz.folha)
        for k in raiz.chaves:                       # cada separador existe de verdade, na folha da direita
            self.assertIsNotNone(arv.busca(k))
            folha = arv._desce_ate_folha(k)
            self.assertEqual(folha.chaves[0], k)

    def test_limites_do_inteiro_de_32_bits_e_chaves_negativas(self):
        arv = self.arvore(3)
        extremos = [-(2 ** 31), -1, 0, 1, 2 ** 31 - 1]
        self.insere_todas(arv, extremos)
        for k in extremos:
            self.assertIsNotNone(arv.busca(k), k)
        with self.assertRaises(ValueError):
            arv.insere(2 ** 31, (1, 0))
        with self.assertRaises(ValueError):
            arv.insere(-(2 ** 31) - 1, (1, 0))
        arv.confere()

    def test_rid_fora_do_formato_e_recusado_antes_de_alterar(self):
        arv = self.arvore(3)
        arv.insere(1, (1, 0))
        for rid in ((2 ** 32, 0), (1, 2 ** 16), (-1, 0), (1, -1)):
            with self.assertRaises(ValueError):
                arv.insere(2, rid)
        self.assertIsNone(arv.busca(2))
        self.assertEqual(arv.niveis(), [[[1]]])

    def test_busca_lê_exatamente_altura_paginas(self):
        arv = self.arvore(3)
        self.insere_todas(arv, range(1, 200))
        h = arv.altura()
        self.assertGreaterEqual(h, 4)
        for k in (1, 77, 199, 1000):                # presentes e ausente
            lidas, _ = self.paginas_lidas(lambda: arv.busca(k))
            self.assertEqual(lidas, h, k)


# -------------------------------------------------------------------- divisão

class TesteDivisao(Base):
    def test_a_folha_so_divide_quando_passa_do_maximo(self):
        arv = self.arvore(3)
        self.insere_todas(arv, [10, 20, 30])
        self.assertEqual(arv.niveis(), [[[10, 20, 30]]])
        arv.insere(40, (1, 0))
        self.assertEqual(arv.altura(), 2)

    def test_divisao_de_folha_copia_o_separador_e_encadeia(self):
        arv = self.arvore(3)
        self.insere_todas(arv, [5, 10, 20, 30])
        raiz = arv._le(arv.raiz)
        self.assertEqual(raiz.chaves, [20])
        esq, dir_ = (arv._le(p) for p in raiz.filhos)
        self.assertEqual((esq.chaves, dir_.chaves), ([5, 10], [20, 30]))   # o 20 continua na folha
        self.assertEqual(esq.proxima, dir_.pagina)
        self.assertEqual(dir_.proxima, 0)

    def test_divisao_de_no_interno_sobe_a_chave_sem_copiar(self):
        arv = self.arvore(3)
        self.insere_todas(arv, self.ordem_ex2())
        raiz = arv._le(arv.raiz)
        self.assertEqual(raiz.chaves, [40])
        internos = [arv._le(p) for p in raiz.filhos]
        self.assertEqual([n.chaves for n in internos], [[20, 30], [50]])
        for n in internos:                          # o 40 não ficou em nenhum dos dois internos
            self.assertNotIn(40, n.chaves)

    @staticmethod
    def ordem_ex2():
        return [10, 20, 5, 30, 25, 40, 15, 35, 45, 50, 55]

    def test_raiz_nova_so_quando_a_divisao_chega_nela(self):
        arv = self.arvore(3)
        alturas = []
        for k in self.ordem_ex2():
            arv.insere(k, (1, 0))
            alturas.append(arv.altura())
        # sobe do 1 para o 2 no 30 (4ª chave) e do 2 para o 3 no 55 (última)
        self.assertEqual(alturas, [1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 3])

    def test_a_pagina_da_raiz_muda_e_fica_registrada_na_pagina_0(self):
        arv = self.arvore(3)
        raiz_antes = arv.raiz
        self.insere_todas(arv, [1, 2, 3, 4])
        self.assertNotEqual(arv.raiz, raiz_antes)
        reaberta = ArvoreBMais.abre(self.cache)
        self.assertEqual(reaberta.raiz, arv.raiz)

    def test_ordem_crescente_decrescente_e_aleatoria(self):
        for nome, chaves in (
            ("crescente", list(range(1, 301))),
            ("decrescente", list(range(300, 0, -1))),
            ("aleatoria", random.Random(1).sample(range(1, 301), 300)),
        ):
            with self.subTest(nome):
                self.reinicia()
                arv = self.arvore(3)
                self.insere_todas(arv, chaves)
                altura, total = arv.confere()
                self.assertEqual(total, 300)
                self.assertEqual([k for k, _ in arv.faixa(1, 300)], sorted(chaves))
                self.assertEqual(self.cache.fixadas(), 0)

    def test_invariantes_depois_de_cada_insercao_com_varios_maximos(self):
        for maximo in (2, 3, 4, 5, 8):
            with self.subTest(max_chaves=maximo):
                self.reinicia()
                arv = self.arvore(maximo)
                chaves = random.Random(maximo).sample(range(-500, 500), 150)
                for k in chaves:
                    arv.insere(k, (abs(k) + 1, abs(k) % 100))
                    arv.confere()               # folhas na mesma profundidade, ordem, limites, encadeamento
                for k in chaves:
                    self.assertEqual(arv.busca(k), (abs(k) + 1, abs(k) % 100))

    def test_nenhum_no_passa_do_maximo_e_nenhum_fica_vazio(self):
        arv = self.arvore(4)
        self.insere_todas(arv, random.Random(7).sample(range(2000), 400))
        for nivel in arv.niveis():
            for chaves in nivel:
                self.assertTrue(1 <= len(chaves) <= 4)

    def test_chave_duplicada_e_recusada_e_a_arvore_nao_muda(self):
        arv = self.arvore(3)
        self.insere_todas(arv, [10, 20, 30, 40])
        antes = arv.niveis()
        total_antes = le_metadados(self.cache)[2]
        for k in (10, 20, 30, 40):
            with self.assertRaises(ChaveDuplicada):
                arv.insere(k, (99, 9))
        self.assertEqual(arv.niveis(), antes)
        self.assertEqual(le_metadados(self.cache)[2], total_antes)   # nem página alocada à toa
        self.assertEqual(arv.busca(10), (11, 10))                    # o rid original continua
        self.assertEqual(self.cache.fixadas(), 0)

    def test_com_o_tamanho_de_pagina_de_verdade_e_um_nivel_ate_408_chaves(self):
        arv = ArvoreBMais.cria(self.cache)                           # sem limite: o que cabe na página
        self.insere_todas(arv, range(CAP_FOLHA))
        self.assertEqual(arv.altura(), 1)
        arv.insere(CAP_FOLHA, (1, 0))                                # a 409ª divide
        self.assertEqual(arv.altura(), 2)
        arv.confere()


# ---------------------------------------------------------------------- faixa

class TesteFaixa(Base):
    def setUp(self):
        super().setUp()
        self.arv = self.arvore(3)
        self.chaves = list(range(10, 400, 10))                       # 10, 20, ..., 390
        self.insere_todas(self.arv, random.Random(3).sample(self.chaves, len(self.chaves)))

    def faixa(self, a, b):
        return [k for k, _ in self.arv.faixa(a, b)]

    def test_faixa_atravessa_varias_folhas_em_ordem(self):
        self.assertEqual(self.faixa(55, 205), [k for k in self.chaves if 55 <= k <= 205])

    def test_limites_inclusivos_e_ausentes(self):
        self.assertEqual(self.faixa(20, 40), [20, 30, 40])
        self.assertEqual(self.faixa(21, 39), [30])
        self.assertEqual(self.faixa(31, 39), [])
        self.assertEqual(self.faixa(40, 20), [])                     # minimo > maximo
        self.assertEqual(self.faixa(0, 5), [])                       # tudo abaixo
        self.assertEqual(self.faixa(1000, 2000), [])                 # tudo acima

    def test_faixa_cobrindo_tudo_e_ate_a_ultima_folha(self):
        self.assertEqual(self.faixa(-10 ** 9, 10 ** 9), self.chaves)
        self.assertEqual(self.faixa(380, 10 ** 9), [380, 390])

    def test_faixa_desce_uma_vez_e_segue_o_encadeamento(self):
        h = self.arv.altura()
        achadas = self.faixa(100, 300)
        folhas_com_chaves = len({self.arv._desce_ate_folha(k).pagina for k in achadas})
        lidas, _ = self.paginas_lidas(lambda: self.faixa(100, 300))
        # h páginas na descida (a primeira folha inclusive) + as folhas seguintes pelo
        # encadeamento, nunca voltando à raiz. Só se o último valor da faixa for o último
        # da sua folha é preciso ler mais uma, para ver que o máximo passou.
        # Sem o encadeamento seriam folhas * h.
        base = h + (folhas_com_chaves - 1)
        self.assertIn(lidas, (base, base + 1))
        self.assertLess(lidas, folhas_com_chaves * h)

    def test_o_gerador_abandonado_no_meio_nao_deixa_pagina_fixada(self):
        g = self.arv.faixa(10, 390)
        next(g), next(g)
        g.close()
        self.assertEqual(self.cache.fixadas(), 0)


# --------------------------------------------------------------------- página

class TestePagina(Base):
    def test_capacidades_do_formato(self):
        self.assertEqual((CAP_FOLHA, CAP_INTERNO), (408, 510))
        self.assertLessEqual(16 + CAP_FOLHA * 10, PAGE_SIZE)
        self.assertLessEqual(16 + CAP_INTERNO * 8, PAGE_SIZE)

    def test_ida_e_volta_da_folha(self):
        no = No(FOLHA, 5, chaves=[-3, 4, 90], rids=[(1, 0), (2, 7), (4_000_000_000, 65535)], proxima=9)
        buf = bytearray(PAGE_SIZE)
        codifica_no(no, buf)
        self.assertEqual(len(buf), PAGE_SIZE)
        volta = decodifica_no(buf, 5)
        self.assertEqual((volta.tipo, volta.chaves, volta.rids, volta.proxima),
                         (FOLHA, no.chaves, no.rids, 9))

    def test_ida_e_volta_do_no_interno(self):
        no = No(INTERNO, 8, chaves=[20, 30], filhos=[2, 3, 4])
        buf = bytearray(PAGE_SIZE)
        codifica_no(no, buf)
        volta = decodifica_no(buf, 8)
        self.assertEqual((volta.tipo, volta.chaves, volta.filhos), (INTERNO, [20, 30], [2, 3, 4]))

    def test_no_cheio_cabe_na_pagina(self):
        folha = No(FOLHA, 1, chaves=list(range(CAP_FOLHA)), rids=[(1, 0)] * CAP_FOLHA)
        interno = No(INTERNO, 2, chaves=list(range(CAP_INTERNO)), filhos=list(range(CAP_INTERNO + 1)))
        for no in (folha, interno):
            buf = bytearray(PAGE_SIZE)
            codifica_no(no, buf)
            self.assertEqual(len(buf), PAGE_SIZE)
            self.assertEqual(decodifica_no(buf, no.pagina).chaves, no.chaves)

    def test_a_sobra_da_pagina_fica_zerada_e_o_mesmo_no_da_os_mesmos_bytes(self):
        grande = No(FOLHA, 3, chaves=[1, 2, 3, 4], rids=[(1, i) for i in range(4)])
        pequeno = No(FOLHA, 3, chaves=[1], rids=[(1, 0)])
        buf = bytearray(PAGE_SIZE)
        codifica_no(grande, buf)
        codifica_no(pequeno, buf)                                    # reaproveita o buffer sujo
        limpo = bytearray(PAGE_SIZE)
        codifica_no(pequeno, limpo)
        self.assertEqual(buf, limpo)

    def test_o_cabecalho_nunca_se_confunde_com_pagina_de_dados(self):
        # no M1, o bytes 2..3 são o tam_registro (nunca 0); no nó, são sempre 0
        buf = bytearray(PAGE_SIZE)
        codifica_no(No(FOLHA, 4), buf)
        self.assertEqual(buf[2:4], b"\x00\x00")

    def test_pagina_de_dados_nao_e_aceita_como_no(self):
        arv = self.arvore()
        pagina_dados = aloca_cache(self.cache, ESQUEMA_ALUNO.tamanho)
        with self.assertRaises(ValueError):
            arv._le(pagina_dados)

    def test_pagina_de_outro_lugar_nao_e_aceita(self):
        buf = bytearray(PAGE_SIZE)
        codifica_no(No(FOLHA, 4), buf)
        with self.assertRaises(ValueError):
            decodifica_no(buf, 5)                                    # num_pagina não bate
        buf[8] = 7                                                   # tipo inválido
        with self.assertRaises(ValueError):
            decodifica_no(buf, 4)


# ---------------------------------------------------------------------- cache

class TesteCache(Base):
    def test_nenhuma_operacao_deixa_pagina_fixada(self):
        arv = self.arvore(3)
        for k in random.Random(5).sample(range(500), 200):
            arv.insere(k, (1, 0))
            self.assertEqual(self.cache.fixadas(), 0)
        arv.busca(10), list(arv.faixa(0, 500)), arv.altura(), arv.niveis(), arv.confere()
        self.assertEqual(self.cache.fixadas(), 0)

    def test_funciona_com_3_frames_mesmo_com_arvore_de_varios_niveis(self):
        arv = self.arvore(3)
        self.insere_todas(arv, range(1, 400))
        self.assertGreaterEqual(arv.altura(), 5)                     # mais níveis que frames
        self.assertGreater(self.cache.expulsoes, 0)                  # e a expulsão aconteceu de verdade
        self.assertEqual(self.cache.fixadas(), 0)

    def test_a_arvore_tambem_funciona_com_um_cache_de_2_frames(self):
        # no máximo duas páginas fixadas ao mesmo tempo (docstring de ArvoreBMais)
        self.cache = CachePaginas(self.f, 2)
        arv = self.arvore(3)
        self.insere_todas(arv, random.Random(2).sample(range(300), 120))
        arv.confere()

    def test_erro_no_meio_da_insercao_nao_deixa_pin(self):
        arv = self.arvore(3)
        self.insere_todas(arv, [1, 2, 3])
        with self.assertRaises(ChaveDuplicada):
            arv.insere(2, (1, 0))
        with self.assertRaises(ValueError):
            arv.insere(2 ** 40, (1, 0))
        self.assertEqual(self.cache.fixadas(), 0)

    def test_a_pagina_0_e_a_do_m1_continuam_validas(self):
        arv = self.arvore(3)
        self.insere_todas(arv, range(1, 50))
        versao, tam_pagina, total = le_metadados(self.cache)
        self.assertEqual((versao, tam_pagina), (1, PAGE_SIZE))
        self.assertEqual(total, 1 + len(self._paginas_do_indice(arv)))

    def _paginas_do_indice(self, arv):
        vistas, atual = set(), [arv.raiz]
        while atual:
            vistas.update(atual)
            proximos = []
            for p in atual:
                no = arv._le(p)
                if not no.folha:
                    proximos += no.filhos
            atual = proximos
        return vistas


# ---------------------------------------------------------------- persistência

class TestePersistencia(Base):
    def test_reabrir_com_outro_cache_acha_tudo(self):
        arv = self.arvore(3)
        chaves = random.Random(4).sample(range(1000), 100)
        self.insere_todas(arv, chaves)
        self.cache.grava_tudo()
        outro = CachePaginas(self.f, 3)                              # cache frio, mesmo arquivo
        reaberta = ArvoreBMais.abre(outro)
        self.assertEqual(reaberta.max_chaves, 3)                     # o limite também fica na página 0
        self.assertEqual(reaberta.confere()[1], 100)
        for k in chaves:
            self.assertEqual(reaberta.busca(k), (k % 1000 + 1, k % 50))

    def test_reabrir_em_outro_processo(self):
        arv = self.arvore(3)
        self.insere_todas(arv, range(1, 60))
        self.cache.grava_tudo()
        codigo = (
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "from btree import ArvoreBMais\n"
            "from cache import CachePaginas\n"
            "with open(sys.argv[2], 'rb') as f:\n"
            "    a = ArvoreBMais.abre(CachePaginas(f, 3))\n"
            "    print(a.confere()[1], a.busca(42))\n"
        )
        saida = subprocess.run([sys.executable, "-c", codigo, RAIZ, self.caminho],
                               capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(saida[0], "59")
        self.assertEqual(saida[1:], ["(43,", "42)"])

    def test_sem_grava_tudo_o_disco_nao_tem_o_indice_novo(self):
        # o contrato do M2 vale aqui: durabilidade é o grava_tudo() explícito, e sem
        # log o disco pode ficar com o índice pela metade. Ou a reabertura falha
        # (uma página que a raiz promete nunca foi gravada) ou ela vê menos chaves.
        arv = self.arvore(3)
        self.insere_todas(arv, [1, 2, 3, 4, 5])
        self.cache.grava_tudo()
        self.insere_todas(arv, [6, 7, 8, 9, 10, 11])                 # sem gravar
        frio = CachePaginas(self.f, 3)
        try:
            vistas = ArvoreBMais.abre(frio).confere()[1]
        except (ValueError, AssertionError):
            return
        self.assertLess(vistas, 11)

    def test_abrir_tabela_sem_indice(self):
        with self.assertRaises(SemIndice):
            ArvoreBMais.abre(self.cache)

    def test_criar_duas_vezes_e_erro(self):
        self.arvore(3)
        with self.assertRaises(RuntimeError):
            self.arvore(3)

    def test_max_chaves_invalido(self):
        for ruim in (0, 1, CAP_FOLHA + 1):
            with self.assertRaises(ValueError):
                ArvoreBMais.cria(self.cache, ruim)

    def test_arquivo_que_nao_e_minidb(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.db")
            with open(p, "w+b") as f:
                f.write(b"\x07" * PAGE_SIZE)
                with self.assertRaises(ValueError):
                    ArvoreBMais.abre(CachePaginas(f, 3))


# ------------------------------------------------- achar sem ler a tabela (M1+M3)

class TesteSemLerATabela(Base):
    N = 1200                                                         # a tabela do M1: 3 páginas de dados

    def setUp(self):
        super().setUp()
        self.f.close()
        self.total = cria_tabela_m1(self.caminho, self.N)            # feita pelo código do M1, sem índice
        self.f = open(self.caminho, "r+b")
        self.cache = CachePaginas(self.f, 3)
        self.arv = ArvoreBMais.cria(self.cache)                      # índice de tamanho real
        self.indexados = indexa_tabela(self.cache, ESQUEMA_ALUNO, self.arv)

    def test_indexa_a_tabela_que_ja_existia(self):
        self.assertEqual(self.indexados, self.N)
        self.assertEqual(self.arv.confere()[1], self.N)

    def test_acha_o_registro_certo(self):
        for chave in (1, 2, 509, 510, 511, 600, 1199, self.N):
            self.assertEqual(busca_registro(self.cache, ESQUEMA_ALUNO, self.arv, chave),
                             (chave, 20260000 + chave), chave)
        self.assertIsNone(busca_registro(self.cache, ESQUEMA_ALUNO, self.arv, 0))
        self.assertIsNone(busca_registro(self.cache, ESQUEMA_ALUNO, self.arv, self.N + 1))

    def test_achar_o_registro_le_a_arvore_e_uma_pagina_da_tabela_so(self):
        h = self.arv.altura()
        paginas_da_tabela = self._paginas_de_dados()
        self.assertEqual(len(paginas_da_tabela), 3)
        self.cache.zera_contadores()
        pedidas = []
        original = self.cache.fixa
        self.cache.fixa = lambda n: (pedidas.append(n), original(n))[1]
        try:
            busca_registro(self.cache, ESQUEMA_ALUNO, self.arv, 777)
        finally:
            self.cache.fixa = original
        da_tabela = [p for p in pedidas if p in paginas_da_tabela]
        self.assertEqual(len(da_tabela), 1)                          # uma página de dados, não varre
        self.assertEqual(len(pedidas), h + 1)                        # altura da árvore + 1

    def test_varrer_a_tabela_le_todas_as_paginas_de_dados(self):
        dados = self._paginas_de_dados()
        indice = self._paginas_do_indice()
        self.cache.zera_contadores()
        pedidas = []
        original = self.cache.fixa
        self.cache.fixa = lambda n: (pedidas.append(n), original(n))[1]
        try:
            registros = list(varre(self.cache, ESQUEMA_ALUNO))
        finally:
            self.cache.fixa = original
        self.assertEqual(len(registros), self.N)                     # sem lixo: nós não viram registro
        self.assertTrue(dados <= set(pedidas))                       # leu toda a tabela
        # custo do arquivo único: a varredura também fixa as páginas do índice (para
        # ver que não são de dados) e as pula. Por isso a busca pelo índice vale mais.
        self.assertEqual(set(pedidas) - {0}, dados | indice)

    def test_a_varredura_do_m1_pula_as_paginas_do_indice(self):
        from minidb import varredura
        self.cache.grava_tudo()
        registros, _ = varredura(self.f, ESQUEMA_ALUNO)
        self.assertEqual(len(registros), self.N)
        self.assertEqual(sorted(r[0] for r in registros), list(range(1, self.N + 1)))

    def test_insere_indexado_depois_do_indice(self):
        _, atual = self._ultima_pagina_de_dados()
        for chave in range(self.N + 1, self.N + 701):
            _, atual = insere_indexado(self.cache, ESQUEMA_ALUNO, self.arv,
                                       (chave, 20260000 + chave), atual)
        self.assertEqual(self.arv.confere()[1], self.N + 700)
        for chave in (1, self.N, self.N + 1, self.N + 700):
            self.assertEqual(busca_registro(self.cache, ESQUEMA_ALUNO, self.arv, chave)[0], chave)
        self.assertEqual(len(list(varre(self.cache, ESQUEMA_ALUNO))), self.N + 700)
        self.assertEqual(self.cache.fixadas(), 0)

    def test_insere_indexado_recusa_duplicata_antes_de_gravar_na_tabela(self):
        _, atual = self._ultima_pagina_de_dados()
        antes = len(list(varre(self.cache, ESQUEMA_ALUNO)))
        with self.assertRaises(ChaveDuplicada):
            insere_indexado(self.cache, ESQUEMA_ALUNO, self.arv, (5, 1), atual)
        self.assertEqual(len(list(varre(self.cache, ESQUEMA_ALUNO))), antes)   # nada entrou na tabela
        self.assertEqual(self.cache.fixadas(), 0)

    def test_faixa_de_registros_vem_em_ordem_de_id(self):
        regs = list(faixa_registros(self.cache, ESQUEMA_ALUNO, self.arv, 505, 515))
        self.assertEqual([r[0] for r in regs], list(range(505, 516)))      # atravessa a página 1 -> 2
        self.assertEqual(regs[0], (505, 20260505))

    def test_rid_que_aponta_para_slot_que_nao_existe(self):
        with self.assertRaises(ValueError):
            le_registro(self.cache, ESQUEMA_ALUNO, (1, 10_000))

    def test_indice_construido_por_insercao_igual_ao_construido_pela_varredura(self):
        # mesma tabela, mas o índice nasce junto com a tabela (insere_indexado)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "n.db"), "w+b") as f2:
                inicializa_pagina0(f2)
                c2 = CachePaginas(f2, 3)
                a2 = ArvoreBMais.cria(c2)
                atual = aloca_cache(c2, ESQUEMA_ALUNO.tamanho)
                for i in range(1, self.N + 1):
                    _, atual = insere_indexado(c2, ESQUEMA_ALUNO, a2, (i, 20260000 + i), atual)
                self.assertEqual(a2.confere()[1], self.N)
                for i in (1, 600, self.N):
                    self.assertEqual(busca_registro(c2, ESQUEMA_ALUNO, a2, i), (i, 20260000 + i))

    def _paginas_de_dados(self):
        return set(range(1, le_metadados(self.cache)[2])) - self._paginas_do_indice()

    def _paginas_do_indice(self):
        vistas, atual = set(), [self.arv.raiz]
        while atual:
            vistas.update(atual)
            proximos = []
            for p in atual:
                no = self.arv._le(p)
                if not no.folha:
                    proximos += no.filhos
            atual = proximos
        return vistas

    def _ultima_pagina_de_dados(self):
        return None, max(self._paginas_de_dados())


# ------------------------------------------------------------------- terminal

class TesteTerminal(Base):
    """indice.py: um comando por vez, em outro processo, como no terminal."""

    def roda(self, *args):
        r = subprocess.run([sys.executable, os.path.join(RAIZ, "indice.py"), self.db, *args],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.dir.name, "term.db")
        subprocess.run([sys.executable, os.path.join(RAIZ, "indice.py"), self.db, "300"],
                       input="sair\n", capture_output=True, text=True, check=True, timeout=60)  # cria 300 alunos

    def test_busca_mostra_o_registro_e_o_custo(self):
        saida = self.roda("busca", "150")
        self.assertIn("(id, matricula) = (150, 20260150)", saida)
        self.assertIn("da TABELA", saida)

    def test_busca_de_id_ausente_nao_chega_na_tabela(self):
        saida = self.roda("busca", "9999")
        self.assertIn("nenhum registro", saida)
        self.assertNotIn("da TABELA", saida)

    def test_insere_persiste_e_recusa_duplicata(self):
        self.assertIn("inserido", self.roda("insere", "301", "555"))
        self.assertIn("(id, matricula) = (301, 555)", self.roda("busca", "301"))   # outro processo
        self.assertIn("recusado", self.roda("insere", "301", "1"))

    def test_faixa_e_varredura(self):
        self.assertIn("3 registros", self.roda("faixa", "10", "12"))
        self.assertIn("(150, 20260150)", self.roda("varre", "150"))


# --------------------------------------------------------------------- escopo

class TesteEscopo(Base):
    def test_o_m3_nao_tem_remocao(self):
        arv = self.arvore()
        for nome in ("remove", "remover", "apaga", "delete"):
            self.assertFalse(hasattr(arv, nome), nome)


if __name__ == "__main__":
    unittest.main()
