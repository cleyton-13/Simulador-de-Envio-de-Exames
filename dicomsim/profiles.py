"""Perfis: destinos (PACS/RIS/impressora) + equipamentos + perfis de fabricante.

Tudo vive em `perfis.json` — um único arquivo no lugar de config.json,
equipamentos.json e modalidades.json.

Os perfis de fabricante são APROXIMAÇÕES (nome do fabricante/modelo gravado nas
imagens e estrutura típica de séries). Servem para exercitar o PACS com cabeçalhos
variados; não reproduzem o comportamento interno de cada aparelho.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .netutil import Alvo

ARQUIVO = Path(__file__).resolve().parent.parent / "perfis.json"


@dataclass
class Equipamento:
    nome: str
    aet: str
    modalidade: str = "CT"
    fabricante: str = ""
    modelo: str = ""
    setor: str = ""
    destino: str = "local"                 # chave em perfis.json["destinos"]
    series: list = field(default_factory=lambda: [{"descricao": "SERIE 1", "imagens": 1}])
    mpps: bool = True
    commitment: bool = False
    imprimir: bool = False
    origem_imagens: str = "real"          # real | anomala | sintetica
    identidade: str = "novo"              # novo | sobrepor (reenvia os mesmos UIDs do último)
    porta_escuta: int = 0                  # onde recebe o N-EVENT-REPORT (0 = sorteia)

    @classmethod
    def de_dict(cls, d, base=None):
        d = {**(base or {}), **d}
        campos = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in campos})


@dataclass
class Destino:
    pacs: Alvo
    ris: Alvo | None = None
    impressora: Alvo | None = None


def _alvo(d):
    return Alvo(d["aet"], d.get("ip", "127.0.0.1"), int(d.get("porta", 104))) if d else None


def carregar(arquivo=ARQUIVO):
    return json.loads(Path(arquivo).read_text(encoding="utf-8"))


def salvar(dados, arquivo=ARQUIVO):
    Path(arquivo).write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")


def destino(dados, chave) -> Destino:
    d = dados["destinos"][chave]
    return Destino(_alvo(d["pacs"]), _alvo(d.get("ris")), _alvo(d.get("impressora")))


def equipamento(dados, nome) -> Equipamento:
    for e in dados["equipamentos"]:
        if e["nome"] == nome:
            base = dados.get("fabricantes", {}).get(e.get("fabricante", ""), {})
            return Equipamento.de_dict(e, base.get("padrao"))
    raise KeyError(f"equipamento '{nome}' não existe em perfis.json")


def equipamentos(dados):
    return [equipamento(dados, e["nome"]) for e in dados["equipamentos"]]


# ---------------------------------------------------------------- cadastro
MODALIDADES = {
    "CT": "Tomografia (CT)", "MR": "Ressonância (MR)", "CR": "Radiografia computadorizada (CR)",
    "DX": "Radiografia digital (DX)", "US": "Ultrassom (US)", "XA": "Angiografia (XA)",
    "MG": "Mamografia (MG)", "RF": "Fluoroscopia (RF)", "PT": "PET (PT)",
    "NM": "Medicina nuclear (NM)", "OT": "Outros / captura (OT)",
}

# Pontos de partida para o cadastro de destinos (valores padrão de cada produto).
MODELOS_DESTINO = {
    "Servidor virtual local": {"pacs": {"aet": "PACS_TESTE", "ip": "127.0.0.1", "porta": 11112},
                               "ris": "mesmo", "impressora": "mesmo"},
    "Orthanc (padrão)": {"pacs": {"aet": "ORTHANC", "ip": "127.0.0.1", "porta": 4242},
                         "ris": "mesmo", "impressora": None},
    "dcm4chee (padrão)": {"pacs": {"aet": "DCM4CHEE", "ip": "127.0.0.1", "porta": 11112},
                          "ris": "mesmo", "impressora": None},
    "Em branco": {"pacs": {"aet": "", "ip": "", "porta": 104}, "ris": None, "impressora": None},
}


def validar_aet(aet):
    """AE Title: 1 a 16 caracteres, sem espaços nas pontas, sem barra invertida."""
    if not aet or not aet.strip():
        return "Informe o AE Title."
    if aet != aet.strip():
        return "O AE Title não pode ter espaço no início ou no fim."
    if len(aet) > 16:
        return f"O AE Title tem {len(aet)} caracteres; o máximo do DICOM é 16."
    if "\\" in aet:
        return "O AE Title não pode ter barra invertida."
    return None


def usos_do_destino(dados, chave):
    return [e["nome"] for e in dados["equipamentos"] if e.get("destino") == chave]


def salvar_destino(dados, chave, destino_dict, chave_antiga=None):
    """Cria/atualiza. Se renomear, atualiza os equipamentos que o usavam."""
    if not chave.strip():
        raise ValueError("Informe um nome para o destino.")
    if chave != chave_antiga and chave in dados["destinos"]:
        raise ValueError(f"Já existe um destino chamado '{chave}'.")
    erro = validar_aet(destino_dict["pacs"]["aet"])
    if erro:
        raise ValueError("PACS: " + erro)
    if not destino_dict["pacs"].get("ip", "").strip():
        raise ValueError("Informe o IP ou nome do servidor do PACS.")
    if chave_antiga and chave_antiga != chave:
        dados["destinos"].pop(chave_antiga, None)
        for e in dados["equipamentos"]:
            if e.get("destino") == chave_antiga:
                e["destino"] = chave
    dados["destinos"][chave] = destino_dict
    return dados


def excluir_destino(dados, chave):
    usos = usos_do_destino(dados, chave)
    if usos:
        raise ValueError("Não dá para excluir: usado por " + ", ".join(usos)
                         + ". Troque o destino desses equipamentos antes.")
    if len(dados["destinos"]) <= 1:
        raise ValueError("Precisa existir pelo menos um destino.")
    dados["destinos"].pop(chave, None)
    return dados


def salvar_equipamento(dados, eq_dict, nome_antigo=None):
    nome = eq_dict["nome"].strip()
    if not nome:
        raise ValueError("Informe o nome do equipamento.")
    if nome != nome_antigo and any(e["nome"] == nome for e in dados["equipamentos"]):
        raise ValueError(f"Já existe um equipamento chamado '{nome}'.")
    erro = validar_aet(eq_dict["aet"])
    if erro:
        raise ValueError(erro)
    if eq_dict.get("destino") not in dados["destinos"]:
        raise ValueError("Escolha um destino válido.")
    if not eq_dict.get("series"):
        raise ValueError("Cadastre pelo menos uma série.")
    eq_dict["nome"] = nome
    lista = dados["equipamentos"]
    if nome_antigo:
        for i, e in enumerate(lista):
            if e["nome"] == nome_antigo:
                lista[i] = eq_dict
                break
        else:
            lista.append(eq_dict)
    else:
        lista.append(eq_dict)
    return dados


def excluir_equipamento(dados, nome):
    dados["equipamentos"] = [e for e in dados["equipamentos"] if e["nome"] != nome]
    return dados


def destino_para_dict(modelo):
    """Converte um modelo (com 'mesmo'/None) no formato salvo em perfis.json."""
    pacs = dict(modelo["pacs"])
    out = {"pacs": pacs}
    for chave in ("ris", "impressora"):
        v = modelo.get(chave)
        if v == "mesmo":
            out[chave] = dict(pacs)
        elif isinstance(v, dict):
            out[chave] = dict(v)
    return out
