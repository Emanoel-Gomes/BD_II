import os
import sys
import signal

TAM_PAGINA = 4096


def escreve_pagina(f, n, buf):
    f.seek(n * TAM_PAGINA)
    f.write(buf)


def filho(arquivo, com_sync):
    novo = not os.path.exists(arquivo)
    f = open(arquivo, "w+b" if novo else "r+b")

    escreve_pagina(f, 2, b"A" * TAM_PAGINA)
    escreve_pagina(f, 3, b"B" * TAM_PAGINA)

    if com_sync:
        f.flush()
        os.fsync(f.fileno())

    print(f"[filho pid={os.getpid()}] escrevi as páginas 2 e 3"
          f"{' e chamei flush()+fsync()' if com_sync else ', SEM flush() nem fsync()'}."
          f" Agora: kill -9")
    sys.stdout.flush()

    # Simula "encerrar o programa com kill -9 sem fechar o arquivo":
    # nunca chama f.close(), e morre imediatamente por SIGKILL.
    os.kill(os.getpid(), signal.SIGKILL)


def descreve_pagina(dados, letra):
    cheia = bytes([ord(letra)]) * TAM_PAGINA
    vazia = b"\x00" * TAM_PAGINA
    if dados == cheia:
        return f"toda '{letra}' (a escrita chegou inteira)"
    if dados == vazia or len(dados) == 0:
        return "vazia/zero (a escrita não chegou)"
    return f"parcial/corrompida: primeiros bytes = {dados[:16]!r}"


def inspeciona(arquivo, rotulo):
    print(f"--- {rotulo} ---")
    if not os.path.exists(arquivo):
        print(f"{arquivo}: nem existe no disco")
        return

    tamanho = os.path.getsize(arquivo)
    print(f"tamanho de {arquivo}: {tamanho} bytes")

    with open(arquivo, "rb") as f:
        f.seek(2 * TAM_PAGINA)
        p2 = f.read(TAM_PAGINA)
        f.seek(3 * TAM_PAGINA)
        p3 = f.read(TAM_PAGINA)

    print(f"página 2: {descreve_pagina(p2, 'A')}")
    print(f"página 3: {descreve_pagina(p3, 'B')}")


def pai():
    casos = [
        ("SEM sync() antes do kill -9", "sem_sync.db", False),
        ("COM sync() antes do kill -9", "com_sync.db", True),
    ]

    for rotulo, arquivo, com_sync in casos:
        if os.path.exists(arquivo):
            os.remove(arquivo)

        pid = os.fork()
        if pid == 0:
            filho(arquivo, com_sync)
            # nunca chega aqui: o filho se mata dentro de filho()
        else:
            _, status = os.waitpid(pid, 0)
            morreu_por_sigkill = os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
            print(f"[pai] filho pid={pid} terminou; morreu por SIGKILL: {morreu_por_sigkill}")
            inspeciona(arquivo, rotulo)
            print()


if __name__ == "__main__":
    pai()
