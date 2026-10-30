"""
teste_sql.py - testes do M4 (python teste_sql.py -v). Um arquivo só, por etapa:

    Tokenizador   os exemplos dos slides, e cada erro léxico
    Parser        as árvores dos slides, os erros do exercício 2, o que sobra
    Semantica     tabela, coluna, tipo, tamanho (precisa do catálogo)
    Catalogo      em disco: outro cache, outro processo, várias páginas
    Tabelas       corrente de páginas, duas tabelas intercaladas, cache de 3 frames
    Programa      o ./minidb de verdade, com a meta do slide palavra por palavra
    Injecao       o exercício 2.2 contra o minidb
"""

import os
import struct
import subprocess
import sys
import tempfile
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

from cache import CachePaginas                                    # noqa: E402
from catalogo import Catalogo, EsquemaSQL, OFF_CATALOGO           # noqa: E402
from erros import ErroLexico, ErroSemantico, ErroSintatico        # noqa: E402
from executor import confere, executa                             # noqa: E402
from minidb import PAGE_SIZE, inicializa_pagina0                  # noqa: E402
from sql import analisa, tokeniza                                 # noqa: E402

CREATE_ALUNO = "CREATE TABLE aluno (id INT, matricula INT, nome CHAR(20));"
PROGRAMA = os.path.join(AQUI, "minidb")


class ComBanco(unittest.TestCase):
    """Um arquivo minidb temporário, com cache de 3 frames (de propósito: com
    capacidade grande a expulsão nunca acontece e os testes não provam nada)."""

    FRAMES = 3

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.caminho = os.path.join(self.dir.name, "t.db")
        self.abertos = []
        with open(self.caminho, "w+b") as f:
            inicializa_pagina0(f)
        self.abre()

    def tearDown(self):
        for f in self.abertos:
            f.close()
        self.dir.cleanup()

    def abre(self):
        """(Re)abre o arquivo com um cache NOVO: só o que está no disco vale."""
        f = open(self.caminho, "r+b")
        self.abertos.append(f)
        self.cache = CachePaginas(f, self.FRAMES)
        self.cat = Catalogo(self.cache)
        return self.cat

    def sql(self, texto):
        r = executa(texto, self.cat, self.cache)
        self.assertEqual(self.cache.fixadas(), 0, f"página ficou fixada depois de: {texto}")
        return r


# ---------------------------------------------------------------- etapa 1

class Tokenizador(unittest.TestCase):
    def test_slide_nome_char_20(self):
        # a tabela "o tokenizador rodando à mão"
        self.assertEqual(tokeniza("nome CHAR(20),"), [
            ("NOME", "nome"), ("PALAVRA", "CHAR"), ("SIMBOLO", "("), ("NUMERO", 20),
            ("SIMBOLO", ")"), ("SIMBOLO", ","), ("FIM", None)])

    def test_slide_create_completo(self):
        t = tokeniza(CREATE_ALUNO)
        self.assertEqual(len(t), 18)                      # 17 tokens + FIM, como no slide
        self.assertEqual(t[0], ("PALAVRA", "CREATE"))
        self.assertEqual(t[2], ("NOME", "aluno"))
        self.assertEqual(t[-2:], [("SIMBOLO", ";"), ("FIM", None)])

    def test_slide_select_tem_nove_tokens(self):
        self.assertEqual(len(tokeniza("SELECT nome FROM aluno WHERE id = 42")), 9)

    def test_gabarito_exercicio_1(self):
        self.assertEqual(tokeniza("INSERT INTO aluno VALUES (3, 20260003, 'Carla');"), [
            ("PALAVRA", "INSERT"), ("PALAVRA", "INTO"), ("NOME", "aluno"),
            ("PALAVRA", "VALUES"), ("SIMBOLO", "("), ("NUMERO", 3), ("SIMBOLO", ","),
            ("NUMERO", 20260003), ("SIMBOLO", ","), ("TEXTO", "Carla"), ("SIMBOLO", ")"),
            ("SIMBOLO", ";"), ("FIM", None)])

    def test_maiuscula_minuscula_dao_o_mesmo_token(self):
        self.assertEqual(tokeniza("create"), tokeniza("CREATE"))
        self.assertEqual(tokeniza("cReAtE")[0], ("PALAVRA", "CREATE"))

    def test_nome_mantem_a_caixa(self):
        self.assertEqual(tokeniza("Aluno")[0], ("NOME", "Aluno"))

    def test_numero_sai_como_int_e_texto_sem_aspas(self):
        self.assertEqual(tokeniza("20 '20'")[:2], [("NUMERO", 20), ("TEXTO", "20")])

    def test_texto_guarda_espacos_e_simbolos_por_dentro(self):
        self.assertEqual(tokeniza("'a ( b ; c'")[0], ("TEXTO", "a ( b ; c"))
        self.assertEqual(tokeniza("''")[0], ("TEXTO", ""))

    def test_palavra_reservada_dentro_de_texto_continua_texto(self):
        self.assertEqual(tokeniza("'SELECT'")[0], ("TEXTO", "SELECT"))

    def test_vazio_so_tem_fim(self):
        self.assertEqual(tokeniza(""), [("FIM", None)])
        self.assertEqual(tokeniza("  \t\n "), [("FIM", None)])

    def test_nao_olha_a_ordem(self):
        # o tokenizador deixa passar o que o parser vai recusar
        self.assertEqual(len(tokeniza("TABLE CREATE ( (")), 5)

    def test_nome_com_underscore_e_digito(self):
        self.assertEqual(tokeniza("nota_1")[0], ("NOME", "nota_1"))

    def test_nome_acentuado(self):
        self.assertEqual(tokeniza("açúcar")[0], ("NOME", "açúcar"))

    def test_erro_aspas_sem_fechamento_diz_a_posicao(self):
        with self.assertRaisesRegex(ErroLexico, "aspas sem fechamento na posição 7"):
            tokeniza("SELECT 'abc")

    def test_erro_caractere_inesperado(self):
        with self.assertRaisesRegex(ErroLexico, r"caractere inesperado '#' na posição 7"):
            tokeniza("SELECT #")
        for ruim in ("-1", "a.b", "a<b", '"x"', "x\x00"):
            with self.assertRaises(ErroLexico, msg=ruim):
                tokeniza(ruim)

    def test_digito_que_nao_e_ascii_nao_estoura(self):
        # '²'.isdigit() é True mas int('²') levanta ValueError: tem que virar ErroLexico
        with self.assertRaises(ErroLexico):
            tokeniza("²")

    def test_numero_com_milhares_de_digitos_vira_erro_lexico(self):
        with self.assertRaises(ErroLexico):
            tokeniza("9" * 5000)


