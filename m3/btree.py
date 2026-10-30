"""
btree.py - M3: árvore B+ do minidb.

Um índice que leva de uma chave (o id do aluno) ao RID do registro, que é
(página, slot) como o M1 gravou. Assim achar um registro não precisa ler a
tabela: desce a árvore e vai direto à página certa.

Regras (slides "Árvore B e árvore B+" e "Nós internos e folhas"):

    - cada nó ocupa exatamente uma página de 4096 bytes
    - nó interno: só chaves, para guiar a descida
        à esquerda da chave k_i ficam as chaves menores que k_i,
        e k_i e as maiores vão para a direita (filho i+1)
    - folha: chave -> (página, slot) e um ponteiro para a próxima folha
    - todas as folhas estão na mesma profundidade
    - sem remoção (fora do M3)

Quem fala com o disco é o cache do M2: a árvore pede páginas com fixa/solta
e não sabe o que é arquivo. Também não sabe o que é SQL nem o que é uma
tabela: ver minidb_indice.py para a ligação com o M1.

Como um nó é gravado na página (detalhes e tabela no NOTES.md):

    bytes   0..1   n_chaves       H   (no M1 este lugar é o n_slots)
            2..3   zero           H   (no M1 é o tam_registro, que nunca é 0:
                                       é a marca de "esta página não é de dados")
            4..7   num_pagina     I   número da própria página (igual ao M1)
            8      tipo           B   1 = folha, 2 = nó interno
            9..11  (reservado)
            12..15 extra          I   folha: próxima folha (0 = última)
                                      interno: filho 0 (o mais à esquerda)
            16..   entradas
                folha:   n x (chave i32, página u32, slot u16)   10 bytes
                interno: n x (chave i32, filho u32)               8 bytes
                         o filho da entrada i é o filho i+1

Onde fica a raiz: na página 0, a partir do byte 18 (o M1 usa até o 17):
    bytes 18..21  raiz         I   0 = a tabela ainda não tem índice
          22..23  max_chaves   H   0 = o que cabe na página
A página 0 nunca é nó, então 0 serve de "nulo".
"""

import struct
from bisect import bisect_left, bisect_right

from minidb_cache import le_metadados
from minidb_m1 import HEADER_SIZE, PAGE_SIZE

FOLHA = 1
INTERNO = 2

_CAB = struct.Struct("<HHIB3xI")         # 16 bytes, mesmo tamanho do cabeçalho do M1
_ENT_FOLHA = struct.Struct("<iIH")       # chave, página, slot
_ENT_INTERNO = struct.Struct("<iI")      # chave, filho da direita
assert _CAB.size == HEADER_SIZE

TAM_ENT_FOLHA = _ENT_FOLHA.size          # 10
TAM_ENT_INTERNO = _ENT_INTERNO.size      # 8
CAP_FOLHA = (PAGE_SIZE - HEADER_SIZE) // TAM_ENT_FOLHA        # 408 chaves
CAP_INTERNO = (PAGE_SIZE - HEADER_SIZE) // TAM_ENT_INTERNO    # 510 chaves

OFF_RAIZ = 18      # na página 0
OFF_MAX = 22
CHAVE_MIN, CHAVE_MAX = -(2 ** 31), 2 ** 31 - 1


class ChaveDuplicada(KeyError):
    """A chave já está no índice. O índice do minidb é único (é o id)."""


class SemIndice(RuntimeError):
    """A tabela (arquivo) ainda não tem índice criado."""


class No:
    """Um nó decodificado, em memória. A página é só a forma gravada dele.

    folha:   chaves[i] -> rids[i]; `proxima` é a próxima folha (0 = nenhuma)
    interno: len(filhos) == len(chaves) + 1; filhos[0] fica à esquerda de
             chaves[0], filhos[i+1] à direita de chaves[i]
    """

    __slots__ = ("tipo", "pagina", "chaves", "rids", "filhos", "proxima")

    def __init__(self, tipo, pagina, chaves=None, rids=None, filhos=None, proxima=0):
        self.tipo = tipo
        self.pagina = pagina
        self.chaves = chaves if chaves is not None else []
        self.rids = rids if rids is not None else []
        self.filhos = filhos if filhos is not None else []
        self.proxima = proxima

    @property
    def folha(self):
        return self.tipo == FOLHA


# ---------- o nó dentro da página ----------

