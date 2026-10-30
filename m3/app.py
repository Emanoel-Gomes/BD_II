#!/usr/bin/env python3
"""
app.py - o minidb inteiro num app só: M1 (página, RID, fsync) + M2 (cache LRU/FIFO,
fixa/solta, página suja) + M3 (árvore B+). Não altera nenhum módulo: só importa.

    python3 app.py demo                    tudo junto, passo a passo (começa aqui)
    python3 app.py ARQ.db                  prompt interativo (cria o arquivo se não existir)
    python3 app.py ARQ.db insere 10 20 5   um comando só e sai
    python3 app.py ARQ.db < comandos.txt   ou comandos vindos do terminal (heredoc)

    opções:  --frames N      frames do cache (padrão 8; mínimo 3)
             --politica P    lru | fifo (padrão lru)
             --max-chaves K  chaves por nó ao CRIAR o índice (padrão 3 num arquivo novo, como nos
                             exercícios; 0 = o que cabe na página, 408/510, que é o padrão ao
                             indexar uma tabela do M1 que já existia)

Comandos (no prompt, no heredoc ou na linha de comando):
    insere N [N ...]    grava na tabela (M1) e no índice (M3), pelo cache (M2). Aceita 1..50
    busca N [N ...]     desce a árvore e mostra cada página: ACERTO (memória) ou FALTA (disco)
    faixa A B           WHERE id BETWEEN A AND B, pelo encadeamento das folhas
    varre N             o mesmo que busca, mas SEM índice (lê a tabela inteira)
    arvore              desenha a árvore com o número de cada página
    cache               o que está na memória, o que está suja, contadores
    frio                esvazia o cache (grava as sujas antes)
    politica lru|fifo   troca a política (cache novo, frio)
    frames N            troca a capacidade (cache novo, frio)
    zera                zera os contadores
    grava               grava as páginas sujas no disco (grava_tudo)
    bench               LRU contra FIFO nas mesmas 3000 buscas, e índice contra varredura
    info                tamanho do arquivo, do índice e altura
    ajuda | sair
"""

import os
import random
import shlex
import signal
import subprocess
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from btree import ArvoreBMais, ChaveDuplicada, SemIndice, decodifica_no  # noqa: E402  (M3)
from cache import CachePaginas                                    # noqa: E402  (M2)
from minidb_m1 import le_pagina                                   # noqa: E402  (M1)
from minidb import (ESQUEMA_ALUNO, HEADER_SIZE, PAGE_SIZE,        # noqa: E402  (M1)
                    deslocamento, inicializa_pagina0, le_cabecalho)
from minidb_cache import aloca, le_metadados, varre               # noqa: E402  (M1 pelo M2)
from minidb_indice import (busca_registro, faixa_registros, le_registro,       # noqa: E402  (M3 + tabela)
                           indexa_tabela, insere_indexado)

ESQ = ESQUEMA_ALUNO
MAT_BASE = 20260000          # matrícula = MAT_BASE + id, como nas tabelas do M1


def matricula(n):
    return MAT_BASE + n


# ======================================================================
#  Banco: o arquivo (M1), o cache (M2) e o índice (M3) juntos
# ======================================================================