# ---------------------------------------------------------------- etapa 2

class ParserArvores(unittest.TestCase):
    def test_create_do_slide(self):
        self.assertEqual(analisa(CREATE_ALUNO), {
            "op": "CREATE", "tabela": "aluno",
            "colunas": [("id", "INT", 4), ("matricula", "INT", 4), ("nome", "CHAR", 20)]})

    def test_insert_do_gabarito(self):
        self.assertEqual(analisa("INSERT INTO aluno VALUES (3, 20260003, 'Carla');"),
                         {"op": "INSERT", "tabela": "aluno", "valores": [3, 20260003, "Carla"]})

    def test_select_com_where_do_slide(self):
        self.assertEqual(analisa("SELECT nome FROM aluno WHERE id = 42"),
                         {"op": "SELECT", "colunas": ["nome"], "tabela": "aluno", "where": ("id", 42)})

    def test_select_estrela_e_varias_colunas(self):
        self.assertEqual(analisa("SELECT * FROM aluno")["colunas"], ["*"])
        self.assertEqual(analisa("SELECT id, nome FROM aluno")["colunas"], ["id", "nome"])
        self.assertIsNone(analisa("SELECT * FROM aluno")["where"])

    def test_where_com_texto(self):
        self.assertEqual(analisa("SELECT * FROM aluno WHERE nome = 'Ana'")["where"], ("nome", "Ana"))

    def test_ponto_e_virgula_e_opcional(self):
        self.assertEqual(analisa("SELECT * FROM aluno;"), analisa("SELECT * FROM aluno"))

    def test_palavras_em_minusculas(self):
        self.assertEqual(analisa("select * from aluno where id = 1")["op"], "SELECT")

    def test_espacos_e_quebras_nao_importam(self):
        self.assertEqual(analisa("SELECT\n*\tFROM   aluno ;  \n"), analisa("SELECT * FROM aluno"))

    def test_uma_coluna_so_e_uma_coluna_char_1(self):
        self.assertEqual(analisa("CREATE TABLE t (a CHAR(1))")["colunas"], [("a", "CHAR", 1)])

    def test_insert_so_com_texto_e_so_com_numero(self):
        self.assertEqual(analisa("INSERT INTO t VALUES ('')")["valores"], [""])
        self.assertEqual(analisa("INSERT INTO t VALUES (0)")["valores"], [0])

    def test_o_parser_nao_confere_tipo_nem_tabela(self):
        # isso é semântica: precisa do catálogo
        analisa("INSERT INTO naoexiste VALUES ('x', 1, 2, 3)")
        analisa("SELECT idade FROM naoexiste")


