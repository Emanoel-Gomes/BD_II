"""
catalogo.py - M4, parte 2: o catálogo (quem sabe onde cada tabela mora) e as
duas operações de tabela que o executor usa: inserir uma linha e varrer.

A árvore sintática traz o NOME da tabela, mas o nome sozinho não diz onde ela
mora nem com quais colunas. Isso fica no disco, no catálogo, e é por ele que
um segundo processo sabe que `aluno` existe sem ter visto o CREATE TABLE.

Onde as coisas ficam (tudo pelo cache do M2; o formato dos dados é o do M1):

    página 0    bytes 0..17   o que o M1 já usa
                bytes 18..23  raiz do índice B+ (M3)
                bytes 24..27  NOVO: página do 1º catálogo (0 = ainda não tem)

    página de catálogo (tipo 3), 16 bytes de cabeçalho como as outras:
        0..1  n_entradas (u16)      2..3  marca 0 (u16): "não é página de dados",
        4..7  num_pagina (u32)            o mesmo teste que o M1/M2 já faz para
        8     tipo = 3 (u8)               pular os nós do índice
        12..15  extra (u32): próxima página de catálogo (0 = última)
        16..  entradas, uma atrás da outra, de tamanho variável:
            u8 len + nome da tabela (utf-8)
            u8 n_colunas, u32 primeira página de dados, u32 última
            n_colunas x ( u8 len + nome, u8 tipo (1 INT, 2 CHAR), u16 tamanho )

    página de dados de uma tabela: o cabeçalho do M1 + NOVO nos bytes 8..11 a
        próxima página DA MESMA TABELA (0 = última). Os bytes 8..15 eram
        reservados e zerados no M1, então um arquivo antigo continua valendo.

Por que encadear as páginas da tabela: com mais de uma tabela no arquivo, as
páginas se misturam (aluno, curso, aluno, ...). A varredura do M1 anda do 1 ao
total e não saberia de quem é cada uma. Com `primeira` no catálogo e a
corrente de próximas, a varredura de uma tabela lê só as páginas dela.
"""

import struct

from erros import ErroSemantico
from minidb import Esquema, HEADER_SIZE, PAGE_SIZE, le_cabecalho
from minidb_cache import aloca, insere, le_metadados

TIPO_CATALOGO = 3
OFF_CATALOGO = 24            # na página 0
OFF_PROXIMA = 8              # na página de dados: próxima página da tabela
MAX_NOME = 32                # bytes, tabela ou coluna
INT_MIN, INT_MAX = -(2 ** 31), 2 ** 31 - 1
_CAB = struct.Struct("<HHIB3xI")
assert _CAB.size == HEADER_SIZE
_COD_TIPO = {"INT": 1, "CHAR": 2}
_TIPO_COD = {1: "INT", 2: "CHAR"}


# ---------- o esquema com tipos de SQL ----------

class EsquemaSQL(Esquema):
    """O Esquema do M1 com as colunas como o parser as entrega:
    [("id", "INT", 4), ("nome", "CHAR", 20)]. INT vira i (4 bytes) e CHAR(n)
    vira ns (n bytes, sempre n, completados com zeros): o registro continua
    de tamanho fixo, e `tamanho` continua derivado das colunas."""

    def __init__(self, colunas):
        super().__init__([(nome, "i" if tipo == "INT" else f"{tam}s")
                          for nome, tipo, tam in colunas])
        self.colunas = list(colunas)             # os trios, não os pares do M1

    def serializa(self, valores):
        if len(valores) != len(self.colunas):
            raise ValueError(f"{len(self.colunas)} colunas, {len(valores)} valores")
        brutos = []
        for (nome, tipo, tam), v in zip(self.colunas, valores):
            if tipo == "INT":
                if not isinstance(v, int) or isinstance(v, bool) or not INT_MIN <= v <= INT_MAX:
                    raise ValueError(f"coluna {nome}: {v!r} não é um INT de 32 bits")
                brutos.append(v)
            else:
                b = v.encode("utf-8") if isinstance(v, str) else None
                if b is None or len(b) > tam or b"\x00" in b:
                    raise ValueError(f"coluna {nome}: {v!r} não cabe em CHAR({tam})")
                brutos.append(b)
        return super().serializa(brutos)

    def desserializa(self, dados):
        brutos = super().desserializa(dados)
        return tuple(b.rstrip(b"\x00").decode("utf-8") if tipo == "CHAR" else b
                     for (_, tipo, _), b in zip(self.colunas, brutos))