class Banco:
    def __init__(self, caminho, frames=8, politica="lru", max_chaves=None):
        if frames < 3:
            raise ValueError("frames precisa ser >= 3 (a árvore fixa até 2 páginas, a tabela mais 1)")
        self.caminho = caminho
        self.max_chaves = max_chaves        # None = padrão: 3 se o arquivo é novo, página inteira se já existia
        novo = not os.path.exists(caminho) or os.path.getsize(caminho) == 0
        if novo:                                       # M1: página 0 (número mágico, versão...)
            with open(caminho, "w+b") as f:
                inicializa_pagina0(f)
        self.f = open(caminho, "r+b")
        self.criou = novo
        self.indexou = 0
        self._abre(frames, politica, novo)

    def _abre(self, frames, politica, novo):
        self.cache = CachePaginas(self.f, frames, politica)           # M2
        if novo:
            if self.max_chaves is None:
                self.max_chaves = 3
            self.max_chaves = self.max_chaves or None                 # 0 = o que cabe na página
            self.pagina_dados = aloca(self.cache, ESQ.tamanho)        # M1: 1ª página de dados
            self.arv = ArvoreBMais.cria(self.cache, max_chaves=self.max_chaves)
            self.cache.grava_tudo()                                   # arquivo válido desde já
        else:
            try:
                self.arv = ArvoreBMais.abre(self.cache)
            except SemIndice:                          # tabela do M1 sem índice: indexa agora
                self.arv = ArvoreBMais.cria(self.cache, max_chaves=self.max_chaves or None)
                self.indexou = indexa_tabela(self.cache, ESQ, self.arv)
                self.cache.grava_tudo()
            self.pagina_dados = self._ultima_pagina_dados()
        # Abrir leu páginas (página 0, raiz, última de dados). Cache NOVO, para o 1º comando
        # começar frio de verdade: um processo recém-aberto não tem nada em memória.
        self.cache.grava_tudo()
        self._cache_vazio(frames, politica)

    def _ultima_pagina_dados(self):
        """A última página que NÃO é nó do índice (tam_registro != 0)."""
        _, _, total = le_metadados(self.cache)
        for n in range(total - 1, 0, -1):
            with self.cache.usa(n) as buf:
                if le_cabecalho(buf)[1] != 0:
                    return n
        return aloca(self.cache, ESQ.tamanho)

    def recria_cache(self, frames=None, politica=None):
        """Cache novo (frio). Grava as sujas antes: nada se perde."""
        frames = frames or self.cache.capacidade
        politica = politica or self.cache.politica
        if frames < 3:
            raise ValueError("frames precisa ser >= 3 (a árvore fixa até 2 páginas, a tabela mais 1)")
        self.cache.grava_tudo()
        self._cache_vazio(frames, politica)

    def _cache_vazio(self, frames, politica):
        """Cache novo e VAZIO. A árvore é refeita com a raiz que já se sabe, sem ler a página 0 pelo
        cache novo (ArvoreBMais.abre leria, e a página 0 ficaria residente antes do 1º comando)."""
        raiz, maxc = self.arv.raiz, self.arv.max_chaves
        self.cache = CachePaginas(self.f, frames, politica)
        self.arv = ArvoreBMais(self.cache, raiz, maxc)

    def fim(self):
        n = self.cache.grava_tudo()
        self.f.close()
        return n

    # ---------- contabilidade ----------

    def marca(self):
        return dict(self.cache.estatisticas())

    def desde(self, antes):
        c = self.cache.estatisticas()
        return {k: c[k] - antes[k] for k in c}

    @staticmethod
    def texto(d):
        return (f"{d['chamadas']} páginas pedidas = {d['acertos']} acerto(s) + {d['faltas']} falta(s)"
                f" | {d['leituras_disco']} lidas do disco, {d['expulsoes']} expulsões"
                f" ({d['expulsoes_sujas']} sujas gravadas)")

    # ---------- operações ----------

    def insere(self, n):
        """M1 grava o registro, M3 grava a chave. Devolve (rid, divisões, subiu_raiz)."""
        alocacoes, orig, raiz0 = [0], self.arv._aloca, self.arv.raiz

        def conta():
            alocacoes[0] += 1
            return orig()

        self.arv._aloca = conta                         # só conta os nós novos da árvore
        try:
            rid, self.pagina_dados = insere_indexado(
                self.cache, ESQ, self.arv, (n, matricula(n)), self.pagina_dados)
        finally:
            del self.arv._aloca
        subiu = self.arv.raiz != raiz0
        return rid, alocacoes[0] - (1 if subiu else 0), subiu

    def papel(self, p):
        """O que a página p é, olhando o frame SEM mexer no cache."""
        if p == 0:
            return "meta"
        buf = self.cache.frames[self.cache.tabela[p]].dados
        if le_cabecalho(buf)[1] != 0:
            return "dados"
        tipo = buf[8]
        if p == self.arv.raiz:
            return "raiz" if tipo == 2 else "raiz=folha"
        return "folha" if tipo == 1 else "interno"


