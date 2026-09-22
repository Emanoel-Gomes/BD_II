"""
minidb - fechamento do M1: deslocamento, cabeçalho, página 0,
serialização, aloca() e varredura.

Reaproveita le_pagina/escreve_pagina de minidb_m1.py (não mexe neles).
Isso aqui é o que faltava do checklist "Onde vocês precisam estar":

    - deslocamento(pagina, slot, tam_registro): a fórmula, num lugar só
    - cabeçalho de 16 bytes de verdade (n_slots, tam_registro, num_pagina)
    - página 0 com número mágico, versão, tamanho de página, total de páginas
    - Esquema como objeto; serializa/desserializa derivados dele
    - aloca(): página nova de dados, contada no metadado da página 0
    - insere(): acha espaço (usa a página atual ou aloca outra), grava, devolve o RID
    - varredura(): percorre todos os registros, contando quantas leituras faz
"""

import os
import struct

from minidb_m1 import escreve_pagina, le_pagina, PAGE_SIZE, HEADER_SIZE

MAGICO = b"MINIDB\x00\x00"  # 8 bytes
VERSAO = 1


class Esquema:
    """Lista de colunas (nome, formato struct de 1 letra). O tamanho do
    registro é sempre derivado das colunas -- nunca digitado à mão."""

    def __init__(self, colunas):
        self.colunas = colunas  # ex.: [("id", "i"), ("matricula", "i")]
        self.formato = "<" + "".join(fmt for _, fmt in colunas)
        self.tamanho = struct.calcsize(self.formato)

    def serializa(self, valores):
        return struct.pack(self.formato, *valores)

    def desserializa(self, dados):
        return struct.unpack(self.formato, dados[:self.tamanho])


ESQUEMA_ALUNO = Esquema([("id", "i"), ("matricula", "i")])  # 8 bytes, igual ao M1 anterior


def deslocamento(pagina, slot, tam_registro):
    """A fórmula do offset, num lugar só: página x TAM_PAGINA + cabeçalho + slot x tamanho do registro."""
    return pagina * PAGE_SIZE + HEADER_SIZE + slot * tam_registro


# ---------- página 0: metadados ----------

def inicializa_pagina0(f):
    """Cria a página 0: número mágico, versão, tamanho de página e total
    de páginas (1 -- só a própria página 0, por enquanto)."""
    pagina0 = bytearray(PAGE_SIZE)
    pagina0[0:8] = MAGICO
    struct.pack_into("<H", pagina0, 8, VERSAO)
    struct.pack_into("<I", pagina0, 10, PAGE_SIZE)
    struct.pack_into("<I", pagina0, 14, 1)
    escreve_pagina(f, 0, bytes(pagina0))


def le_metadados(f):
    pagina0 = le_pagina(f, 0)
    magico = pagina0[0:8]
    if magico != MAGICO:
        raise ValueError(f"arquivo nao e um minidb (numero magico {magico!r} inesperado)")
    versao = struct.unpack_from("<H", pagina0, 8)[0]
    tam_pagina = struct.unpack_from("<I", pagina0, 10)[0]
    total_paginas = struct.unpack_from("<I", pagina0, 14)[0]
    if tam_pagina != PAGE_SIZE:
        raise ValueError(f"arquivo com pagina de {tam_pagina} bytes, esperado {PAGE_SIZE}")
    return versao, tam_pagina, total_paginas


def _grava_total_paginas(f, total):
    pagina0 = bytearray(le_pagina(f, 0))
    struct.pack_into("<I", pagina0, 14, total)
    escreve_pagina(f, 0, bytes(pagina0))


# ---------- cabeçalho de página (16 bytes) ----------

def le_cabecalho(dados_da_pagina):
    n_slots = struct.unpack_from("<H", dados_da_pagina, 0)[0]
    tam_registro = struct.unpack_from("<H", dados_da_pagina, 2)[0]
    num_pagina = struct.unpack_from("<I", dados_da_pagina, 4)[0]
    return n_slots, tam_registro, num_pagina


