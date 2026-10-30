"""
minidb_indice.py - M3: liga a árvore B+ (btree.py) à tabela do M1/M2.

A árvore só conhece chave -> (página, slot). Aqui fica o que sabe de tabela:

    insere_indexado   grava o registro na tabela e a chave no índice
    busca_registro    chave -> RID (pela árvore) -> registro (uma página da tabela)
    faixa_registros   BETWEEN: percorre as folhas e busca cada registro
    indexa_tabela     constrói o índice de uma tabela que já existia (a do M1)

Tudo passa pelo cache do M2. A coluna indexada é a primeira do esquema (o id).
"""

from btree import ChaveDuplicada
from minidb import HEADER_SIZE, le_cabecalho
from minidb_cache import insere, le_metadados

COLUNA_CHAVE = 0     # o id, primeira coluna do esquema `aluno`


def insere_indexado(cache, esquema, arvore, valores, pagina_atual):
    """Insere na tabela e no índice. Devolve (rid, pagina_a_usar_na_proxima),
    como o insere() do M2.

    A duplicata é recusada ANTES de gravar na tabela: se fosse depois, o
    registro ficaria na tabela sem entrada no índice (e invisível para a busca)."""
    chave = valores[COLUNA_CHAVE]
    if arvore.busca(chave) is not None:
        raise ChaveDuplicada(chave)
    rid, pagina_atual = insere(cache, esquema, valores, pagina_atual)
    arvore.insere(chave, rid)
    return rid, pagina_atual


def le_registro(cache, esquema, rid):
    """Lê o registro do RID: fixa UMA página da tabela, solta."""
    pagina, slot = rid
    with cache.usa(pagina) as buf:
        n_slots, tam_registro, _ = le_cabecalho(buf)
        if tam_registro == 0 or slot >= n_slots:
            raise ValueError(f"rid {rid} aponta para um slot que não existe (página com {n_slots} slots)")
        off = HEADER_SIZE + slot * tam_registro
        return esquema.desserializa(bytes(buf[off:off + tam_registro]))


def busca_registro(cache, esquema, arvore, chave):
    """WHERE id = chave. Desce a árvore (altura páginas) e lê 1 página da
    tabela, sem varrê-la. Devolve a tupla do registro, ou None."""
    rid = arvore.busca(chave)
    if rid is None:
        return None
    registro = le_registro(cache, esquema, rid)
    assert registro[COLUNA_CHAVE] == chave, f"índice aponta {rid} para {registro}, procurava {chave}"
    return registro


def faixa_registros(cache, esquema, arvore, minimo, maximo):
    """WHERE id BETWEEN minimo AND maximo, em ordem de id."""
    for chave, rid in arvore.faixa(minimo, maximo):
        yield le_registro(cache, esquema, rid)


def indexa_tabela(cache, esquema, arvore):
    """Constrói o índice de uma tabela que já tem registros (os do M1,
    feitos antes do M3): uma varredura, e cada registro vira uma entrada
    chave -> (página, slot). Devolve quantos indexou."""
    _, _, total = le_metadados(cache)
    indexados = 0
    for pagina in range(1, total):
        with cache.usa(pagina) as buf:
            n_slots, tam_registro, _ = le_cabecalho(buf)
            if tam_registro == 0:                 # nó do índice, não é de dados
                continue
            achados = [
                (esquema.desserializa(bytes(buf[HEADER_SIZE + s * tam_registro:
                                                HEADER_SIZE + (s + 1) * tam_registro]))[COLUNA_CHAVE], s)
                for s in range(n_slots)
            ]
        # o buffer já foi solto: a árvore pode precisar de frames para si
        for chave, slot in achados:
            arvore.insere(chave, (pagina, slot))
            indexados += 1
    return indexados
