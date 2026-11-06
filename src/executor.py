"""
executor.py - M4, parte 2: análise semântica (etapa 3) e execução (etapa 4).

    analisa(sql)      etapas 1 e 2 (sql.py): texto -> árvore
    confere(...)      etapa 3: a árvore faz sentido PARA ESTE banco? Quem
                      responde é o catálogo: a tabela existe? a coluna existe?
                      o tipo bate? Não mexe em página nenhuma.
    roda(...)         etapa 4: um `if` por comando, direto sobre a árvore,
                      chamando o que o M1, o M2 e o catálogo já têm.

`executa(sql, catalogo, cache)` encadeia as quatro e devolve o texto que o
programa imprime. Cada etapa tem o seu tipo de erro (erros.py): se a etapa 3
falhar, nada foi gravado; se a 1 ou a 2 falhar, o catálogo nem foi consultado.
"""

from catalogo import INT_MAX, INT_MIN, MAX_NOME, tamanho_entrada
from erros import ErroNaoImplementado, ErroSemantico, ErroSQL
from minidb import HEADER_SIZE, PAGE_SIZE
from sql import analisa


# ---------- etapa 3: análise semântica ----------

def _nome_ok(nome, o_que):
    if len(nome.encode("utf-8")) > MAX_NOME:
        raise ErroSemantico(f"{o_que} {nome!r} passa de {MAX_NOME} bytes")


def _confere_valor(coluna, valor):
    """O valor bate com o tipo da coluna? `coluna` é (nome, tipo, tamanho)."""
    nome, tipo, tam = coluna
    if tipo == "INT":
        if not isinstance(valor, int):
            raise ErroSemantico(f"a coluna {nome} é INT, veio o texto {valor!r}")
        if not INT_MIN <= valor <= INT_MAX:
            raise ErroSemantico(f"a coluna {nome} é INT de 32 bits, {valor} não cabe")
    else:
        if not isinstance(valor, str):
            raise ErroSemantico(f"a coluna {nome} é CHAR({tam}), veio o número {valor}")
        if "\x00" in valor:
            raise ErroSemantico(f"o texto da coluna {nome} tem um byte nulo")
        n = len(valor.encode("utf-8"))
        if n > tam:
            raise ErroSemantico(f"o texto {valor!r} tem {n} bytes e não cabe em "
                                f"CHAR({tam}) (coluna {nome})")


def _coluna(tabela, nome):
    i = tabela.indice_coluna(nome)
    if i is None:
        raise ErroSemantico(f"a tabela {tabela.nome} não tem a coluna {nome}")
    return i


def confere(arvore, catalogo):
    """Árvore sintática -> plano, já com a Tabela do catálogo e as colunas
    resolvidas em posições. Levanta ErroSemantico."""
    op = arvore["op"]

    if op == "CREATE":
        nome, colunas = arvore["tabela"], arvore["colunas"]
        _nome_ok(nome, "o nome da tabela")
        if catalogo.existe(nome):
            raise ErroSemantico(f"a tabela {nome} já existe")
        vistos = set()
        for cn, tipo, tam in colunas:
            _nome_ok(cn, "o nome da coluna")
            if cn.lower() in vistos:
                raise ErroSemantico(f"a coluna {cn} aparece duas vezes")
            vistos.add(cn.lower())
            if tipo == "CHAR" and tam < 1:
                raise ErroSemantico(f"CHAR({tam}): o tamanho precisa ser pelo menos 1 (coluna {cn})")
        if len(colunas) > 255:
            raise ErroSemantico(f"{len(colunas)} colunas: o catálogo guarda no máximo 255 por tabela")
        registro = sum(tam for _, _, tam in colunas)
        if registro > PAGE_SIZE - HEADER_SIZE:
            raise ErroSemantico(f"o registro teria {registro} bytes e só cabem "
                                f"{PAGE_SIZE - HEADER_SIZE} por página")
        if HEADER_SIZE + tamanho_entrada(nome, colunas) > PAGE_SIZE:
            raise ErroSemantico("colunas demais para uma entrada do catálogo")
        return {"op": op, "tabela": nome, "colunas": colunas}

    tabela = catalogo.busca(arvore["tabela"])            # a tabela existe?

    if op == "INSERT":
        valores = arvore["valores"]
        if len(valores) != len(tabela.colunas):
            raise ErroSemantico(f"a tabela {tabela.nome} tem {len(tabela.colunas)} colunas, "
                                f"vieram {len(valores)} valores")
        for coluna, valor in zip(tabela.colunas, valores):
            _confere_valor(coluna, valor)                # o tipo bate?
        return {"op": op, "tabela": tabela, "valores": valores}

    if op == "SELECT":
        if arvore["colunas"] == ["*"]:
            indices = list(range(len(tabela.colunas)))
        else:
            indices = [_coluna(tabela, c) for c in arvore["colunas"]]   # a coluna existe?
        where = arvore["where"]
        if where is not None:
            i = _coluna(tabela, where[0])
            _confere_valor(tabela.colunas[i], where[1])
            where = (i, where[1])
        return {"op": op, "tabela": tabela, "indices": indices, "where": where}

    raise AssertionError(f"o parser devolveu um op desconhecido: {op!r}")


# ---------- etapa 4: execução ----------

def roda(plano, catalogo, cache):
    op = plano["op"]

    if op == "CREATE":
        catalogo.cria(plano["tabela"], plano["colunas"])
        cache.grava_tudo()          # "OK" tem que valer depois de um kill: ver NOTES.md
        return "OK"

    if op == "INSERT":
        catalogo.insere(plano["tabela"], plano["valores"])
        cache.grava_tudo()
        return "OK 1"

    if op == "SELECT":
        if plano["where"] is not None:
            raise ErroNaoImplementado("o WHERE é conferido, mas só passa a ser executado "
                                      "no M5 (junto com os operadores)")
        linhas = ["|".join(str(l[i]) for i in plano["indices"])
                  for l in catalogo.varre(plano["tabela"])]
        n = len(linhas)
        return "\n".join(linhas + [f"({n} {'linha' if n == 1 else 'linhas'})"])

    raise AssertionError(f"op desconhecido: {op!r}")


def executa(sql, catalogo, cache):
    """O que o laço principal chama: um comando de texto -> o texto da resposta.
    Erro de qualquer etapa vira uma linha `ERRO <etapa>: <mensagem>`."""
    try:
        arvore = analisa(sql)                    # etapas 1 e 2
        plano = confere(arvore, catalogo)        # etapa 3
        return roda(plano, catalogo, cache)      # etapa 4
    except ErroSQL as e:
        return f"ERRO {e.etapa}: {e}"
