"""
minidb_cache.py - M2: as operações do M1 (metadados, aloca, insere,
varredura) reescritas para passar pelo cache.

Regra de ouro: depois que o cache existe, NADA lê nem escreve o arquivo por
fora dele. Se o M1 ler a página 0 direto do disco enquanto o cache guarda
uma versão mais nova e suja dela, existem duas cópias com valores
diferentes (a armadilha "Ler o arquivo sem passar pelo cache"). Por isso até a página 0 vai pelo cache.

O formato em disco é exatamente o do M1 (minidb.py): os mesmos bytes, o
mesmo cabeçalho de 16 bytes, a mesma página 0. Um arquivo feito por um lado
abre no outro.
"""

import struct

from minidb import (
    HEADER_SIZE, MAGICO, PAGE_SIZE,
    _cabe_na_pagina, _grava_cabecalho, le_cabecalho,
)


def le_metadados(cache):
    with cache.usa(0) as p0:
        if bytes(p0[0:8]) != MAGICO:
            raise ValueError(f"arquivo nao e um minidb (numero magico {bytes(p0[0:8])!r})")
        versao = struct.unpack_from("<H", p0, 8)[0]
        tam_pagina = struct.unpack_from("<I", p0, 10)[0]
        total_paginas = struct.unpack_from("<I", p0, 14)[0]
    if tam_pagina != PAGE_SIZE:
        raise ValueError(f"arquivo com pagina de {tam_pagina} bytes, esperado {PAGE_SIZE}")
    return versao, tam_pagina, total_paginas


def aloca(cache, tam_registro):
    """Página nova de dados. O total na página 0 sobe no cache; a página
    0 fica suja e só vai ao disco quando for expulsa ou gravada."""
    _, _, total = le_metadados(cache)
    nova = total
    with cache.usa(nova, escreve=True) as p:
        _grava_cabecalho(p, 0, tam_registro, nova)
    with cache.usa(0, escreve=True) as p0:
        struct.pack_into("<I", p0, 14, total + 1)
    return nova


def insere(cache, esquema, valores, pagina_atual):
    """Igual ao insere() do M1, mas altera o buffer do cache no lugar e só
    marca a página como suja. Devolve (rid, pagina_a_usar_na_proxima)."""
    with cache.usa(pagina_atual) as p:          # só olha: não suja
        n_slots, _, _ = le_cabecalho(p)
    if not _cabe_na_pagina(n_slots, esquema.tamanho):
        pagina_atual = aloca(cache, esquema.tamanho)
        n_slots = 0

    with cache.usa(pagina_atual, escreve=True) as p:
        off = HEADER_SIZE + n_slots * esquema.tamanho
        p[off:off + esquema.tamanho] = esquema.serializa(valores)
        _grava_cabecalho(p, n_slots + 1, esquema.tamanho, pagina_atual)
    return (pagina_atual, n_slots), pagina_atual


def varre(cache, esquema):
    """A varredura do slide "Fixar e soltar": fixa a página, devolve os registros dela,
    solta. O finally cobre o caminho de erro E o caso de o chamador
    abandonar o gerador no meio (o close() do gerador dispara o finally)."""
    _, _, total = le_metadados(cache)
    for n in range(1, total):                   # a página 0 é metadado
        buf = cache.fixa(n)
        try:
            n_slots, tam_registro, _ = le_cabecalho(buf)
            for slot in range(n_slots):
                off = HEADER_SIZE + slot * tam_registro
                yield esquema.desserializa(bytes(buf[off:off + tam_registro]))
        finally:
            cache.solta(n)
