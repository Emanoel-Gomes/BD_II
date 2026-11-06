import os
import struct

PAGE_SIZE = 4096
HEADER_SIZE = 16
RECORD_SIZE = 8

ARQUIVO = "dados.db"
PAGINA = 2
SLOT = 0


def _garante_tamanho(f, n):
    f.seek(0, os.SEEK_END)
    tamanho_atual = f.tell()
    tamanho_necessario = (n + 1) * PAGE_SIZE
    if tamanho_atual < tamanho_necessario:
        f.write(b"\x00" * (tamanho_necessario - tamanho_atual))


def escreve_pagina(f, n, dados):
    assert len(dados) == PAGE_SIZE, "página precisa ter exatamente 4096 bytes"
    try:
        _garante_tamanho(f, n)
        f.seek(n * PAGE_SIZE)
        escritos = f.write(dados)
        f.flush()
        os.fsync(f.fileno())
    except OSError as erro:
        print(f"[erro] falha ao escrever a página {n} em {f.name}: {erro}")
        raise

    if escritos != PAGE_SIZE:
        print(f"[erro] escrita incompleta na página {n}: {escritos} de {PAGE_SIZE} bytes gravados")


def le_pagina(f, n):
    try:
        _garante_tamanho(f, n)
        f.seek(n * PAGE_SIZE)
        dados = f.read(PAGE_SIZE)
    except OSError as erro:
        print(f"[erro] falha ao ler a página {n} de {f.name}: {erro}")
        raise

    if len(dados) < PAGE_SIZE:
        dados += b"\x00" * (PAGE_SIZE - len(dados))
    return dados


def grava_registro_pagina2():
    modo = "r+b" if os.path.exists(ARQUIVO) else "w+b"
    with open(ARQUIVO, modo) as f:
        pagina = bytearray(le_pagina(f, PAGINA))

        registro = struct.pack("<ii", 1, 20260001)  # id=1, matricula=20260001
        offset_na_pagina = HEADER_SIZE + SLOT * RECORD_SIZE
        pagina[offset_na_pagina:offset_na_pagina + RECORD_SIZE] = registro

        # atualiza o cabeçalho: 1 slot ocupado
        pagina[0:4] = struct.pack("<I", 1)

        escreve_pagina(f, PAGINA, bytes(pagina))

    offset_absoluto = PAGINA * PAGE_SIZE + offset_na_pagina
    print(f"[processo 1] registro gravado no byte {offset_absoluto} do arquivo {ARQUIVO}")
    # hexdump nem sempre vem instalado por padrão; 'od' é mais garantido.
    # Se tiver hexdump na sua máquina, o equivalente é:
    #   hexdump -C dados.db -s {offset_absoluto} -n {RECORD_SIZE}
    print(f"[processo 1] para conferir no disco: od -A d -t x1z -j {offset_absoluto} -N {RECORD_SIZE} {ARQUIVO}")


def le_registro_pagina2():
    with open(ARQUIVO, "rb") as f:
        pagina = le_pagina(f, PAGINA)

    num_slots = struct.unpack("<I", pagina[0:4])[0]
    offset_na_pagina = HEADER_SIZE + SLOT * RECORD_SIZE
    id_, matricula = struct.unpack("<ii", pagina[offset_na_pagina:offset_na_pagina + RECORD_SIZE])

    print(f"[processo 2] slots ocupados no cabeçalho da página {PAGINA}: {num_slots}")
    print(f"[processo 2] registro lido de volta: id={id_}, matricula={matricula}")


def demonstra_falha():
    print("[demo de falha] abrindo o arquivo em modo somente-leitura e tentando escrever nele...")
    with open(ARQUIVO, "rb") as f:
        pagina_fake = b"\x00" * PAGE_SIZE
        try:
            escreve_pagina(f, PAGINA, pagina_fake)
        except OSError:
            print("[demo de falha] escreve_pagina levantou OSError, como esperado (arquivo aberto só-leitura)")


if __name__ == "__main__":
    grava_registro_pagina2()
    le_registro_pagina2()
    demonstra_falha()