@contextmanager
def rastro(cache):
    """Anota cada fixa(): (página, foi falta?). É como o app enxerga ACERTO e FALTA."""
    log, orig = [], cache.fixa
    tinha = "fixa" in vars(cache)          # já havia um rastro/espião por cima? restaura o MESMO depois

    def fixa(n):
        antes = cache.faltas
        buf = orig(n)
        log.append((n, cache.faltas > antes))
        return buf

    cache.fixa = fixa
    try:
        yield log
    finally:
        if tinha:
            cache.fixa = orig
        else:
            del cache.fixa


# ======================================================================
#  Saída
# ======================================================================

def espia(b, pagina):
    """Lê um nó SEM mexer no cache (nem fila do LRU, nem contadores, nem expulsão): se a página
    está residente usa o frame (pode estar mais nova que o disco), senão lê o arquivo direto."""
    c = b.cache
    if pagina in c.tabela:
        return decodifica_no(c.frames[c.tabela[pagina]].dados, pagina)
    return decodifica_no(le_pagina(b.f, pagina), pagina)


def desenha(b, limite=24):
    nivel, linhas, n = [espia(b, b.arv.raiz)], [], 0
    while nivel:
        n += len(nivel)
        if n > limite:
            return f"  árvore com mais de {limite} nós: grande demais para desenhar (use `info`)"
        r = "raiz   " if not linhas else ("folhas " if nivel[0].folha else "interno")
        linhas.append(f"  {r} " + "  ".join(
            f"p{x.pagina}[{' '.join(map(str, x.chaves))}]" for x in nivel))
        if nivel[0].folha:
            break
        nivel = [espia(b, f) for x in nivel for f in x.filhos]
    return "\n".join(linhas)


def cmd_insere(b, nums, mostra_arvore=True):
    antes = b.marca()
    detalhe = len(nums) <= 12          # lote grande: só o resumo, senão são milhares de linhas
    feitos = recusados = divisoes = subidas = 0
    for n in nums:
        try:
            rid, div, subiu = b.insere(n)
        except ChaveDuplicada:
            recusados += 1
            if detalhe:
                print(f"  insere {n}: RECUSADO, id repetido (nada foi gravado)")
            continue
        except ValueError as e:
            recusados += 1
            print(f"  insere {n}: recusado: {e}")
            continue
        feitos += 1
        divisoes += div
        subidas += 1 if subiu else 0
        if not detalhe:
            continue
        off = deslocamento(rid[0], rid[1], ESQ.tamanho)
        extra = ""
        if div:
            extra = f" | DIVIDIU {div}x" + (" e a divisão chegou à raiz: +1 nível" if subiu else "")
        print(f"  insere {n:>5}: RID (página {rid[0]}, slot {rid[1]}) = byte {off} do arquivo{extra}")
        if div and mostra_arvore:
            print(desenha(b))
    if not detalhe:
        print(f"  {feitos} inseridos, {recusados} recusados; {divisoes} divisões de nó, "
              f"{subidas} vez(es) a divisão chegou à raiz (altura agora {b.arv.altura()})")
    sujas = sum(1 for fr in b.cache.frames if fr.sujo)
    print(f"  cache: {Banco.texto(b.desde(antes))}")
    print(f"  {sujas} página(s) suja(s) só na memória; `grava` (ou sair) leva ao disco. "
          f"Altura do índice: {b.arv.altura()}")


def papel_pagina(i, total, achou, rid, off, p):
    if achou and i == total - 1:
        return f"TABELA, slot {rid[1]}, byte {off}"
    n_idx = total - (1 if achou else 0)
    if n_idx == 1:
        return "raiz = folha"
    return "raiz" if i == 0 else ("folha" if i == n_idx - 1 else "nó interno")


