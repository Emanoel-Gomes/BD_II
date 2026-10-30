"""
indice.py - M3 no terminal: uma tabela `aluno` com índice B+, para buscar,
inserir e ver a árvore por comandos.

Uso:
    python indice.py aluno.db            abre (se não existir, cria com 10000 alunos)
    python indice.py aluno.db 50000      idem, criando com 50000 alunos
    python indice.py aluno.db busca 7500 roda UM comando e sai

Comandos (também valem dentro do prompt):
    busca ID            desce a árvore, mostra cada página lida e o registro
    varre ID            acha o mesmo ID SEM índice (varredura), para comparar
    faixa A B           registros com A <= id <= B
    insere ID MATRICULA grava na tabela e no índice (recusa id repetido)
    arvore              desenha a árvore (só se for pequena)
    info                tamanho da tabela, do índice e altura
    ajuda / sair

Cada comando começa com o cache FRIO (como o demo_indice.py), então "leituras
de disco" é o número do slide. A tabela fica no arquivo, o índice também.
"""

import os
import shlex
import sys
from bisect import bisect_right

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apoio import cria_tabela_m1  # noqa: E402
from btree import ArvoreBMais, ChaveDuplicada, SemIndice  # noqa: E402
from cache import CachePaginas  # noqa: E402
from minidb import ESQUEMA_ALUNO  # noqa: E402
from minidb_cache import le_metadados, varre  # noqa: E402
from minidb_indice import busca_registro, faixa_registros, indexa_tabela, insere_indexado  # noqa: E402

AJUDA = __doc__.split("Comandos")[1].split('"""')[0]


class Banco:
    def __init__(self, caminho):
        self.f = open(caminho, "r+b")
        self.frio()

    def frio(self):
        """Cache novo = nenhuma página em memória."""
        self.cache = CachePaginas(self.f, 32)
        self.arv = ArvoreBMais.abre(self.cache)
        self.cache.zera_contadores()

    def custo(self):
        c = self.cache
        return f"[{c.chamadas} páginas pedidas, {c.leituras_disco} lidas do disco]"

    def fim(self):
        self.cache.grava_tudo()
        self.f.close()


def resumo(chaves, destaque=None, max_itens=8):
    """Lista curta de chaves: nó grande vira `[a, b, c ... y, z] (N chaves)`.
    Se `destaque` está na lista, mostra os vizinhos dele em vez do começo."""
    if len(chaves) <= max_itens:
        return str(chaves)
    if destaque is not None and destaque in chaves:
        i = chaves.index(destaque)
        ini = max(0, min(i - 2, len(chaves) - 5))
        trecho = chaves[ini:ini + 5]
        pre = "... " if ini > 0 else ""
        pos = " ..." if ini + 5 < len(chaves) else ""
        return f"[{pre}{', '.join(map(str, trecho))}{pos}] ({len(chaves)} chaves)"
    return f"[{', '.join(map(str, chaves[:3]))} ... {', '.join(map(str, chaves[-2:]))}] ({len(chaves)} chaves)"


def cmd_busca(b, chave):
    b.frio()
    arv, c = b.arv, b.cache
    print(f"SELECT * FROM aluno WHERE id = {chave}")
    no, n = arv._le(arv.raiz), 1
    while not no.folha:
        i = bisect_right(no.chaves, chave)
        lado = f"{chave} < {no.chaves[0]}" if i == 0 else f"{chave} >= {no.chaves[i - 1]}"
        vizinhas = no.chaves[max(0, i - 1):i + 1]
        print(f"  leitura {n}: página {no.pagina}, nó interno ({len(no.chaves)} chaves, "
              f"em volta: {vizinhas}): {lado} -> filho {i}")
        no, n = arv._le(no.filhos[i]), n + 1
    rid = arv.busca(chave)
    print(f"  leitura {n}: página {no.pagina}, folha {resumo(no.chaves, chave)}: " +
          (f"achou {chave} -> RID {rid}" if rid else f"{chave} não está aqui"))
    b.frio()                               # a descida acima deixou páginas no cache: a conta oficial
    c, arv = b.cache, b.arv                # recomeça com cache frio e só conta o que busca_registro faz
    reg = busca_registro(c, ESQUEMA_ALUNO, arv, chave)
    if reg is None:
        print(f"  => nenhum registro. Nem chegou à tabela. {b.custo()}")
    else:
        print(f"  leitura {n + 1}: página {rid[0]} da TABELA, slot {rid[1]}")
        print(f"  => (id, matricula) = {reg}  {b.custo()}")


