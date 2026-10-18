"""O exame completo de uma modalidade, na ordem de um equipamento de verdade.

  worklist → escolhe exame → MPPS IN PROGRESS → adquire séries (C-STORE)
           → MPPS COMPLETED/DISCONTINUED → Storage Commitment → impressão
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field

from pydicom.uid import generate_uid

from . import library, steps
from .identidade import Registro
from .events import AVISO, FALHA, INFO, OK, PULADO, Emissor
from .netutil import porta_escuta_padrao
from .profiles import Destino, Equipamento


@dataclass
class ResultadoExame:
    equipamento: str
    ok: bool
    paciente: str = ""
    estudo_uid: str = ""
    imagens: int = 0
    eventos: list = field(default_factory=list)


def _porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def exame_sintetico(eq: Equipamento):
    """Paciente de teste quando não há RIS ou o RIS não devolveu nada.
    Acesso e ID são inéditos a cada chamada (o PACS sempre vê um paciente novo)."""
    suf = generate_uid()[-6:]
    return {"nome": "TESTE^SIMULADOR", "id": "SIM" + suf, "acesso": "SIMACC" + suf,
            "estudo_uid": generate_uid(), "modalidade": eq.modalidade,
            "procedimento": f"Exame simulado {eq.modalidade}", "nascimento": "19800101",
            "sexo": "O", "passo": "SPS1", "proc_id": "REQ1", "data": ""}


def executar_exame(eq: Equipamento, dest: Destino, item: dict | None = None,
                   em: Emissor | None = None, usar_worklist=True,
                   porta_escuta=None, registro: Registro | None = None) -> ResultadoExame:
    em = em or Emissor(nome=eq.nome)
    aet = eq.aet
    em.emitir("inicio", INFO, f"{eq.modalidade} · {eq.fabricante} {eq.modelo} · destino {dest.pacs}")

    # 1) worklist ------------------------------------------------------
    if item is None:
        if usar_worklist and dest.ris is not None:
            lista = steps.consultar_worklist(em, aet, dest.ris, modalidade=eq.modalidade)
            if lista:
                item = lista[0]
        elif not usar_worklist:
            em.emitir("worklist", PULADO, "desligada")
        if item is None:
            em.emitir("worklist", AVISO, "sem exame agendado — usando paciente simulado")
            item = exame_sintetico(eq)
    estudo_uid = item.get("estudo_uid") or generate_uid()
    paciente = {**item, "modalidade": item.get("modalidade") or eq.modalidade}

    # 2) MPPS início ---------------------------------------------------
    mpps_uid = None
    if eq.mpps:
        mpps_uid = steps.mpps_criar(em, aet, dest.pacs, item, eq.modalidade, eq.nome)
    else:
        em.emitir("mpps-inicio", PULADO, "equipamento não usa MPPS")

    # 3) aquisição + C-STORE ------------------------------------------
    registro = registro or Registro()
    anomalas = eq.origem_imagens == "anomala"
    series_info, todas, ref_imgs = [], [], []
    contador = 0
    for si, s in enumerate(eq.series, 1):
        dss, serie_uid, reaprov = [], None, 0
        for i in range(int(s.get("imagens", 1))):
            ds = library.obter_imagem(eq.modalidade, contador, eq.origem_imagens)
            est, ser, sop, reuso = registro.ids(eq.nome, eq.identidade, si, i + 1, estudo_uid)
            serie_uid = ser
            reaprov += reuso
            try:
                ds = library.carimbar(ds, paciente, est if reuso else estudo_uid, ser, si, i + 1,
                                      eq.fabricante, eq.modelo, eq.nome, aet, sop_uid=sop)
            except Exception as e:
                em.emitir("aquisicao", AVISO, f"não foi possível carimbar a imagem: {e}")
            ds.SeriesDescription = s.get("descricao", "")
            registro.gravar(eq.nome, si, i + 1, est if reuso else estudo_uid, ser, sop)
            dss.append(ds)
            contador += 1
        em.emitir("aquisicao", INFO,
                  f"série {si} '{s.get('descricao','')}': {len(dss)} imagem(ns), "
                  f"{'MESMOS UIDs do envio anterior (sobrepor)' if reaprov else 'UIDs inéditos'}")
        res = steps.armazenar(em, aet, dest.pacs, dss, anomalas=anomalas)
        enviadas = [(r["classe"], r["instancia"]) for r in res if r["ok"]]
        ref_imgs += enviadas
        todas += dss
        series_info.append({"uid": serie_uid, "descricao": s.get("descricao", ""),
                            "instancias": enviadas,
                            "falhas": 0 if anomalas else sum(1 for r in res if not r["ok"])})
    registro.salvar()

    houve_falha = any(s["falhas"] for s in series_info)

    # 4) MPPS fim ------------------------------------------------------
    if mpps_uid:
        steps.mpps_concluir(em, aet, dest.pacs, mpps_uid,
                            [s for s in series_info if s["instancias"]],
                            status="DISCONTINUED" if houve_falha else "COMPLETED")

    # 5) Storage Commitment --------------------------------------------
    if eq.commitment:
        porta = porta_escuta or eq.porta_escuta or porta_escuta_padrao(aet)
        steps.commitment(em, aet, dest.pacs, ref_imgs, porta)
    else:
        em.emitir("commitment", PULADO, "equipamento não usa commitment")

    # 6) Impressão -----------------------------------------------------
    if eq.imprimir and dest.impressora is not None:
        steps.imprimir(em, aet, dest.impressora, todas[0] if todas else None)
    else:
        em.emitir("print", PULADO, "sem impressão")

    em.emitir("fim", OK if em.ok else FALHA,
              f"{len(ref_imgs)}/{len(todas)} imagem(ns) entregue(s)")
    return ResultadoExame(eq.nome, em.ok, str(paciente.get("nome", "")), estudo_uid,
                          len(ref_imgs), em.eventos)