def busca_uma(b, chave, quieto=False):
    antes = b.marca()
    reg = None
    with rastro(b.cache) as log:
        rid = b.arv.busca(chave)                         # a ÚNICA descida: nada é lido fora da medição
        if rid is not None:
            reg = le_registro(b.cache, ESQ, rid)
            assert reg[0] == chave, f"índice aponta {rid} para {reg}, procurava {chave}"
    d = b.desde(antes)
    if not quieto:
        print(f"SELECT * FROM aluno WHERE id = {chave}")
        off = deslocamento(*rid, ESQ.tamanho) if rid else None
        for i, (p, falta) in enumerate(log):
            quem = papel_pagina(i, len(log), reg is not None, rid, off, p)
            onde = "FALTA  -> leu do disco" if falta else "ACERTO -> já estava na memória"
            print(f"  {i + 1}. página {p:<4} {quem:<28} {onde}")
        if reg is None:
            print(f"  => nenhum registro (nem chegou à tabela)")
        else:
            print(f"  => (id, matricula) = {reg}")
            print(f"     conferir no disco: od -A d -t x1z -j {off} -N {ESQ.tamanho} {b.caminho}")
        print(f"  {Banco.texto(d)}")
    return reg, d


def cmd_busca(b, nums):
    total = None
    for n in nums:
        _, d = busca_uma(b, n)
        total = d if total is None else {k: total[k] + d[k] for k in d}
    if len(nums) > 1:
        print(f"TOTAL de {len(nums)} buscas: {Banco.texto(total)}")
    print(f"  (política {b.cache.politica.upper()}, {b.cache.capacidade} frames: "
          f"quanto mais ACERTO, menos disco)")


def cmd_faixa(b, a, z):
    antes = b.marca()
    with rastro(b.cache) as log:
        regs = list(faixa_registros(b.cache, ESQ, b.arv, a, z))
    print(f"SELECT * FROM aluno WHERE id BETWEEN {a} AND {z}")
    for r in regs[:10]:
        print(f"  {r}")
    if len(regs) > 10:
        print(f"  ... (mais {len(regs) - 10})")
    print(f"  => {len(regs)} registros; {Banco.texto(b.desde(antes))}")
    print(f"  (desce UMA vez até a folha do {a} e segue o encadeamento das folhas)")


def cmd_varre(b, chave):
    antes = b.marca()
    achou = [r for r in varre(b.cache, ESQ) if r[0] == chave]
    print(f"SELECT * FROM aluno WHERE id = {chave}   (SEM índice: varredura da tabela)")
    print(f"  => {achou[0] if achou else 'nenhum registro'}")
    print(f"  {Banco.texto(b.desde(antes))}")
    print("  (uma varredura grande passa por todo o cache e expulsa as páginas quentes: veja `cache`)")


def cmd_cache(b):
    c = b.cache
    print(f"  política {c.politica.upper()}, {c.capacidade} frames "
          f"({len(c.residentes())} em uso, {c.fixadas()} fixadas)")
    partes = [f"{p}:{b.papel(p)}{'*' if c.suja(p) else ''}" for p in c.residentes()]
    print("  sai primeiro -> " + ("  ".join(partes) if partes else "(vazio)") + "  <- mais recente")
    print("  (* = suja: está diferente do disco)")
    e = c.estatisticas()
    taxa = f"{100 * e['acertos'] / e['chamadas']:.1f}%" if e["chamadas"] else "-"
    print(f"  desde o último `zera`: {Banco.texto(e)} | taxa de acerto {taxa}")