def cmd_varre(b, chave):
    b.frio()
    achados = [r for r in varre(b.cache, ESQUEMA_ALUNO) if r[0] == chave]
    print(f"SELECT * FROM aluno WHERE id = {chave}   (sem índice: lê tudo)")
    print(f"  => {achados[0] if achados else 'nenhum registro'}  {b.custo()}")
    print("  (a varredura também fixa as páginas do índice para pulá-las)")


def cmd_faixa(b, a, z):
    b.frio()
    regs = list(faixa_registros(b.cache, ESQUEMA_ALUNO, b.arv, a, z))
    for r in regs[:10]:
        print(f"  {r}")
    if len(regs) > 10:
        print(f"  ... (mais {len(regs) - 10})")
    print(f"  => {len(regs)} registros  {b.custo()}")


def pagina_para_inserir(arv):
    """Dica de onde gravar: a página de dados do maior id (a folha mais à direita).
    Se não couber, o insere() do M2 aloca outra. Achar isso custa a altura da árvore;
    procurar a última página de dados varrendo o arquivo leria o índice inteiro."""
    no = arv._le(arv.raiz)
    while not no.folha:
        no = arv._le(no.filhos[-1])
    return no.rids[-1][0]


def cmd_insere(b, chave, matricula):
    b.frio()
    try:
        insere_indexado(b.cache, ESQUEMA_ALUNO, b.arv, (chave, matricula), pagina_para_inserir(b.arv))
    except ChaveDuplicada:
        print(f"  recusado: o id {chave} já existe (nada foi gravado). {b.custo()}")
        return
    except ValueError as e:
        print(f"  recusado: {e}")
        return
    print(f"  inserido ({chave}, {matricula}). altura do índice: {b.arv.altura()}  {b.custo()}")
    b.cache.grava_tudo()                        # sem log: durabilidade é gravar


def cmd_arvore(b):
    b.frio()
    niveis = b.arv.niveis()
    n = sum(len(x) for x in niveis)
    if n > 40:
        print(f"  árvore com {n} nós em {len(niveis)} níveis: grande demais para desenhar.")
        print(f"  raiz: {resumo(niveis[0][0])}")
        return
    print(b.arv.desenha())


def cmd_info(b):
    b.frio()
    _, _, total = le_metadados(b.cache)
    folhas = sum(1 for _ in b.arv.folhas())
    chaves = sum(len(f.chaves) for f in b.arv.folhas())
    print(f"  arquivo: {total} páginas de 4096 bytes")
    print(f"  índice: {chaves} chaves em {folhas} folhas, altura {b.arv.altura()} "
          f"(busca = {b.arv.altura()} páginas do índice + 1 da tabela)")


def executa(b, partes):
    cmd, args = partes[0].lower(), partes[1:]
    try:
        if cmd == "busca" and len(args) == 1:
            cmd_busca(b, int(args[0]))
        elif cmd == "varre" and len(args) == 1:
            cmd_varre(b, int(args[0]))
        elif cmd == "faixa" and len(args) == 2:
            cmd_faixa(b, int(args[0]), int(args[1]))
        elif cmd == "insere" and len(args) == 2:
            cmd_insere(b, int(args[0]), int(args[1]))
        elif cmd == "arvore" and not args:
            cmd_arvore(b)
        elif cmd == "info" and not args:
            cmd_info(b)
        elif cmd in ("ajuda", "help", "?"):
            print("Comandos" + AJUDA)
        else:
            print("  comando não entendido. Digite 'ajuda'.")
    except ValueError as e:
        print(f"  erro: {e}")


def abre_ou_cria(caminho, n):
    if not os.path.exists(caminho):
        print(f"{caminho} não existe: criando a tabela com {n} alunos e o índice...")
        cria_tabela_m1(caminho, n)
        with open(caminho, "r+b") as f:
            c = CachePaginas(f, 32)
            arv = ArvoreBMais.cria(c)
            indexa_tabela(c, ESQUEMA_ALUNO, arv)
            c.grava_tudo()
    try:
        return Banco(caminho)
    except SemIndice:
        sys.exit(f"{caminho} é uma tabela sem índice. Apague-o para recriar, ou use outro nome.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    caminho = sys.argv[1]
    resto = sys.argv[2:]
    n = int(resto[0]) if len(resto) == 1 and resto[0].isdigit() else 10_000
    b = abre_ou_cria(caminho, n)
    try:
        if resto and not (len(resto) == 1 and resto[0].isdigit()):
            executa(b, resto)                     # um comando só
            return
        cmd_info(b)
        print("Digite 'ajuda' para os comandos, 'sair' para sair. Ex.: busca 7500")
        while True:
            try:
                linha = input("indice> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not linha:
                continue
            if linha.lower() in ("sair", "exit", "quit"):
                break
            executa(b, shlex.split(linha))
    finally:
        b.fim()


if __name__ == "__main__":
    main()
