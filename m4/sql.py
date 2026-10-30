"""
sql.py - M4, parte 1: do texto à árvore (tokenizador + parser).

    texto --tokeniza--> lista de tokens --Parser--> árvore sintática (dict)

O que o resto do minidb chama é `analisa(sql)`. Nada aqui sabe o que é uma
tabela, uma página ou o catálogo: "a tabela existe?" é a etapa 3 (executor.py).

A gramática do minidb:

    comando := ( create | insert | select ) [ ; ]
    create  := CREATE TABLE nome ( coluna { , coluna } )
    coluna  := nome INT  |  nome CHAR ( número )
    insert  := INSERT INTO nome VALUES ( valor { , valor } )
    select  := SELECT ( * | nome { , nome } ) FROM nome [ WHERE nome = valor ]
    valor   := número  |  texto

    [ ] opcional, { } repete zero ou mais vezes, | escolha.

Cada regra é uma função do Parser: obrigatório vira `espera`, [ ] vira
`if aceita`, { } vira `while aceita`, | vira if/else olhando o próximo token.
"""

from erros import ErroLexico, ErroSintatico

PALAVRAS = {"CREATE", "TABLE", "INSERT", "INTO", "VALUES",
            "SELECT", "FROM", "WHERE", "INT", "CHAR"}
DIGITOS = "0123456789"          # só ASCII: '²'.isdigit() é True e int('²') estoura


# ---------- etapa 1: tokenizador ----------

def tokeniza(sql):
    """Texto -> lista de pares (tipo, valor), em ordem, terminada em (FIM, None).

    Tipos: PALAVRA (reservada, sempre em maiúsculas), NOME, NUMERO (já int),
    TEXTO (sem as aspas), SIMBOLO, FIM. Espaço some. Não olha a ordem: para
    ele `TABLE CREATE ( (` passa sem reclamar. Quem olha a ordem é o parser."""
    tokens, i = [], 0
    while i < len(sql):
        c = sql[i]
        if c.isspace():
            i += 1
        elif c.isalpha():                               # palavra reservada ou nome
            j = i
            while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            p = sql[i:j]
            tokens.append(("PALAVRA", p.upper()) if p.upper() in PALAVRAS else ("NOME", p))
            i = j
        elif c in DIGITOS:                              # mesmo laço, com dígitos
            j = i
            while j < len(sql) and sql[j] in DIGITOS:
                j += 1
            try:
                tokens.append(("NUMERO", int(sql[i:j])))
            except ValueError:                          # milhares de dígitos
                raise ErroLexico(f"número grande demais na posição {i}") from None
            i = j
        elif c == "'":                                  # texto vai até a próxima aspa
            j = sql.find("'", i + 1)
            if j < 0:
                raise ErroLexico(f"aspas sem fechamento na posição {i}")
            tokens.append(("TEXTO", sql[i + 1:j]))
            i = j + 1
        elif c in "(),;*=":
            tokens.append(("SIMBOLO", c))
            i += 1
        else:
            raise ErroLexico(f"caractere inesperado {c!r} na posição {i}")
    return tokens + [("FIM", None)]


# ---------- etapa 2: parser (descida recursiva) ----------

class Parser:
    def __init__(self, tokens):
        self.tokens, self.i = tokens, 0

    def olha(self):
        return self.tokens[self.i]

    def aceita(self, tipo, valor):
        """Consome o token só se casar, e diz se casou."""
        if self.tokens[self.i] == (tipo, valor):
            self.i += 1
            return True
        return False

    def espera(self, tipo, valor=None):
        """Consome o token ou dá erro de sintaxe. Devolve o valor do token."""
        t, v = self.tokens[self.i]
        if t != tipo or (valor is not None and v != valor):
            raise ErroSintatico(f"esperava {valor or tipo}, veio {_mostra(t, v)}")
        self.i += 1
        return v

    def valor(self):
        t, v = self.olha()
        if t in ("NUMERO", "TEXTO"):
            self.i += 1
            return v
        raise ErroSintatico(f"esperava valor, veio {_mostra(t, v)}")

    # --- uma função por regra da gramática ---

    def comando(self):
        t, v = self.olha()
        # confere o TIPO também: o texto 'CREATE' (entre aspas) não é o comando CREATE
        if (t, v) == ("PALAVRA", "CREATE"):
            arvore = self.create()
        elif (t, v) == ("PALAVRA", "INSERT"):
            arvore = self.insert()
        elif (t, v) == ("PALAVRA", "SELECT"):
            arvore = self.select()
        else:
            raise ErroSintatico(f"comando desconhecido {_mostra(t, v)}")
        self.aceita("SIMBOLO", ";")
        self.espera("FIM")                              # sobrou token? é erro
        return arvore

    def create(self):
        self.espera("PALAVRA", "CREATE")
        self.espera("PALAVRA", "TABLE")
        tabela = self.espera("NOME")
        self.espera("SIMBOLO", "(")
        colunas = [self.coluna()]
        while self.aceita("SIMBOLO", ","):
            colunas.append(self.coluna())
        self.espera("SIMBOLO", ")")
        return {"op": "CREATE", "tabela": tabela, "colunas": colunas}

    def coluna(self):
        nome = self.espera("NOME")
        if self.aceita("PALAVRA", "INT"):
            return (nome, "INT", 4)
        if not self.aceita("PALAVRA", "CHAR"):
            t, v = self.olha()
            raise ErroSintatico(f"esperava INT ou CHAR, veio {_mostra(t, v)}")
        self.espera("SIMBOLO", "(")
        n = self.espera("NUMERO")
        self.espera("SIMBOLO", ")")
        return (nome, "CHAR", n)

    def insert(self):
        self.espera("PALAVRA", "INSERT")
        self.espera("PALAVRA", "INTO")
        tabela = self.espera("NOME")
        self.espera("PALAVRA", "VALUES")
        self.espera("SIMBOLO", "(")
        valores = [self.valor()]
        while self.aceita("SIMBOLO", ","):
            valores.append(self.valor())
        self.espera("SIMBOLO", ")")
        return {"op": "INSERT", "tabela": tabela, "valores": valores}

    def select(self):
        self.espera("PALAVRA", "SELECT")
        if self.aceita("SIMBOLO", "*"):
            colunas = ["*"]
        else:
            colunas = [self.espera("NOME")]
            while self.aceita("SIMBOLO", ","):
                colunas.append(self.espera("NOME"))
        self.espera("PALAVRA", "FROM")
        tabela = self.espera("NOME")
        where = None
        if self.aceita("PALAVRA", "WHERE"):
            coluna = self.espera("NOME")
            self.espera("SIMBOLO", "=")
            where = (coluna, self.valor())
        return {"op": "SELECT", "colunas": colunas, "tabela": tabela, "where": where}


def _mostra(tipo, valor):
    """Como o token aparece numa mensagem: o FIM não tem valor para mostrar."""
    return "o fim do comando" if tipo == "FIM" else repr(valor)


def analisa(sql):
    """Texto -> árvore sintática. É o que o resto do minidb chama."""
    return Parser(tokeniza(sql)).comando()