def cmd_info(b):
    no = espia(b, b.arv.raiz)
    h = 1
    while not no.folha:
        no, h = espia(b, no.filhos[0]), h + 1
    folhas = [no]
    while no.proxima:
        no = espia(b, no.proxima)
        folhas.append(no)
    chaves = sum(len(f.chaves) for f in folhas)
    p0 = b.cache.frames[b.cache.tabela[0]].dados if 0 in b.cache.tabela else le_pagina(b.f, 0)
    total = int.from_bytes(p0[14:18], "little")        # total de páginas, como a página 0 diz
    cap = b.arv.max_chaves or "o que cabe na página (408 folha / 510 interno)"
    print(f"  arquivo {b.caminho}: {total} páginas de {PAGE_SIZE} bytes = {total * PAGE_SIZE} bytes")
    print(f"  índice: {chaves} chaves em {len(folhas)} folhas, altura {h}, máx. de chaves por nó: {cap}")
    print(f"  uma busca lê {h} página(s) do índice + 1 da tabela; sem índice leria {total - 1}")


# ======================================================================
#  bench: política de cache contra política de cache, índice contra varredura
# ======================================================================

def carga_de_buscas(n_chaves, n_buscas=3000, n_quentes=6, seed=7):
    """80% das buscas caem em poucos ids (alunos 'quentes'), 20% em qualquer um."""
    rnd = random.Random(seed)
    quentes = [rnd.randint(1, n_chaves) for _ in range(n_quentes)]
    return [rnd.choice(quentes) if rnd.random() < 0.8 else rnd.randint(1, n_chaves)
            for _ in range(n_buscas)]


def monta_tabela_grande(caminho, n):
    b = Banco(caminho, frames=64, politica="lru", max_chaves=0)
    for i in range(1, n + 1):
        b.insere(i)
    b.fim()


def cmd_bench(b=None, n=20000, frames=(3, 8, 16)):
    print(f"  montando uma tabela de {n} alunos com índice (arquivo temporário)...")
    with tempfile.TemporaryDirectory() as d:
        caminho = os.path.join(d, "bench.db")
        monta_tabela_grande(caminho, n)
        carga = carga_de_buscas(n)
        with open(caminho, "r+b") as f:
            tmp = CachePaginas(f, 3)
            _, _, total = le_metadados(tmp)
            altura = ArvoreBMais.abre(tmp).altura()
        print(f"  arquivo: {total} páginas | índice de altura {altura} | "
              f"{len(carga)} buscas: 80% em 6 ids quentes, 20% em ids quaisquer")
        print(f"  {'frames':>6}  {'política':<8} {'páginas pedidas':>15} {'leituras de disco':>18} "
              f"{'taxa de acerto':>15}  {'disco/busca':>11}  {'faltas da raiz':>14}")
        res = {}
        for fr in frames:
            for pol in ("fifo", "lru"):
                with open(caminho, "r+b") as f:
                    cache = CachePaginas(f, fr, pol)
                    arv = ArvoreBMais.abre(cache)
                    cache.zera_contadores()
                    faltas_raiz = 0
                    for k in carga:
                        with rastro(cache) as log:
                            busca_registro(cache, ESQ, arv, k)
                        faltas_raiz += sum(1 for p, falta in log if p == arv.raiz and falta)
                    e = cache.estatisticas()
                    assert cache.fixadas() == 0
                e["faltas_raiz"] = faltas_raiz
                res[(fr, pol)] = e
                print(f"  {fr:>6}  {pol.upper():<8} {e['chamadas']:>15} {e['leituras_disco']:>18} "
                      f"{100 * e['acertos'] / e['chamadas']:>14.1f}%  {e['leituras_disco'] / len(carga):>11.2f}"
                      f"  {faltas_raiz:>14}")
        with open(caminho, "r+b") as f:
            cache = CachePaginas(f, 8, "lru")
            antes = cache.leituras_disco
            achou = [r for r in varre(cache, ESQ) if r[0] == n // 2]
            varrida = cache.leituras_disco - antes
        fm = 8
        f_fifo, f_lru = res[(fm, "fifo")]["leituras_disco"], res[(fm, "lru")]["leituras_disco"]
        print(f"\n  SEM índice, uma única busca lê a tabela inteira: {varrida} leituras de disco")
        print(f"  COM índice e cache frio: {altura} do índice + 1 da tabela = {altura + 1}; "
              f"com o cache quente (LRU, {fm} frames), {f_lru / len(carga):.2f} por busca")
        print(f"  Com {fm} frames, LRU fez {f_lru} leituras contra {f_fifo} do FIFO "
              f"({100 * (f_fifo - f_lru) / f_fifo:.0f}% menos). A raiz é pedida em TODA busca: "
              f"o LRU a mantém ({res[(fm, 'lru')]['faltas_raiz']} faltas), o FIFO a expulsa por ser a mais "
              f"antiga ({res[(fm, 'fifo')]['faltas_raiz']} faltas).")


# ======================================================================
#  durabilidade: kill -9 com e sem grava_tudo (M1 atividade 2, M2 atividade 3)
# ======================================================================

def filho_morre(caminho, modo, frames, nums):
    """Roda num processo à parte: insere e leva um kill -9 em si mesmo."""
    b = Banco(caminho, frames=frames)
    for n in nums:
        b.insere(n)
    if modo == "com":
        b.cache.grava_tudo()
    os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))


