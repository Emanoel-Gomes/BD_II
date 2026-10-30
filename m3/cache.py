"""
cache.py - M2: cache de páginas (buffer pool) do minidb.

Fica entre o resto do banco e o arquivo do M1. Quem precisa de uma página
pede ao cache (fixa), e não ao arquivo. Reaproveita le_pagina/escreve_pagina
do minidb_m1.py sem mexer neles: o cache é a única camada que fala com eles.

Estrutura (o desenho do slide "Onde o cache entra"):

    frames   lista de `capacidade` posições de memória, cada uma com uma
             página de 4096 bytes, mais 3 metadados: qual página guarda,
             quantos usuários a fixaram (pins) e se está suja.
    tabela   dict  número da página -> índice do frame  (é o "verificar")
    livres   frames que ainda não guardam nada            (é o "adicionar")
    ordem    OrderedDict das páginas residentes, da mais antiga para a mais
             nova; define quem sai quando enche            (é o "resolver")

Política de inserção: a página entra por demanda, quando dá falta.
Política de remoção: a mais antiga da `ordem` que não esteja fixada.
    lru  - cada acerto leva a página para o fim da fila (é o que o M2 pede)
    fifo - o acerto não mexe na fila (só para comparar)

Uma thread só. Sem trava (latch) nenhuma: concorrência fica fora do M2.
"""

from collections import OrderedDict
from contextlib import contextmanager

from minidb_m1 import PAGE_SIZE, escreve_pagina, le_pagina


# 32 frames = 128 KiB. A tabela de 10 mil registros do M1 ocupa 21 páginas; com
# LRU e varredura repetida o cache só ajuda quando a tabela INTEIRA cabe (0% de
# acertos com 20 frames, 90% com 21 - ver atividade_2/comparacao.py). Os 11
# frames de folga deixam a tabela crescer até ~15 mil registros (31 páginas de
# dados) sem perder o cache, e dão lugar às páginas do índice do M3, que vão
# dividir este mesmo cache. Os testes usam 3 de propósito: com capacidade
# grande a expulsão nunca acontece.
CAPACIDADE_PADRAO = 32


class CacheCheio(RuntimeError):
    """Falta de frame e todas as páginas residentes estão fixadas."""


class Frame:
    __slots__ = ("dados", "pagina", "pins", "sujo")

    def __init__(self):
        self.dados = bytearray(PAGE_SIZE)  # alocado uma vez, reaproveitado sempre
        self.pagina = None                 # None = frame livre
        self.pins = 0
        self.sujo = False


