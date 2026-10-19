"""Pequenas utilidades de apresentação."""


def nome_legivel(pn):
    """Nome de pessoa DICOM -> 'Nome Sobrenome'.

    No DICOM o nome vem como `Sobrenome^Nome^Nome do meio^Prefixo^Sufixo`: o `^`
    separa componentes e o sobrenome vem PRIMEIRO. Só a exibição muda; o valor
    enviado ao PACS continua exatamente como veio.
    """
    grupo = str(pn or "").split("=")[0]          # ignora representações ideográficas/fonéticas
    f = (grupo.split("^") + [""] * 5)[:5]
    familia, nome, meio, prefixo, sufixo = (x.strip() for x in f)
    partes = [prefixo, nome, meio, familia, sufixo]
    return " ".join(p for p in partes if p) or "(sem nome)"
