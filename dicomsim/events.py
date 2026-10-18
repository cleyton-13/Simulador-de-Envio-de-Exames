"""Eventos estruturados.

Cada passo gera um Evento (etapa, status, detalhe). O resultado de um exame é
decidido pelos eventos — nunca por busca de palavras no texto.

Compatível com a tela antiga: além da linha humana, cada evento imprime
`@P {...}` (barra de progresso) e `@E {...}` (evento completo em JSON).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field

OK, FALHA, AVISO, INFO, PULADO = "ok", "falha", "aviso", "info", "pulado"


@dataclass
class Evento:
    etapa: str
    status: str
    detalhe: str = ""
    modalidade: str = ""
    dados: dict = field(default_factory=dict)
    t: float = field(default_factory=time.time)


class Emissor:
    """Coleta eventos, imprime e chama callbacks (thread-safe)."""

    def __init__(self, nome="", imprimir=True, callback=None, total=0):
        self.nome = nome
        self.imprimir = imprimir
        self.callback = callback
        self.total = total
        self.n = 0
        self.eventos: list[Evento] = []
        self._lock = threading.Lock()

    def emitir(self, etapa, status, detalhe="", **dados) -> Evento:
        ev = Evento(etapa, status, detalhe, self.nome, dados)
        with self._lock:
            self.eventos.append(ev)
            if status in (OK, FALHA, PULADO):
                self.n += 1
        if self.imprimir:
            marca = {"ok": "OK", "falha": "FALHOU", "aviso": "AVISO",
                     "info": "..", "pulado": "pulado"}.get(status, status)
            pref = f"[{self.nome}] " if self.nome else ""
            print(f"{pref}[{etapa}] {marca} {detalhe}".rstrip(), flush=True)
            print("@P " + json.dumps({"n": self.n, "total": self.total, "etapa": etapa,
                                      "item": self.nome, "status": status}), flush=True)
            print("@E " + json.dumps(asdict(ev), ensure_ascii=False, default=str), flush=True)
        if self.callback:
            self.callback(ev)
        return ev

    # resumo -----------------------------------------------------------
    def falhas(self):
        return [e for e in self.eventos if e.status == FALHA]

    @property
    def ok(self):
        return not self.falhas()

    def resumo(self):
        return {
            "ok": self.ok,
            "etapas": [{"etapa": e.etapa, "status": e.status, "detalhe": e.detalhe}
                       for e in self.eventos if e.status != INFO],
        }