class ParserErros(unittest.TestCase):
    def erro(self, sql, tipo=ErroSintatico):
        with self.assertRaises(tipo) as cm:
            analisa(sql)
        return str(cm.exception)

    def test_exercicio_1_3_carla_sem_aspas(self):
        self.assertEqual(self.erro("INSERT INTO aluno VALUES (3, 20260003, Carla);"),
                         "esperava valor, veio 'Carla'")

    def test_exercicio_2_1_igual_igual(self):
        self.assertEqual(self.erro("SELECT nome FROM aluno WHERE id == 42"),
                         "esperava valor, veio '='")

    def test_exercicio_2_1_falta_o_nome_da_tabela(self):
        self.assertEqual(self.erro("SELECT * FROM WHERE id = 42"), "esperava NOME, veio 'WHERE'")

    def test_exercicio_2_1_aspa_no_meio_e_erro_lexico_nao_sintatico(self):
        # 'O'Brien' vira TEXTO 'O', NOME Brien e uma aspa que nunca fecha:
        # o tokenizador falha antes de o parser ver qualquer coisa
        self.erro("SELECT * FROM aluno WHERE nome = 'O'Brien'", ErroLexico)

    def test_ordem_trocada(self):
        self.erro("CREATE TABLE aluno (id INT nome, CHAR(20))")
        self.erro("TABLE CREATE ( (")

    def test_sobrou_token(self):
        self.assertEqual(self.erro("SELECT * FROM aluno aluno"), "esperava FIM, veio 'aluno'")
        self.erro("SELECT * FROM aluno; SELECT * FROM aluno")      # um comando por vez

    def test_comando_faltando_pedaco(self):
        self.assertEqual(self.erro("SELECT *"), "esperava FROM, veio o fim do comando")
        self.erro("SELECT FROM aluno")
        self.erro("INSERT INTO aluno VALUES ()")
        self.erro("INSERT INTO aluno VALUES (1,)")
        self.erro("CREATE TABLE aluno ()")
        self.erro("CREATE TABLE aluno (id INT,)")
        self.erro("SELECT * FROM aluno WHERE")
        self.erro("SELECT * FROM aluno WHERE id =")

    def test_vazio_e_so_ponto_e_virgula(self):
        self.assertEqual(self.erro(""), "comando desconhecido o fim do comando")
        self.erro(";")

    def test_comando_desconhecido(self):
        self.assertEqual(self.erro("DROP TABLE aluno"), "comando desconhecido 'DROP'")
        self.erro("UPDATE aluno")

    def test_texto_com_nome_de_comando_nao_e_comando(self):
        self.assertEqual(self.erro("'SELECT' * FROM aluno"), "comando desconhecido 'SELECT'")
        self.assertEqual(self.erro("'CREATE' TABLE t (a INT)"), "comando desconhecido 'CREATE'")
        self.assertEqual(self.erro("'INSERT' INTO t VALUES (1)"), "comando desconhecido 'INSERT'")

    def test_palavra_reservada_na_posicao_errada(self):
        # a palavra certa é parte da gramática: qualquer outra PALAVRA no lugar dela é erro
        self.assertEqual(self.erro("CREATE FROM t (a INT)"), "esperava TABLE, veio 'FROM'")
        self.assertEqual(self.erro("INSERT FROM t VALUES (1)"), "esperava INTO, veio 'FROM'")
        self.assertEqual(self.erro("INSERT INTO t SELECT (1)"), "esperava VALUES, veio 'SELECT'")
        self.assertEqual(self.erro("SELECT * INTO t"), "esperava FROM, veio 'INTO'")
        self.assertEqual(self.erro("CREATE TABLE t (a CHAR(5) INT)"), "esperava ), veio 'INT'")

    def test_tipo_desconhecido_diz_int_ou_char(self):
        self.assertEqual(self.erro("CREATE TABLE t (a FLOAT)"), "esperava INT ou CHAR, veio 'FLOAT'")

    def test_char_sem_tamanho(self):
        self.erro("CREATE TABLE t (a CHAR)")
        self.erro("CREATE TABLE t (a CHAR())")
        self.erro("CREATE TABLE t (a CHAR('x'))")

    def test_palavra_reservada_nao_serve_de_nome(self):
        self.erro("CREATE TABLE select (a INT)")
        self.erro("SELECT * FROM aluno WHERE where = 1")

    def test_sem_or_e_sem_and(self):
        self.erro("SELECT * FROM aluno WHERE id = 1 OR id = 2")
        self.erro("SELECT * FROM aluno WHERE id = 1 AND id = 2")

    def test_where_so_igualdade(self):
        self.erro("SELECT * FROM aluno WHERE id > 1", ErroLexico)     # '>' nem é símbolo
        self.erro("SELECT * FROM aluno WHERE id")

    def test_valor_no_where_nao_pode_ser_nome(self):
        self.erro("SELECT * FROM aluno WHERE id = matricula")


# ---------------------------------------------------------------- etapa 3