class Tabela:
    """Uma entrada do catálogo, em memória."""

    __slots__ = ("nome", "colunas", "primeira", "ultima", "esquema", "_pos")

    def __init__(self, nome, colunas, primeira, ultima, pos):
        self.nome, self.colunas = nome, list(colunas)
        self.primeira, self.ultima = primeira, ultima
        self.esquema = EsquemaSQL(self.colunas)
        self._pos = pos                          # (página do catálogo, deslocamento da entrada)

    def indice_coluna(self, nome):
        """Posição da coluna (sem diferenciar maiúsculas) ou None."""
        nome = nome.lower()
        for i, (n, _, _) in enumerate(self.colunas):
            if n.lower() == nome:
                return i
        return None


def _codifica(nome, colunas, primeira, ultima):
    nb = nome.encode("utf-8")
    out = bytes([len(nb)]) + nb + struct.pack("<BII", len(colunas), primeira, ultima)
    for cn, tipo, tam in colunas:
        cb = cn.encode("utf-8")
        out += bytes([len(cb)]) + cb + struct.pack("<BH", _COD_TIPO[tipo], tam)
    return out


def tamanho_entrada(nome, colunas):
    return len(_codifica(nome, colunas, 0, 0))


# ---------- o catálogo ----------

class Catalogo:
    """Abre (ou cria, se o arquivo ainda não tem) o catálogo de um arquivo
    minidb. Fica em memória um dicionário nome -> Tabela, lido do disco na
    abertura e mantido igual ao disco a cada mudança (uma thread, um processo)."""

    def __init__(self, cache):
        self.cache = cache
        self.tabelas = {}                        # nome em minúsculas -> Tabela
        self._paginas = []                       # páginas de catálogo, em ordem
        self._usado = {}                         # página de catálogo -> bytes usados
        self._carrega()

    # ----- consulta -----

    def existe(self, nome):
        return nome.lower() in self.tabelas

    def busca(self, nome):
        """A Tabela, ou ErroSemantico: é a pergunta "a tabela existe?"."""
        t = self.tabelas.get(nome.lower())
        if t is None:
            raise ErroSemantico(f"a tabela {nome} não existe")
        return t

    def nomes(self):
        return [t.nome for t in self.tabelas.values()]

    # ----- criar tabela -----

    def cria(self, nome, colunas):
        """Cria a tabela: uma página de dados e a entrada no catálogo. O que
        pode estar errado (nome repetido, tamanho) o executor já conferiu."""
        esquema = EsquemaSQL(colunas)
        primeira = aloca(self.cache, esquema.tamanho)
        entrada = _codifica(nome, colunas, primeira, primeira)
        pagina = self._pagina_com_espaco(len(entrada))
        off = self._usado[pagina]
        with self.cache.usa(pagina, escreve=True) as p:
            p[off:off + len(entrada)] = entrada
            n = struct.unpack_from("<H", p, 0)[0]
            struct.pack_into("<H", p, 0, n + 1)
        self._usado[pagina] = off + len(entrada)
        t = Tabela(nome, colunas, primeira, primeira, (pagina, off))
        self.tabelas[nome.lower()] = t
        return t

    # ----- linhas -----

    def insere(self, tabela, valores):
        """Grava uma linha na última página da tabela, ou numa nova (que entra
        no fim da corrente). Devolve o RID (página, slot), como o M1."""
        tabela.esquema.serializa(valores)        # confere ANTES de mexer em qualquer página
        rid, pagina = insere(self.cache, tabela.esquema, valores, tabela.ultima)
        if pagina != tabela.ultima:              # a última encheu: alocou outra
            with self.cache.usa(tabela.ultima, escreve=True) as p:
                struct.pack_into("<I", p, OFF_PROXIMA, pagina)
            self._muda_ultima(tabela, pagina)
        return rid

    def varre(self, tabela):
        """As linhas da tabela, em ordem de inserção: segue a corrente de
        páginas a partir de `primeira`. Cada página é fixada, copiada e solta
        antes de devolver as linhas, então nenhuma fixação fica aberta com o
        chamador."""
        _, _, total = le_metadados(self.cache)
        pagina, vistas = tabela.primeira, 0
        while pagina != 0:
            vistas += 1
            if vistas >= total:
                raise ValueError(f"a corrente de páginas da tabela {tabela.nome} dá voltas")
            with self.cache.usa(pagina) as buf:
                n_slots, tam, num = le_cabecalho(buf)
                if tam != tabela.esquema.tamanho or num != pagina:
                    raise ValueError(f"página {pagina} não é de dados da tabela {tabela.nome} "
                                     f"(tam_registro {tam}, num_pagina {num})")
                linhas = [tabela.esquema.desserializa(
                              bytes(buf[HEADER_SIZE + s * tam:HEADER_SIZE + (s + 1) * tam]))
                          for s in range(n_slots)]
                proxima = struct.unpack_from("<I", buf, OFF_PROXIMA)[0]
            yield from linhas
            pagina = proxima

    # ----- páginas de catálogo -----

    def _muda_ultima(self, tabela, pagina):
        cat, off = tabela._pos
        pos_ultima = off + 1 + len(tabela.nome.encode("utf-8")) + 1 + 4
        with self.cache.usa(cat, escreve=True) as p:
            struct.pack_into("<I", p, pos_ultima, pagina)
        tabela.ultima = pagina

    def _nova_pagina_catalogo(self):
        """Reserva uma página no fim do arquivo (sobe o total na página 0, como
        o aloca do M1) e a inicializa como página de catálogo vazia."""
        _, _, total = le_metadados(self.cache)
        with self.cache.usa(0, escreve=True) as p0:
            struct.pack_into("<I", p0, 14, total + 1)
        with self.cache.usa(total, escreve=True) as p:
            p[:] = bytes(PAGE_SIZE)
            _CAB.pack_into(p, 0, 0, 0, total, TIPO_CATALOGO, 0)
        self._usado[total] = HEADER_SIZE
        return total

    def _pagina_com_espaco(self, tamanho):
        if HEADER_SIZE + tamanho > PAGE_SIZE:
            raise ValueError("entrada maior que uma página de catálogo")
        ultima = self._paginas[-1]
        if self._usado[ultima] + tamanho <= PAGE_SIZE:
            return ultima
        nova = self._nova_pagina_catalogo()
        with self.cache.usa(ultima, escreve=True) as p:     # encadeia: extra = próxima
            struct.pack_into("<I", p, 12, nova)
        self._paginas.append(nova)
        return nova

    def _carrega(self):
        le_metadados(self.cache)                 # confere o número mágico da página 0
        with self.cache.usa(0) as p0:
            pagina = struct.unpack_from("<I", p0, OFF_CATALOGO)[0]
        if pagina == 0:                          # arquivo novo (ou do M1 a M3): cria o catálogo
            pagina = self._nova_pagina_catalogo()
            with self.cache.usa(0, escreve=True) as p0:
                struct.pack_into("<I", p0, OFF_CATALOGO, pagina)
            self._paginas = [pagina]
            return
        vistas = set()
        while pagina != 0:
            if pagina in vistas:
                raise ValueError("a corrente de páginas de catálogo dá voltas")
            vistas.add(pagina)
            self._paginas.append(pagina)
            pagina = self._le_pagina_catalogo(self._paginas[-1])

    def _le_pagina_catalogo(self, pagina):
        """Lê as entradas de uma página de catálogo para a memória. Devolve a
        próxima página de catálogo (0 = última)."""
        with self.cache.usa(pagina) as p:
            n, marca, num, tipo, proxima = _CAB.unpack_from(p, 0)
            if marca != 0 or tipo != TIPO_CATALOGO or num != pagina:
                raise ValueError(f"página {pagina} não é uma página de catálogo "
                                 f"(tipo {tipo}, marca {marca}, num_pagina {num})")
            off = HEADER_SIZE
            for _ in range(n):
                ini = off
                ln = p[off]
                nome = bytes(p[off + 1:off + 1 + ln]).decode("utf-8")
                off += 1 + ln
                ncol, primeira, ultima = struct.unpack_from("<BII", p, off)
                off += 9
                colunas = []
                for _ in range(ncol):
                    lc = p[off]
                    cn = bytes(p[off + 1:off + 1 + lc]).decode("utf-8")
                    cod, tam = struct.unpack_from("<BH", p, off + 1 + lc)
                    colunas.append((cn, _TIPO_COD[cod], tam))
                    off += 1 + lc + 3
                self.tabelas[nome.lower()] = Tabela(nome, colunas, primeira, ultima, (pagina, ini))
            self._usado[pagina] = off
        return proxima