def teste_kill(caminho_base, modo, frames, nums):
    with tempfile.TemporaryDirectory() as d:
        copia = os.path.join(d, "k.db")
        with open(caminho_base, "rb") as a, open(copia, "wb") as z:
            z.write(a.read())
        subprocess.run([sys.executable, os.path.abspath(__file__), copia, "--frames", str(frames),
                        "_morre", modo, *map(str, nums)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            b = Banco(copia, frames=32)
            altura, total = b.arv.confere()
            achou = [n for n in nums if b.arv.busca(n) is not None]
            on = [n for n in nums if busca_registro(b.cache, ESQ, b.arv, n) is not None]
            b.f.close()
            return f"abriu; {total} chaves no índice; achou {len(achou)}/{len(nums)} dos novos; {len(on)} com registro"
        except Exception as e:                                         # índice pela metade
            return f"ÍNDICE QUEBRADO: {type(e).__name__}: {str(e)[:70]}"


# ======================================================================
#  O demo: tudo junto
# ======================================================================

def titulo(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def demo():
    caminho = "demo_app.db"
    if os.path.exists(caminho):
        os.remove(caminho)
    print("minidb: M1 (página/RID) + M2 (cache) + M3 (árvore B+) num app só")

    # ---- 1. M1 ----
    titulo("1. M1 - arquivo de páginas de 4096 bytes, página 0 de metadados, RID (página, slot)")
    b = Banco(caminho, frames=4, politica="lru", max_chaves=3)
    with open(caminho, "rb") as f:
        raw0 = f.read(18)
    print(f"  {caminho} criado. Página 0: número mágico {raw0[:8]!r}, versão {int.from_bytes(raw0[8:10], 'little')}, "
          f"tamanho de página {int.from_bytes(raw0[10:14], 'little')}")
    print(f"  esquema aluno = (id, matricula), {ESQ.tamanho} bytes por registro; "
          f"cabem {(PAGE_SIZE - HEADER_SIZE) // ESQ.tamanho} por página")
    print(f"  fórmula do byte: página*{PAGE_SIZE} + {HEADER_SIZE} + slot*{ESQ.tamanho}  "
          f"(a escrita em disco usa write+flush+fsync, como na atividade do kill -9)")

    # ---- 2. M2 ----
    titulo("2. M2 - nada fala com o arquivo por fora do cache: 4 frames, política LRU")
    print("  Cache de 4 frames de propósito: a árvore e a tabela vão precisar de mais que isso,")
    print("  então a expulsão (e a gravação das páginas sujas ao expulsar) vai acontecer de verdade.")
    cmd_cache(b)

    # ---- 3. M3: exercício 1 e 2 ----
    titulo("3. M3 - exercício 1: inserir 10, 20, 5, 30, 25, 40, 15 (máx. 3 chaves por nó)")
    print("  Cada inserção grava o registro na tabela (M1) e a chave no índice (M3), pelo cache (M2).")
    cmd_insere(b, [10, 20, 5, 30, 25, 40, 15])
    print(f"\n  Altura ao fim: {b.arv.altura()}")
    print("  (a tabela tem os registros na ORDEM DE CHEGADA; o índice é que está em ordem)")

    titulo("3b. M3 - exercício 2: mais 35, 45, 50, 55 (uma das divisões chega à raiz)")
    cmd_insere(b, [35, 45, 50, 55])
    print(f"\n  Altura ao fim: {b.arv.altura()}")
    print("  Duplicata é recusada antes de gravar:")
    cmd_insere(b, [25])

    # ---- 4. Busca com cache ----
    titulo("4. Busca por valor: o índice acha a página, o cache evita ler de novo")
    b.recria_cache()
    print("  Cache frio (esvaziado de propósito). 1ª busca por 25: tudo é FALTA.")
    busca_uma(b, 25)
    print("\n  2ª busca por 25, mesmo processo: o cache já tem as páginas.")
    busca_uma(b, 25)
    print("\n  Busca por 30: a raiz é a mesma, então só o que é novo vai ao disco.")
    busca_uma(b, 30)
    print("\n  Busca por 99 (não existe): para na folha e nem toca na tabela.")
    busca_uma(b, 99)
    print()
    cmd_cache(b)
    print()
    cmd_faixa(b, 12, 33)
    print("  (o exercício 2 pergunta quantas páginas lê BETWEEN 12 AND 33: raiz, interno e 3 folhas = 5 do")
    print("   índice; as de dados vêm do cache ou do disco)")

    # ---- 5. índice contra varredura, e política ----
    titulo("5. Política de cache e índice contra varredura (20000 alunos, 3000 buscas)")
    cmd_bench()

    # ---- 6. durabilidade ----
    titulo("6. Durabilidade: kill -9 no meio das inserções (M1 atividade 2, M2 atividade 3)")
    b.cache.grava_tudo()
    base = os.path.join(tempfile.gettempdir(), "minidb_base_kill.db")
    if os.path.exists(base):
        os.remove(base)
    bb = Banco(base, frames=32)
    for n in (10, 20, 5, 30, 25):
        bb.insere(n)
    bb.fim()
    novos = list(range(100, 140))
    print("  Arquivo base com 5 chaves. Um processo filho insere 40 chaves novas e leva `kill -9` em si mesmo:")
    print(f"    sem grava_tudo, 64 frames (cabe tudo, nada expulso): {teste_kill(base, 'sem', 64, novos)}")
    print(f"    com grava_tudo antes do kill:                         {teste_kill(base, 'com', 64, novos)}")
    print(f"    sem grava_tudo, 3 frames (as expulsões gravaram partes): {teste_kill(base, 'sem', 3, novos)}")
    print("  O cache é só memória: o que só existe nele morre com ele (1º caso: voltou ao estado antigo, íntegro).")
    print("  3º caso: só o que foi expulso chegou ao disco. Sem log não há garantia do que sobra: com outra")
    print("  sequência o resultado já foi um índice QUEBRADO (nó apontando para página vazia). O log resolve.")
    os.remove(base)

    b.fim()
    print(f"\n  tudo gravado em {caminho}. Agora é com você:")
    print(f"      python3 app.py {caminho}       # e digite: busca 25 | insere 60 61 | arvore | cache")


# ======================================================================
#  linha de comando e prompt
# ======================================================================

def parse_nums(args):
    saida = []
    for a in args:
        if ".." in a or (a.count("-") == 1 and not a.startswith("-")):
            ini, fim = a.replace("..", "-").split("-")
            lo, hi = inteiro(ini), inteiro(fim)
            if hi - lo > 100000:
                raise ValueError("intervalo grande demais")
            saida.extend(range(lo, hi + 1))
        else:
            saida.append(inteiro(a))
    return saida


def inteiro(txt):
    try:
        return int(txt)
    except ValueError:
        raise ValueError(f"{txt!r} não é um número inteiro")


def executa(b, partes):
    cmd, a = partes[0].lower(), partes[1:]
    try:
        if cmd == "insere" and a:
            cmd_insere(b, parse_nums(a))
        elif cmd == "busca" and a:
            cmd_busca(b, parse_nums(a))
        elif cmd == "faixa" and len(a) == 2:
            cmd_faixa(b, inteiro(a[0]), inteiro(a[1]))
        elif cmd == "varre" and len(a) == 1:
            cmd_varre(b, inteiro(a[0]))
        elif cmd == "arvore":
            print(desenha(b, limite=60))
        elif cmd == "cache":
            cmd_cache(b)
        elif cmd == "frio":
            b.recria_cache()
            print("  cache esvaziado (as sujas foram gravadas antes)")
        elif cmd == "politica" and len(a) == 1 and a[0].lower() in ("lru", "fifo"):
            b.recria_cache(politica=a[0].lower())
            print(f"  política {a[0].upper()} (cache novo, frio)")
        elif cmd == "frames" and len(a) == 1:
            b.recria_cache(frames=inteiro(a[0]))
            print(f"  {a[0]} frames (cache novo, frio)")
        elif cmd == "zera":
            b.cache.zera_contadores()
            print("  contadores zerados")
        elif cmd == "grava":
            print(f"  {b.cache.grava_tudo()} página(s) suja(s) gravadas no disco (write+fsync)")
        elif cmd == "bench":
            cmd_bench()
        elif cmd == "info":
            cmd_info(b)
        elif cmd in ("ajuda", "help", "?"):
            print("Comandos" + __doc__.split("Comandos")[1])
        else:
            print("  comando não entendido (digite `ajuda`)")
    except ValueError as e:
        print(f"  erro: {e}")


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    if argv[1] == "demo":
        demo()
        return

    caminho, resto = argv[1], argv[2:]
    frames, politica, max_chaves = 8, "lru", None
    while resto and resto[0] in ("--frames", "--politica", "--max-chaves"):
        if len(resto) < 2:
            sys.exit(f"{resto[0]} precisa de um valor")
        if resto[0] == "--frames":
            frames = int(resto[1])
        elif resto[0] == "--politica":
            politica = resto[1].lower()
        else:
            max_chaves = int(resto[1])
        resto = resto[2:]

    if resto and resto[0] == "_morre":                  # uso interno do demo
        filho_morre(caminho, resto[1], frames, list(map(int, resto[2:])))
        return

    try:
        b = Banco(caminho, frames, politica, max_chaves)
    except (ValueError, OSError) as e:
        sys.exit(f"erro: {e}")
    if b.criou:
        print(f"{caminho} criado: página 0 + 1ª página de dados + índice B+ "
              f"(chaves por nó: {b.max_chaves or 'o que cabe na página'})")
    if b.indexou:
        print(f"{caminho} era uma tabela do M1 sem índice: {b.indexou} registros indexados")
    try:
        if resto:
            executa(b, resto)
            return
        tty = sys.stdin.isatty()
        if tty:
            cmd_info(b)
            print(f"  política {b.cache.politica.upper()}, {b.cache.capacidade} frames. "
                  f"Digite `ajuda`. Ex.: insere 10 20 5 30 25 40 15, depois busca 25 e `cache`")
        while True:
            try:
                linha = input("app> " if tty else "").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not linha or linha.startswith("#"):
                if linha and not tty:
                    print(linha)
                continue
            if not tty:
                print(f"app> {linha}")
            if linha.lower() in ("sair", "exit", "quit"):
                break
            try:
                executa(b, shlex.split(linha))
            except Exception as e:                      # o prompt não morre por causa de um comando
                print(f"  erro: {type(e).__name__}: {e}")
    finally:
        gravadas = b.fim()
        print(f"[fim] {gravadas} página(s) suja(s) gravadas em {caminho}")


if __name__ == "__main__":
    main(sys.argv)