class Semantica(ComBanco):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.sql(CREATE_ALUNO), "OK")

    def erro(self, texto, etapa="semântico", trecho=""):
        r = self.sql(texto)
        self.assertTrue(r.startswith(f"ERRO {etapa}: "), r)
        self.assertIn(trecho, r)
        return r

    def test_tabela_inexistente(self):
        for s in ("SELECT * FROM curso", "INSERT INTO curso VALUES (1)", "SELECT id FROM curso WHERE id = 1"):
            self.erro(s, trecho="a tabela curso não existe")

    def test_coluna_inexistente_exercicio_2_1(self):
        self.erro("SELECT idade FROM aluno", trecho="a tabela aluno não tem a coluna idade")
        self.erro("SELECT id, idade FROM aluno", trecho="idade")
        self.erro("SELECT * FROM aluno WHERE idade = 1", trecho="idade")

    def test_numero_de_valores(self):
        self.erro("INSERT INTO aluno VALUES (1, 2)", trecho="tem 3 colunas, vieram 2 valores")
        self.erro("INSERT INTO aluno VALUES (1, 2, 'a', 4)", trecho="vieram 4")

    def test_tipo_nao_bate(self):
        self.erro("INSERT INTO aluno VALUES ('um', 2, 'a')", trecho="a coluna id é INT, veio o texto 'um'")
        self.erro("INSERT INTO aluno VALUES (1, 2, 3)", trecho="a coluna nome é CHAR(20), veio o número 3")
        self.erro("SELECT * FROM aluno WHERE id = 'um'", trecho="é INT")
        self.erro("SELECT * FROM aluno WHERE nome = 7", trecho="é CHAR(20)")

    def test_int_fora_de_32_bits(self):
        self.erro("INSERT INTO aluno VALUES (2147483648, 1, 'a')", trecho="não cabe")
        self.assertEqual(self.sql("INSERT INTO aluno VALUES (2147483647, 1, 'a')"), "OK 1")

    def test_texto_grande_demais_conta_bytes_nao_letras(self):
        self.assertEqual(self.sql("INSERT INTO aluno VALUES (1, 1, '" + "a" * 20 + "')"), "OK 1")
        self.erro("INSERT INTO aluno VALUES (2, 1, '" + "a" * 21 + "')", trecho="21 bytes")
        # 10 letras de 2 bytes = 20 bytes cabem; 11 não
        self.assertEqual(self.sql("INSERT INTO aluno VALUES (3, 1, '" + "ã" * 10 + "')"), "OK 1")
        self.erro("INSERT INTO aluno VALUES (4, 1, '" + "ã" * 11 + "')", trecho="22 bytes")

    def test_erro_semantico_nao_grava_nada(self):
        antes = self.sql("SELECT * FROM aluno")
        self.sql("INSERT INTO aluno VALUES (1, 2)")
        self.sql("INSERT INTO aluno VALUES ('x', 2, 'a')")
        self.assertEqual(self.sql("SELECT * FROM aluno"), antes)
        _, _, total = __import__("minidb_cache").le_metadados(self.cache)
        self.assertEqual(total, 3)                       # página 0, catálogo, dados

    def test_erro_lexico_e_sintatico_nao_consultam_o_catalogo(self):
        # tabela que nem existe: o erro é da etapa 1 ou 2, não da 3
        self.erro("SELECT * FROM naoexiste WHERE nome = 'O'Brien'", etapa="léxico")
        self.erro("SELECT * FROM naoexiste WHERE id == 1", etapa="sintático")

    def test_create_repetido_e_coluna_repetida(self):
        self.erro(CREATE_ALUNO, trecho="a tabela aluno já existe")
        self.erro("CREATE TABLE ALUNO (a INT)", trecho="já existe")          # sem diferenciar caixa
        self.erro("CREATE TABLE t (a INT, A CHAR(3))", trecho="aparece duas vezes")
        self.assertFalse(self.cat.existe("t"))

    def test_char_zero_e_registro_grande_demais(self):
        self.erro("CREATE TABLE t (a CHAR(0))", trecho="pelo menos 1")
        self.erro("CREATE TABLE t (a CHAR(4081))", trecho="4081 bytes")
        self.assertEqual(self.sql("CREATE TABLE t (a CHAR(4080))"), "OK")
        self.erro("CREATE TABLE u (a CHAR(4080), b INT)", trecho="4084 bytes")

    def test_nome_comprido_demais(self):
        self.erro(f"CREATE TABLE {'x' * 33} (a INT)", trecho="passa de 32 bytes")
        self.erro(f"CREATE TABLE t ({'x' * 33} INT)", trecho="passa de 32 bytes")
        self.assertEqual(self.sql(f"CREATE TABLE {'x' * 32} (a INT)"), "OK")

    def test_muitas_colunas_nao_cabem_no_catalogo(self):
        cols = ", ".join(f"c{i} INT" for i in range(400))
        self.erro(f"CREATE TABLE largo ({cols})", trecho="400 colunas")
        cols = ", ".join(f"{'c' * 28}{i:03d} INT" for i in range(255))     # 255 colunas, nomes de 31 bytes
        self.erro(f"CREATE TABLE largo ({cols})", trecho="colunas demais")
        self.assertEqual(self.sql("CREATE TABLE ok (" + ", ".join(f"c{i} INT" for i in range(255)) + ")"), "OK")
        self.assertEqual(len(self.abre().busca("ok").colunas), 255)

    def test_sem_diferenciar_caixa_em_tabela_e_coluna(self):
        self.sql("INSERT INTO ALUNO VALUES (1, 1, 'Ana')")
        self.assertEqual(self.sql("SELECT NOME FROM Aluno"), "Ana\n(1 linha)")

    def test_where_e_conferido_mas_nao_executado(self):
        r = self.erro("SELECT * FROM aluno WHERE id = 1", etapa="não implementado", trecho="M5")
        self.assertNotIn("não tem a coluna", r)