def decodifica_no(buf, pagina):
    """bytes da página -> No. Confere o tipo e o número da página: se a
    página não é um nó (ou é de outro lugar), falha alto em vez de seguir."""
    n, marca, num, tipo, extra = _CAB.unpack_from(buf, 0)
    if marca != 0 or tipo not in (FOLHA, INTERNO) or num != pagina:
        raise ValueError(f"página {pagina} não é um nó de árvore B+ (tipo {tipo}, marca {marca}, num_pagina {num})")
    if tipo == FOLHA:
        if n > CAP_FOLHA:
            raise ValueError(f"folha {pagina} com {n} chaves, cabem {CAP_FOLHA}")
        fim = HEADER_SIZE + n * TAM_ENT_FOLHA
        chaves, rids = [], []
        for k, pg, sl in _ENT_FOLHA.iter_unpack(bytes(buf[HEADER_SIZE:fim])):
            chaves.append(k)
            rids.append((pg, sl))
        return No(FOLHA, pagina, chaves=chaves, rids=rids, proxima=extra)
    if n > CAP_INTERNO:
        raise ValueError(f"nó interno {pagina} com {n} chaves, cabem {CAP_INTERNO}")
    fim = HEADER_SIZE + n * TAM_ENT_INTERNO
    chaves, filhos = [], [extra]
    for k, filho in _ENT_INTERNO.iter_unpack(bytes(buf[HEADER_SIZE:fim])):
        chaves.append(k)
        filhos.append(filho)
    return No(INTERNO, pagina, chaves=chaves, filhos=filhos)


def codifica_no(no, buf):
    """No -> bytes, no lugar, no buffer do frame (a mesma bytearray)."""
    n = len(no.chaves)
    if no.folha:
        assert n <= CAP_FOLHA and len(no.rids) == n
        _CAB.pack_into(buf, 0, n, 0, no.pagina, FOLHA, no.proxima)
        for i in range(n):
            pg, sl = no.rids[i]
            _ENT_FOLHA.pack_into(buf, HEADER_SIZE + i * TAM_ENT_FOLHA, no.chaves[i], pg, sl)
        fim = HEADER_SIZE + n * TAM_ENT_FOLHA
    else:
        assert n <= CAP_INTERNO and len(no.filhos) == n + 1
        _CAB.pack_into(buf, 0, n, 0, no.pagina, INTERNO, no.filhos[0])
        for i in range(n):
            _ENT_INTERNO.pack_into(buf, HEADER_SIZE + i * TAM_ENT_INTERNO, no.chaves[i], no.filhos[i + 1])
        fim = HEADER_SIZE + n * TAM_ENT_INTERNO
    buf[fim:] = bytes(PAGE_SIZE - fim)    # sobra zerada: o mesmo nó dá os mesmos bytes


# ---------- a árvore ----------