class CachePaginas:
    def __init__(self, f, capacidade=CAPACIDADE_PADRAO, politica="lru"):
        if capacidade < 1:
            raise ValueError("capacidade precisa ser >= 1")
        if politica not in ("lru", "fifo"):
            raise ValueError(f"política desconhecida: {politica!r}")
        self.f = f  # o cache não é dono do arquivo: quem abriu, fecha
        self.capacidade = capacidade
        self.politica = politica

        self.frames = [Frame() for _ in range(capacidade)]
        self.tabela = {}                                    # página -> índice do frame
        self.livres = list(range(capacidade - 1, -1, -1))   # pop() entrega o frame 0 primeiro
        self.ordem = OrderedDict()                          # página -> None, mais antiga primeiro

        self.zera_contadores()

    # ---------- contadores ----------

    def zera_contadores(self):
        self.chamadas = 0         # chamadas a fixa()
        self.acertos = 0          # hit
        self.faltas = 0           # miss
        self.leituras_disco = 0   # le_pagina que deu certo
        self.escritas_disco = 0   # escreve_pagina que deu certo
        self.expulsoes = 0
        self.expulsoes_sujas = 0  # expulsões que precisaram gravar antes

    def estatisticas(self):
        return {
            "chamadas": self.chamadas, "acertos": self.acertos, "faltas": self.faltas,
            "leituras_disco": self.leituras_disco, "escritas_disco": self.escritas_disco,
            "expulsoes": self.expulsoes, "expulsoes_sujas": self.expulsoes_sujas,
        }

    # ---------- consulta ----------

    def __contains__(self, pagina):
        return pagina in self.tabela

    def residentes(self):
        """Páginas em memória, da próxima a sair para a última a sair."""
        return list(self.ordem)

    def fixadas(self):
        """Quantas fixações estão abertas. Depois de qualquer operação
        completa isso tem que ser 0; se não for, alguém esqueceu o solta."""
        return sum(fr.pins for fr in self.frames)

    def suja(self, pagina):
        i = self.tabela.get(pagina)
        return i is not None and self.frames[i].sujo

    # ---------- fixa / solta ----------

    def fixa(self, n):
        """Devolve o buffer da página n (a MESMA bytearray que mora no
        frame, não uma cópia) e a marca como em uso até o solta()."""
        self.chamadas += 1
        i = self.tabela.get(n)
        if i is not None:                 # ACERTO: nenhum acesso a disco
            self.acertos += 1
            if self.politica == "lru":
                self.ordem.move_to_end(n)
        else:                             # FALTA: acha frame, lê, guarda
            self.faltas += 1
            i = self._traz(n)
        fr = self.frames[i]
        fr.pins += 1
        return fr.dados

    def solta(self, n, sujo=False):
        """Termina o uso de n. sujo=True avisa que o buffer foi alterado.
        O bit de sujeira só sobe aqui: quem altera é responsável por avisar."""
        i = self.tabela.get(n)
        if i is None:
            raise ValueError(f"solta({n}): página fora do cache")
        fr = self.frames[i]
        if fr.pins == 0:
            raise ValueError(f"solta({n}): página não está fixada")
        fr.pins -= 1
        if sujo:
            fr.sujo = True   # só sobe; quem limpa é a gravação em disco

    @contextmanager
    def usa(self, n, escreve=False):
        """fixa + solta garantido em todo caminho de saída, inclusive erro.
        Se escreve=True a página sai marcada como suja mesmo que o bloco
        tenha estourado no meio: o buffer pode ter sido alterado pela metade
        e, na dúvida, grava."""
        buf = self.fixa(n)
        try:
            yield buf
        finally:
            self.solta(n, sujo=escreve)

    # ---------- gravação ----------

    def _grava_frame(self, fr):
        escreve_pagina(self.f, fr.pagina, bytes(fr.dados))
        self.escritas_disco += 1
        fr.sujo = False

    def grava(self, n):
        """Grava a página n se estiver suja. Devolve True se gravou."""
        i = self.tabela.get(n)
        if i is None or not self.frames[i].sujo:
            return False
        self._grava_frame(self.frames[i])
        return True

    def grava_tudo(self):
        """Grava todas as sujas (o 'quando alguém mandar' do slide da página suja).
        Devolve quantas gravou."""
        gravadas = 0
        for fr in self.frames:
            if fr.pagina is not None and fr.sujo:
                self._grava_frame(fr)
                gravadas += 1
        return gravadas

    # ---------- caminho da falta ----------

    def _traz(self, n):
        """Frame livre ou vítima -> lê a página n para dentro dele."""
        i = self.livres.pop() if self.livres else self._expulsa()
        fr = self.frames[i]
        try:
            dados = le_pagina(self.f, n)
        except BaseException:
            # A leitura falhou depois de já termos um frame na mão: devolve
            # o frame aos livres, senão a capacidade encolheria em silêncio.
            fr.pagina, fr.pins, fr.sujo = None, 0, False
            self.livres.append(i)
            raise
        self.leituras_disco += 1
        fr.dados[:] = dados
        fr.pagina, fr.pins, fr.sujo = n, 0, False
        self.tabela[n] = i
        self.ordem[n] = None
        return i

    def _expulsa(self):
        """Escolhe a vítima: a mais antiga da fila SEM pin. Se estiver suja,
        grava ANTES de tirar do cache: se a gravação falhar, a exceção sobe
        e a página continua aqui, suja, sem perder nada."""
        for pagina in self.ordem:
            i = self.tabela[pagina]
            fr = self.frames[i]
            if fr.pins > 0:
                continue                      # em uso: pular, não falhar
            if fr.sujo:
                self._grava_frame(fr)
                self.expulsoes_sujas += 1
            del self.tabela[pagina]
            del self.ordem[pagina]
            fr.pagina, fr.sujo = None, False
            self.expulsoes += 1
            return i                          # return logo após del: seguro iterar e apagar
        raise CacheCheio(
            f"todas as {self.capacidade} páginas do cache estão fixadas; "
            "nada pode ser expulso (algum solta() faltando, ou capacidade pequena demais)"
        )