# ---------------------------------------------------------------- o catálogo no disco

class CatalogoEmDisco(ComBanco):
    def test_arquivo_novo_tem_catalogo_vazio_e_aponta_na_pagina_0(self):
        self.assertEqual(self.cat.nomes(), [])
        self.cache.grava_tudo()
        with open(self.caminho, "rb") as f:
            self.assertNotEqual(struct.unpack_from("<I", f.read(PAGE_SIZE), OFF_CATALOGO)[0], 0)

    def test_outro_cache_enxerga_a_tabela_pelo_disco(self):
        self.sql(CREATE_ALUNO)
        self.cache.grava_tudo()
        cat2 = self.abre()
        t = cat2.busca("aluno")
        self.assertEqual(t.colunas, [("id", "INT", 4), ("matricula", "INT", 4), ("nome", "CHAR", 20)])
        self.assertEqual(t.esquema.tamanho, 28)
        self.assertEqual(executa("SELECT * FROM aluno", cat2, self.cache), "(0 linhas)")

    def test_sem_grava_tudo_o_disco_nao_viu(self):
        # o catálogo é de cache como qualquer página: sem gravar, outro processo não vê.
        # (executa() grava a cada CREATE; aqui chamamos o catálogo direto, sem o executor)
        self.cat.cria("volatil", [("a", "INT", 4)])
        with open(self.caminho, "r+b") as f:
            self.assertFalse(Catalogo(CachePaginas(f, 3)).existe("volatil"))

    def test_create_ja_grava_no_disco(self):
        # roda() chama grava_tudo(): o OK vale depois de um kill
        self.sql("CREATE TABLE a (x INT)")
        with open(self.caminho, "r+b") as f:
            self.assertTrue(Catalogo(CachePaginas(f, 3)).existe("a"))

    def test_insert_ja_grava_no_disco(self):
        self.sql("CREATE TABLE a (x INT)")
        self.sql("INSERT INTO a VALUES (7)")
        with open(self.caminho, "r+b") as f:
            c = CachePaginas(f, 3)
            self.assertEqual(executa("SELECT * FROM a", Catalogo(c), c), "7\n(1 linha)")

    def test_muitas_tabelas_enchem_o_catalogo_e_encadeiam_paginas(self):
        for i in range(300):
            self.assertEqual(self.sql(f"CREATE TABLE tab{i:03d} (a INT, b CHAR(10), c INT)"), "OK")
        self.assertGreater(len(self.cat._paginas), 1)
        for i in (0, 150, 299):
            self.sql(f"INSERT INTO tab{i:03d} VALUES ({i}, 'x{i}', {i * 2})")
        cat2 = self.abre()
        self.assertEqual(len(cat2.tabelas), 300)
        self.assertEqual(cat2._paginas, self.cat._paginas)
        for i in (0, 150, 299):
            self.assertEqual(executa(f"SELECT b FROM tab{i:03d}", cat2, self.cache), f"x{i}\n(1 linha)")

    def test_preserva_a_caixa_do_nome_e_a_ordem_das_colunas(self):
        self.sql("CREATE TABLE Aluno (Zeta INT, alfa CHAR(5), Meio INT)")
        t = self.abre().busca("aluno")
        self.assertEqual(t.nome, "Aluno")
        self.assertEqual([c[0] for c in t.colunas], ["Zeta", "alfa", "Meio"])

    def test_nome_acentuado_vai_e_volta(self):
        self.sql("CREATE TABLE avaliação (descrição CHAR(30))")
        self.sql("INSERT INTO avaliação VALUES ('prova de cálculo')")
        self.assertEqual(executa("SELECT descrição FROM avaliação", self.abre(), self.cache),
                         "prova de cálculo\n(1 linha)")

    def test_pagina_que_nao_e_de_catalogo_falha_alto(self):
        self.sql("CREATE TABLE a (x INT)")
        self.cache.grava_tudo()
        pagina = self.cat._paginas[0]
        with open(self.caminho, "r+b") as f:
            f.seek(pagina * PAGE_SIZE + 8)
            f.write(bytes([9]))                                  # tipo inválido
        with self.assertRaisesRegex(ValueError, "não é uma página de catálogo"):
            self.abre()

    def test_arquivo_que_nao_e_minidb(self):
        with open(self.caminho, "r+b") as f:
            f.write(b"NAOMINIDB")
        with self.assertRaisesRegex(ValueError, "numero magico"):
            self.abre()

    def test_arquivo_do_m3_ganha_catalogo_sem_perder_os_dados_antigos(self):
        # o M3 não conhecia o catálogo: bytes 24..27 da página 0 zerados
        import apoio
        apoio.cria_tabela_m1(self.caminho, 50)
        with open(self.caminho, "rb") as f:
            antes = f.read()[PAGE_SIZE:]                     # as páginas de dados, sem a 0
        cat = self.abre()
        self.assertEqual(cat.nomes(), [])
        self.sql("CREATE TABLE novo (a INT)")
        self.sql("INSERT INTO novo VALUES (1)")
        self.assertEqual(self.sql("SELECT * FROM novo"), "1\n(1 linha)")
        self.cache.grava_tudo()
        with open(self.caminho, "rb") as f:
            depois = f.read()[PAGE_SIZE:]
        self.assertEqual(depois[:len(antes)], antes)         # as páginas antigas ficaram como estavam


