"""
Exercício de hoje: 3 frames, LRU, acessos 1, 2, 3, 1, 4, 2, 5, 1, 2, 3.
Roda no esqueleto do M2 (classe Cache abaixo, exatamente como veio), com um
pager falso que só registra o que iria ao disco.

Rodar:  python exercicio_hoje.py
"""

from collections import OrderedDict


# ---------------- o esqueleto do M2, sem alteração ----------------
class Cache:
    def __init__(self, pager, capacidade=16):
        self.pager, self.cap = pager, capacidade
        self.frames = {}              # pagina -> buffer
        self.suja = set()
        self.fixada = {}              # pagina -> contador
        self.uso = OrderedDict()      # ordem de uso, mais antigo primeiro
        self.acertos = self.faltas = 0

    def fixa(self, n):
        if n in self.frames:
            self.acertos += 1
            self.uso.move_to_end(n)
        else:
            self.faltas += 1
            if len(self.frames) == self.cap:
                self._expulsa()
            self.frames[n] = self.pager.le(n)
            self.uso[n] = True
        self.fixada[n] = self.fixada.get(n, 0) + 1
        return self.frames[n]

    def solta(self, n, sujou=False):
        if sujou:
            self.suja.add(n)
        self.fixada[n] -= 1

    def _expulsa(self):
        for n in list(self.uso):      # do mais antigo para o mais novo
            if self.fixada.get(n, 0) == 0:
                if n in self.suja:
                    self.pager.escreve(n, self.frames[n])
                    self.suja.discard(n)
                del self.frames[n], self.uso[n]
                return
        raise RuntimeError("todas as páginas estão fixadas")

    def descarrega(self):             # no fim do programa, e no commit do M6
        for n in list(self.suja):
            self.pager.escreve(n, self.frames[n])
        self.suja.clear()
        self.pager.sync()


# ---------------- pager falso: só anota o que iria ao disco ----------------
class PagerFalso:
    def __init__(self):
        self.eventos = []             # zerado a cada acesso pelo laço abaixo

    def le(self, n):
        self.eventos.append(f"lê {n}")
        return bytearray(4096)

    def escreve(self, n, buf):
        self.eventos.append(f"ESCREVE {n}")

    def sync(self):
        self.eventos.append("sync")


ACESSOS = [1, 2, 3, 1, 4, 2, 5, 1, 2, 3]


def roda(capacidade, alteradas, titulo):
    """alteradas: conjunto de posições (1..10) em que o acesso altera a página."""
    print(f"\n=== {titulo} ===")
    pager = PagerFalso()
    c = Cache(pager, capacidade)
    print(f"{'#':>2} {'pág':>3} {'resultado':>9}  {'frames (mais antigo → mais novo)':34} disco")
    escritas = []
    for i, n in enumerate(ACESSOS, 1):
        pager.eventos = []
        antes = c.acertos
        buf = c.fixa(n)
        c.solta(n, sujou=(i in alteradas))
        res = "acerto" if c.acertos > antes else "FALTA"
        marca = "  (suja)" if n in c.suja else ""
        print(f"{i:>2} {n:>3} {res:>9}  {str(list(c.uso)):34} {', '.join(pager.eventos)}{marca}")
        escritas += [(i, e) for e in pager.eventos if e.startswith("ESCREVE")]
    pager.eventos = []
    c.descarrega()
    fim = [e for e in pager.eventos if e.startswith("ESCREVE")]
    print(f"   fim: descarrega() -> {', '.join(pager.eventos)}")
    print(f"faltas={c.faltas} acertos={c.acertos} | frames no fim: {list(c.uso)}")
    todas = [f"{e} no acesso {i}" for i, e in escritas] + [f"{e} no descarrega()" for e in fim]
    print(f"escritas em disco: {len(todas)} -> {'; '.join(todas) if todas else 'nenhuma'}")
    return c.faltas


if __name__ == "__main__":
    # Alterações: a página 2 no acesso 2 (1ª vez em que está no cache) e a 5 no acesso 7.
    f3 = roda(3, {2, 7}, "3 frames, LRU  (itens 1, 2 e 3)")
    f4 = roda(4, {2, 7}, "4 frames, LRU  (item 4)")
    print(f"\nfaltas com 3 frames: {f3}; com 4 frames: {f4}; diferença: {f3 - f4}")
    roda(3, {2, 7, 9}, "variante: a página 2 também é alterada no acesso 9 (3 frames)")
