"""Identificadores: enviar como NOVO ou SOBREPOR o último envio.

novo      todo envio gera Series/SOP Instance UIDs inéditos → o PACS sempre recebe
          imagem nova (nunca é tratada como duplicata).
sobrepor  reutiliza os UIDs gravados do último envio daquele equipamento →
          o PACS recebe a MESMA instância (testa duplicata / substituição).
          Na primeira vez não há "último", então se comporta como novo e grava.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydicom.uid import generate_uid

ARQUIVO = Path(__file__).resolve().parent.parent / "estado" / "envios.json"


class Registro:
    def __init__(self, arquivo=ARQUIVO):
        self.arquivo = Path(arquivo)
        try:
            self.dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except Exception:
            self.dados = {}

    def salvar(self):
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo.write_text(json.dumps(self.dados, indent=1), encoding="utf-8")

    def ids(self, equipamento, modo, serie, imagem, estudo_padrao=None):
        """Devolve (estudo_uid, serie_uid, sop_uid, reaproveitado)."""
        chave = f"{equipamento}|{serie}|{imagem}"
        anterior = self.dados.get(chave)
        if modo == "sobrepor" and anterior:
            return anterior["estudo"], anterior["serie"], anterior["sop"], True
        novo = {"estudo": estudo_padrao or generate_uid(),
                "serie": generate_uid(), "sop": generate_uid()}
        return novo["estudo"], novo["serie"], novo["sop"], False

    def gravar(self, equipamento, serie, imagem, estudo, serie_uid, sop):
        self.dados[f"{equipamento}|{serie}|{imagem}"] = {
            "estudo": estudo, "serie": serie_uid, "sop": sop}