# ---------------------------------------------------------------- tabelas

class Tabelas(ComBanco):
    def test_corrente_de_paginas_com_registro_de_28_bytes(self):
        self.sql(CREATE_ALUNO)
        por_pagina = (PAGE_SIZE - 16) // 28                      # 145
        n = por_pagina * 3 + 7
        for i in range(1, n + 1):
            self.assertEqual(self.sql(f"INSERT INTO aluno VALUES ({i}, {i * 10}, 'a{i}')"), "OK 1")
        t = self.cat.busca("aluno")
        self.assertNotEqual(t.primeira, t.ultima)
        linhas = list(self.cat.varre(t))
        self.assertEqual(len(linhas), n)
        self.assertEqual(linhas[0], (1, 10, "a1"))
        self.assertEqual(linhas[-1], (n, n * 10, f"a{n}"))
        self.assertEqual([l[0] for l in linhas], list(range(1, n + 1)))      # em ordem
        self.assertEqual(self.cache.fixadas(), 0)

    def test_corrente_sobrevive_a_reabrir(self):
        self.sql("CREATE TABLE t (a INT)")
        n = 510 * 2 + 5                                           # 3 páginas de dados
        for i in range(n):
            self.sql(f"INSERT INTO t VALUES ({i})")
        cat2 = self.abre()
        self.assertEqual(cat2.busca("t").ultima, self.cat.busca("t").ultima)
        self.assertEqual(len(list(cat2.varre(cat2.busca("t")))), n)
        self.sql(f"INSERT INTO t VALUES ({n})")                   # continua de onde parou
        self.assertEqual(len(list(self.cat.varre(self.cat.busca("t")))), n + 1)

    def test_duas_tabelas_intercaladas_cada_uma_so_ve_as_suas(self):
        self.sql("CREATE TABLE a (x INT)")
        self.sql("CREATE TABLE b (y CHAR(8), z INT)")
        for i in range(1100):                                     # a enche mais de 2 páginas de 510
            self.sql(f"INSERT INTO a VALUES ({i})")
            if i % 100 == 0:
                self.sql(f"INSERT INTO b VALUES ('b{i}', {i})")
        # as páginas de a e de b se misturam no arquivo: só a corrente separa
        ta, tb = self.cat.busca("a"), self.cat.busca("b")
        self.assertEqual([l[0] for l in self.cat.varre(ta)], list(range(1100)))
        self.assertEqual(list(self.cat.varre(tb)), [(f"b{i}", i) for i in range(0, 1100, 100)])
        cat2 = self.abre()
        self.assertEqual(len(list(cat2.varre(cat2.busca("a")))), 1100)
        self.assertEqual(len(list(cat2.varre(cat2.busca("b")))), 11)

    def test_varredura_nao_ve_o_catalogo_nem_a_outra_tabela(self):
        # o minidb_cache.varre do M2 anda por todas as páginas e só pula tam_registro 0
        from minidb_cache import varre
        self.sql("CREATE TABLE a (x INT, y INT)")
        self.sql("CREATE TABLE b (x INT, y INT)")                 # mesmo esquema!
        self.sql("INSERT INTO a VALUES (1, 1)")
        self.sql("INSERT INTO b VALUES (2, 2)")
        self.assertEqual(self.sql("SELECT * FROM a"), "1|1\n(1 linha)")
        # o M2 misturaria as duas (por isso a corrente); o catálogo não
        self.assertEqual(sorted(varre(self.cache, EsquemaSQL([("x", "INT", 4), ("y", "INT", 4)]))),
                         [(1, 1), (2, 2)])

    def test_caracteres_e_zeros_da_ponta(self):
        self.sql("CREATE TABLE t (a CHAR(8), b INT)")
        self.sql("INSERT INTO t VALUES ('', 1)")
        self.sql("INSERT INTO t VALUES ('12345678', 2)")
        self.sql("INSERT INTO t VALUES ('ã', 3)")
        self.sql("INSERT INTO t VALUES ('a b', 4)")
        self.assertEqual(self.sql("SELECT * FROM t"), "|1\n12345678|2\nã|3\na b|4\n(4 linhas)")

    def test_inteiros_extremos_e_zero(self):
        self.sql("CREATE TABLE t (a INT)")
        for v in (0, 2147483647):
            self.sql(f"INSERT INTO t VALUES ({v})")
        self.assertEqual(self.sql("SELECT * FROM t"), "0\n2147483647\n(2 linhas)")

    def test_formato_em_disco_e_o_do_m1(self):
        # a primeira página de dados tem o cabeçalho de 16 bytes do M1 e o registro logo depois
        self.sql("CREATE TABLE t (a INT, b INT)")
        self.sql("INSERT INTO t VALUES (7, 9)")
        self.cache.grava_tudo()
        pg = self.cat.busca("t").primeira
        with open(self.caminho, "rb") as f:
            f.seek(pg * PAGE_SIZE)
            p = f.read(PAGE_SIZE)
        self.assertEqual(struct.unpack_from("<HHI", p, 0), (1, 8, pg))     # n_slots, tam_registro, num
        self.assertEqual(struct.unpack_from("<ii", p, 16), (7, 9))
        self.assertEqual(struct.unpack_from("<I", p, 8)[0], 0)             # sem próxima

    def test_select_vazio_e_singular(self):
        self.sql("CREATE TABLE t (a INT)")
        self.assertEqual(self.sql("SELECT * FROM t"), "(0 linhas)")
        self.sql("INSERT INTO t VALUES (1)")
        self.assertEqual(self.sql("SELECT a FROM t"), "1\n(1 linha)")

    def test_projecao_ordem_e_repeticao(self):
        self.sql(CREATE_ALUNO)
        self.sql("INSERT INTO aluno VALUES (1, 20260001, 'Ana')")
        self.assertEqual(self.sql("SELECT nome, id FROM aluno"), "Ana|1\n(1 linha)")
        self.assertEqual(self.sql("SELECT id, id FROM aluno"), "1|1\n(1 linha)")

    def test_nenhum_comando_deixa_pagina_fixada_nem_com_erro(self):
        for s in (CREATE_ALUNO, "INSERT INTO aluno VALUES (1, 2, 'a')", "SELECT * FROM aluno",
                  "SELECT x FROM aluno", "INSERT INTO aluno VALUES (1)", "SELECT * FROM z",
                  "SELECT * FROM aluno WHERE id = 1", "isso nem é SQL", "SELECT 'x"):
            self.sql(s)                                           # self.sql confere fixadas() == 0

    def test_com_2_frames_tambem_roda(self):
        # a corrente e o catálogo fixam uma página por vez
        self.FRAMES = 2
        self.abre()
        self.sql("CREATE TABLE t (a INT)")
        for i in range(1200):
            self.sql(f"INSERT INTO t VALUES ({i})")
        self.assertEqual(self.sql("SELECT * FROM t").splitlines()[-1], "(1200 linhas)")
        self.assertGreater(self.cache.expulsoes, 0)

    def test_gerador_abandonado_nao_deixa_pagina_fixada(self):
        self.sql("CREATE TABLE t (a INT)")
        for i in range(600):
            self.sql(f"INSERT INTO t VALUES ({i})")
        g = self.cat.varre(self.cat.busca("t"))
        next(g)
        self.assertEqual(self.cache.fixadas(), 0)
        g.close()

    def test_corrente_corrompida_com_volta_falha_alto(self):
        self.sql("CREATE TABLE t (a INT)")
        t = self.cat.busca("t")
        with self.cache.usa(t.primeira, escreve=True) as p:
            struct.pack_into("<I", p, 8, t.primeira)              # aponta para si mesma
        with self.assertRaisesRegex(ValueError, "dá voltas"):
            list(self.cat.varre(t))
        self.assertEqual(self.cache.fixadas(), 0)