class ArvoreBMais:
    """Índice B+ sobre o cache do M2. Use `ArvoreBMais.cria(cache)` na
    primeira vez e `ArvoreBMais.abre(cache)` nas seguintes.

    Nenhum método deixa página fixada ao terminar (nem com erro): `cache.fixadas()`
    volta a 0. No máximo duas páginas ficam fixadas ao mesmo tempo, então até
    um cache de 3 frames aguenta uma árvore de qualquer altura.
    """

    def __init__(self, cache, raiz, max_chaves):
        self.cache = cache
        self.raiz = raiz
        self.max_chaves = max_chaves                      # 0 = o que cabe na página
        self.max_folha = max_chaves or CAP_FOLHA
        self.max_interno = max_chaves or CAP_INTERNO

    # ----- criar e abrir -----

    @classmethod
    def cria(cls, cache, max_chaves=None):
        """Cria o índice vazio: uma folha, que também é a raiz. `max_chaves`
        (2 a 408) limita as chaves por nó, para exercitar divisões com poucos
        dados, como o '3 chaves por nó' dos exercícios; None = o que cabe."""
        if max_chaves is not None and not 2 <= max_chaves <= CAP_FOLHA:
            raise ValueError(f"max_chaves precisa estar entre 2 e {CAP_FOLHA}")
        if cls._le_raiz(cache)[0] != 0:
            raise RuntimeError("esta tabela já tem índice")
        arv = cls(cache, 0, max_chaves or 0)
        raiz = arv._aloca()
        arv._grava(No(FOLHA, raiz))
        arv._muda_raiz(raiz)
        return arv

    @classmethod
    def abre(cls, cache):
        raiz, max_chaves = cls._le_raiz(cache)
        if raiz == 0:
            raise SemIndice("a tabela não tem índice (use ArvoreBMais.cria)")
        return cls(cache, raiz, max_chaves)

    @staticmethod
    def _le_raiz(cache):
        le_metadados(cache)               # confere o número mágico da página 0
        with cache.usa(0) as p0:
            return struct.unpack_from("<IH", p0, OFF_RAIZ)

    def _muda_raiz(self, raiz):
        """Registra a raiz na página 0 (suja: vai ao disco na expulsão ou no
        grava_tudo, como qualquer outra página)."""
        with self.cache.usa(0, escreve=True) as p0:
            struct.pack_into("<IH", p0, OFF_RAIZ, raiz, self.max_chaves)
        self.raiz = raiz

    # ----- páginas -----

    def _le(self, pagina):
        """Fixa, decodifica para um No, solta. Uma página fixada por vez."""
        with self.cache.usa(pagina) as buf:
            return decodifica_no(buf, pagina)

    def _grava(self, no):
        with self.cache.usa(no.pagina, escreve=True) as buf:
            codifica_no(no, buf)

    def _aloca(self):
        """Reserva uma página nova no fim do arquivo (sobe o total da página 0).
        O conteúdo vem depois, com _grava."""
        _, _, total = le_metadados(self.cache)
        with self.cache.usa(0, escreve=True) as p0:
            struct.pack_into("<I", p0, 14, total + 1)
        return total

    # ----- busca -----

    def _desce_ate_folha(self, chave):
        """A descida do slide: a cada nó interno, bisect_right escolhe o filho
        (chave == k_i vai para a direita de k_i). Devolve a folha."""
        no = self._le(self.raiz)
        while not no.folha:
            no = self._le(no.filhos[bisect_right(no.chaves, chave)])
        return no

    def busca(self, chave):
        """RID (página, slot) da chave, ou None. Lê `altura()` páginas."""
        folha = self._desce_ate_folha(chave)
        i = bisect_left(folha.chaves, chave)
        if i < len(folha.chaves) and folha.chaves[i] == chave:
            return folha.rids[i]
        return None

    def faixa(self, minimo, maximo):
        """Gerador de (chave, rid) com minimo <= chave <= maximo, em ordem.
        Desce uma vez até a folha de `minimo` e segue o encadeamento das
        folhas, sem voltar à raiz; para na primeira chave acima de `maximo`."""
        folha = self._desce_ate_folha(minimo)
        while True:
            for k, rid in zip(folha.chaves, folha.rids):
                if k > maximo:
                    return
                if k >= minimo:
                    yield k, rid
            if folha.proxima == 0:
                return
            folha = self._le(folha.proxima)

    # ----- inserção -----

    def insere(self, chave, rid):
        """Insere chave -> rid. Se a folha estourar `max_chaves`, divide: a
        folha vira duas, o primeiro valor da nova sobe como separador, e se o
        pai estourar divide também, até a raiz, que então ganha um nível."""
        if not CHAVE_MIN <= chave <= CHAVE_MAX:
            raise ValueError(f"chave {chave} fora do intervalo de 32 bits")
        pg, sl = rid
        if not (0 <= pg < 2 ** 32 and 0 <= sl < 2 ** 16):
            raise ValueError(f"rid {rid} não cabe em (u32, u16)")

        # desce guardando o caminho: (nó interno, índice do filho escolhido).
        # O que foi lido aqui é o que vai ser alterado na subida: ninguém mexe
        # nesses nós entre a descida e a subida (uma thread só).
        caminho = []
        no = self._le(self.raiz)
        while not no.folha:
            i = bisect_right(no.chaves, chave)
            caminho.append((no, i))
            no = self._le(no.filhos[i])

        j = bisect_left(no.chaves, chave)
        if j < len(no.chaves) and no.chaves[j] == chave:
            raise ChaveDuplicada(chave)          # antes de qualquer alteração
        no.chaves.insert(j, chave)
        no.rids.insert(j, (pg, sl))

        if len(no.chaves) <= self.max_folha:     # cabe: nada de divisão
            self._grava(no)
            return

        # ---- divisão da folha: [a b | c d], o separador é o c (cópia) ----
        meio = len(no.chaves) // 2
        direita = No(FOLHA, self._aloca(),
                     chaves=no.chaves[meio:], rids=no.rids[meio:], proxima=no.proxima)
        no.chaves, no.rids, no.proxima = no.chaves[:meio], no.rids[:meio], direita.pagina
        self._grava(direita)
        self._grava(no)
        separador, novo, esquerdo = direita.chaves[0], direita.pagina, no.pagina

        # ---- sobe: cada pai recebe (separador, novo filho) ----
        while caminho:
            pai, i = caminho.pop()
            pai.chaves.insert(i, separador)
            pai.filhos.insert(i + 1, novo)
            if len(pai.chaves) <= self.max_interno:
                self._grava(pai)
                return
            # divisão do nó interno: a chave do meio SOBE (não fica em nenhum
            # dos dois), ao contrário da folha, onde o separador é copiado.
            meio = len(pai.chaves) // 2
            sobe = pai.chaves[meio]
            direita = No(INTERNO, self._aloca(),
                         chaves=pai.chaves[meio + 1:], filhos=pai.filhos[meio + 1:])
            pai.chaves, pai.filhos = pai.chaves[:meio], pai.filhos[:meio + 1]
            self._grava(direita)
            self._grava(pai)
            separador, novo, esquerdo = sobe, direita.pagina, pai.pagina

        # a divisão chegou à raiz: raiz nova com um separador e dois filhos
        nova_raiz = No(INTERNO, self._aloca(), chaves=[separador], filhos=[esquerdo, novo])
        self._grava(nova_raiz)
        self._muda_raiz(nova_raiz.pagina)

    # ----- inspeção (testes, demos, NOTES) -----

    def altura(self):
        """Níveis da raiz até a folha, contando os dois: raiz-folha = 1.
        É também quantas páginas uma busca lê."""
        h, no = 1, self._le(self.raiz)
        while not no.folha:
            no = self._le(no.filhos[0])
            h += 1
        return h

    def niveis(self):
        """A árvore como listas de listas de chaves, um item por nível
        (de cima para baixo, esquerda para direita): para comparar com o
        desenho do gabarito."""
        atual, saida = [self._le(self.raiz)], []
        while atual:
            saida.append([list(n.chaves) for n in atual])
            if atual[0].folha:
                break
            atual = [self._le(f) for n in atual for f in n.filhos]
        return saida

    def folhas(self):
        """Percorre as folhas pelo encadeamento, da primeira à última."""
        no = self._le(self.raiz)
        while not no.folha:
            no = self._le(no.filhos[0])
        while True:
            yield no
            if no.proxima == 0:
                return
            no = self._le(no.proxima)

    def desenha(self):
        linhas = []
        for i, nivel in enumerate(self.niveis()):
            rotulo = "raiz " if i == 0 else ("folhas" if i == len(self.niveis()) - 1 else "interno")
            linhas.append(f"{rotulo:>7}  " + "  ".join("[" + " ".join(map(str, c)) + "]" for c in nivel))
        return "\n".join(linhas)

    def confere(self):
        """Verifica as invariantes e devolve (altura, total de chaves); levanta
        AssertionError dizendo qual quebrou. Usada pelos testes depois de
        inserções aleatórias."""
        folhas_vistas = []
        prof_folha = set()

        def desce(pagina, lo, hi, prof, eh_raiz):
            no = self._le(pagina)
            ks = no.chaves
            assert ks == sorted(set(ks)), f"nó {pagina}: chaves fora de ordem ou repetidas {ks}"
            for k in ks:
                assert (lo is None or k >= lo) and (hi is None or k < hi), \
                    f"nó {pagina}: chave {k} fora do intervalo [{lo}, {hi}) que o pai promete"
            limite = self.max_folha if no.folha else self.max_interno
            assert len(ks) <= limite, f"nó {pagina} com {len(ks)} chaves, máximo {limite}"
            if not eh_raiz:
                assert len(ks) >= 1, f"nó {pagina} vazio"
            if no.folha:
                prof_folha.add(prof)
                folhas_vistas.append(no)
                return
            assert len(no.filhos) == len(ks) + 1, f"nó {pagina}: {len(no.filhos)} filhos para {len(ks)} chaves"
            for i, filho in enumerate(no.filhos):
                f_lo = lo if i == 0 else ks[i - 1]
                f_hi = hi if i == len(ks) else ks[i]
                desce(filho, f_lo, f_hi, prof + 1, False)

        desce(self.raiz, None, None, 1, True)
        assert len(prof_folha) == 1, f"folhas em profundidades diferentes: {sorted(prof_folha)}"
        encadeadas = [f.pagina for f in self.folhas()]
        assert encadeadas == [f.pagina for f in folhas_vistas], "encadeamento das folhas não segue a ordem da árvore"
        todas = [k for f in folhas_vistas for k in f.chaves]
        assert todas == sorted(todas), "chaves das folhas fora de ordem"
        return prof_folha.pop(), len(todas)