def _grava_cabecalho(pagina_bytes, n_slots, tam_registro, num_pagina):
    struct.pack_into("<H", pagina_bytes, 0, n_slots)
    struct.pack_into("<H", pagina_bytes, 2, tam_registro)
    struct.pack_into("<I", pagina_bytes, 4, num_pagina)


# ---------- alocação ----------

def aloca(f, tam_registro):
    """Cria uma página nova de dados: cabeçalho zerado (0 slots), grava
    o total atualizado na página 0, devolve o número da página nova."""
    _, _, total_paginas = le_metadados(f)
    nova = total_paginas
    pagina_bytes = bytearray(PAGE_SIZE)
    _grava_cabecalho(pagina_bytes, 0, tam_registro, nova)
    escreve_pagina(f, nova, bytes(pagina_bytes))
    _grava_total_paginas(f, total_paginas + 1)
    return nova


# ---------- inserção ----------

def _cabe_na_pagina(n_slots, tam_registro):
    espaco_livre = PAGE_SIZE - HEADER_SIZE
    return (n_slots + 1) * tam_registro <= espaco_livre


def insere(f, esquema, valores, pagina_atual):
    """Insere um registro na página atual, se couber, ou aloca outra.
    Devolve (rid, pagina_a_usar_na_proxima_insercao)."""
    dados = le_pagina(f, pagina_atual)
    n_slots, tam_registro, _ = le_cabecalho(dados)

    if not _cabe_na_pagina(n_slots, esquema.tamanho):
        pagina_atual = aloca(f, esquema.tamanho)
        dados = le_pagina(f, pagina_atual)
        n_slots, tam_registro, _ = le_cabecalho(dados)

    slot = n_slots
    pagina_bytes = bytearray(dados)
    off = HEADER_SIZE + slot * esquema.tamanho
    pagina_bytes[off:off + esquema.tamanho] = esquema.serializa(valores)
    _grava_cabecalho(pagina_bytes, n_slots + 1, esquema.tamanho, pagina_atual)
    escreve_pagina(f, pagina_atual, bytes(pagina_bytes))

    rid = (pagina_atual, slot)
    return rid, pagina_atual


# ---------- varredura ----------

def varredura(f, esquema):
    """Percorre todos os registros de todas as páginas de dados (a
    página 0 é metadado, não conta). Devolve (registros, leituras) --
    'leituras' é quantas vezes le_pagina foi chamada aqui dentro."""
    _, _, total_paginas = le_metadados(f)
    registros = []
    leituras = 0

    for pagina in range(1, total_paginas):
        dados = le_pagina(f, pagina)  # 1 leitura por página, sempre -- mesmo se a página estiver vazia
        leituras += 1
        n_slots, tam_registro, _ = le_cabecalho(dados)
        for slot in range(n_slots):
            off = HEADER_SIZE + slot * tam_registro
            registros.append(esquema.desserializa(dados[off:off + tam_registro]))

    return registros, leituras


# ---------- demo: mede páginas e leituras de verdade ----------

def demo(n_registros=1200, arquivo="dados_m1.db"):
    if os.path.exists(arquivo):
        os.remove(arquivo)

    with open(arquivo, "w+b") as f:
        inicializa_pagina0(f)
        pagina_atual = aloca(f, ESQUEMA_ALUNO.tamanho)

        for i in range(1, n_registros + 1):
            _, pagina_atual = insere(f, ESQUEMA_ALUNO, (i, 20260000 + i), pagina_atual)

        _, _, total_paginas = le_metadados(f)
        registros, leituras = varredura(f, ESQUEMA_ALUNO)

    tamanho_bytes = os.path.getsize(arquivo)

    print(f"registros inseridos: {len(registros)}")
    print(f"total de páginas no arquivo (incluindo a página 0 de metadados): {total_paginas}")
    print(f"tamanho do arquivo: {tamanho_bytes} bytes ({tamanho_bytes // PAGE_SIZE} páginas de {PAGE_SIZE} bytes)")
    print(f"leituras que a varredura fez: {leituras}")
    print(f"conferindo: primeiro registro = {registros[0]}, último registro = {registros[-1]}")


if __name__ == "__main__":
    demo()