# ---------------------------------------------------------------- o programa

def roda_programa(caminho, entrada):
    r = subprocess.run([sys.executable, PROGRAMA, caminho], input=entrada,
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    return r


class Programa(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "dados.db")

    def tearDown(self):
        self.dir.cleanup()

    def test_a_meta_do_slide_em_dois_processos(self):
        r1 = roda_programa(self.db, CREATE_ALUNO + "\n"
                           "INSERT INTO aluno VALUES (1, 20260001, 'Ana');\n"
                           "INSERT INTO aluno VALUES (2, 20260002, 'Bruno');\n")
        self.assertEqual(r1.stdout, "OK\nOK 1\nOK 1\n")
        r2 = roda_programa(self.db, "SELECT * FROM aluno;\n")           # outro processo
        self.assertEqual(r2.stdout, "1|20260001|Ana\n2|20260002|Bruno\n(2 linhas)\n")
        self.assertEqual((r1.returncode, r2.returncode, r1.stderr, r2.stderr), (0, 0, "", ""))

    def test_linhas_em_branco_sao_ignoradas_e_erro_nao_derruba_o_programa(self):
        r = roda_programa(self.db, "\n   \nSELECT * FROM x\n\nCREATE TABLE x (a INT)\nSELECT * FROM x\n")
        self.assertEqual(r.stdout, "ERRO semântico: a tabela x não existe\nOK\n(0 linhas)\n")
        self.assertEqual(r.returncode, 0)

    def test_cada_etapa_tem_o_seu_erro_na_saida(self):
        r = roda_programa(self.db, CREATE_ALUNO + "\n"
                          "SELECT * FROM aluno WHERE nome = 'O'Brien'\n"
                          "SELECT * FROM aluno WHERE id == 1\n"
                          "SELECT idade FROM aluno\n")
        etapas = [l.split(":")[0] for l in r.stdout.splitlines()[1:]]
        self.assertEqual(etapas, ["ERRO léxico", "ERRO sintático", "ERRO semântico"])

    def test_dados_chegam_ao_disco_mesmo_sem_fim_de_entrada_limpo(self):
        # o processo morre (kill -9) logo depois de responder "OK 1": o dado tem que estar lá
        p = subprocess.Popen([sys.executable, PROGRAMA, self.db], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True, encoding="utf-8")
        p.stdin.write("CREATE TABLE t (a INT)\nINSERT INTO t VALUES (42)\n")
        p.stdin.flush()
        self.assertEqual(p.stdout.readline(), "OK\n")
        self.assertEqual(p.stdout.readline(), "OK 1\n")
        p.kill()
        p.wait()
        p.stdin.close()
        p.stdout.close()
        self.assertEqual(roda_programa(self.db, "SELECT * FROM t\n").stdout, "42\n(1 linha)\n")

    def test_acentos_na_entrada_e_na_saida(self):
        roda_programa(self.db, "CREATE TABLE t (n CHAR(10))\nINSERT INTO t VALUES ('João')\n")
        self.assertEqual(roda_programa(self.db, "SELECT * FROM t\n").stdout, "João\n(1 linha)\n")

    def test_arquivo_que_nao_e_minidb_nao_e_alterado(self):
        with open(self.db, "wb") as f:
            f.write(b"isto e um texto qualquer\n")
        r = roda_programa(self.db, "SELECT * FROM t\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("não é um arquivo do minidb", r.stderr)
        with open(self.db, "rb") as f:
            self.assertEqual(f.read(), b"isto e um texto qualquer\n")

    def test_arquivo_vazio_e_tratado_como_novo(self):
        open(self.db, "wb").close()
        r = roda_programa(self.db, "CREATE TABLE t (a INT)\n")
        self.assertEqual(r.stdout, "OK\n")

    def test_sem_argumento_mostra_o_uso(self):
        r = subprocess.run([sys.executable, PROGRAMA], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("./minidb dados.db", r.stdout)

    def test_tres_processos_em_sequencia_acumulam(self):
        roda_programa(self.db, "CREATE TABLE t (a INT)\nINSERT INTO t VALUES (1)\n")
        roda_programa(self.db, "INSERT INTO t VALUES (2)\n")
        roda_programa(self.db, "INSERT INTO t VALUES (3)\n")
        self.assertEqual(roda_programa(self.db, "SELECT * FROM t\n").stdout, "1\n2\n3\n(3 linhas)\n")


# ---------------------------------------------------------------- exercício 2.2

class Injecao(ComBanco):
    def test_o_payload_do_exercicio_2_2(self):
        self.sql(CREATE_ALUNO)
        self.sql("INSERT INTO aluno VALUES (1, 20260001, 'Ana')")
        nome = "x' OR '1'='1"
        consulta = "SELECT * FROM aluno WHERE nome = '" + nome + "'"
        t = tokeniza(consulta)
        # o texto do usuário virou gramática: as aspas dele fecharam o texto e o OR é token de fora
        self.assertEqual(t[-6:], [("TEXTO", "x"), ("NOME", "OR"), ("TEXTO", "1"),
                                  ("SIMBOLO", "="), ("TEXTO", "1"), ("FIM", None)])
        self.assertEqual(self.sql(consulta), "ERRO sintático: esperava FIM, veio 'OR'")

    def test_nao_e_protecao_a_gramatica_so_nao_tem_o_que_atacar_ainda(self):
        # com o OR fora da gramática o ataque cai no parser. Mas a fronteira
        # dado/comando já foi apagada: o mesmo mecanismo ALTERA um INSERT, que
        # a gramática aceita, e só a conferência de colunas (semântica) o pega.
        self.sql(CREATE_ALUNO)
        nome = "Zé', 'extra"
        consulta = "INSERT INTO aluno VALUES (9, 9, '" + nome + "')"
        self.assertEqual(len(analisa(consulta)["valores"]), 4)      # o parser aceitou: 4 valores
        self.assertTrue(self.sql(consulta).startswith("ERRO semântico"))
        # numa tabela com 4 colunas o mesmo texto GRAVARIA um valor que o usuário inventou
        self.sql("CREATE TABLE quatro (id INT, a CHAR(10), b CHAR(10), c CHAR(10))")
        c2 = "INSERT INTO quatro VALUES (1, 'a', '" + nome + "')"
        self.assertEqual(self.sql(c2), "OK 1")
        self.assertEqual(self.sql("SELECT * FROM quatro"), "1|a|Zé|extra\n(1 linha)")


if __name__ == "__main__":
    unittest.main()
