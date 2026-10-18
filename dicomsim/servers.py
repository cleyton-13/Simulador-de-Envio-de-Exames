"""Servidor virtual completo numa só porta: PACS + RIS(MWL) + MPPS + Commitment + Print.

Serve para testar o simulador de modalidade sem equipamento real — e para os
testes automáticos. Guarda tudo em memória (e as imagens numa pasta).

    srv = ServidorVirtual(aet="PACS_TESTE", porta=11112, pasta=tmp)
    srv.iniciar(); ...; srv.parar()
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

from pydicom.dataset import Dataset
from pydicom.uid import (ExplicitVRBigEndian, ExplicitVRLittleEndian,
                         ImplicitVRLittleEndian, generate_uid)
from pynetdicom import AE, evt
from pynetdicom.presentation import StoragePresentationContexts
from pynetdicom.sop_class import (
    BasicFilmBox, BasicFilmSession, BasicGrayscaleImageBox,
    BasicGrayscalePrintManagementMeta, ModalityPerformedProcedureStep,
    ModalityWorklistInformationFind, StorageCommitmentPushModel, Verification,
)

from .netutil import RETIRADAS, Alvo, porta_escuta_padrao

RAIZ = Path(__file__).resolve().parent.parent
from pydicom.uid import AllTransferSyntaxes
TS = list(AllTransferSyntaxes)   # aceita também JPEG, JPEG-LS, JPEG2000, RLE


def _casa(filtro, valor):
    """Filtro DICOM simplificado: vazio/* = tudo; *x* contém; x* começa; = igual."""
    if filtro in (None, "", "*"):
        return True
    f, v = str(filtro).strip().upper(), str(valor or "").upper()
    if f.startswith("*") and f.endswith("*"):
        return f.strip("*") in v
    if f.endswith("*"):
        return v.startswith(f[:-1])
    if f.startswith("*"):
        return v.endswith(f[1:])
    return v == f


def worklist_padrao():
    fp = RAIZ / "worklist.json"
    return json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else []


class ServidorVirtual:
    def __init__(self, aet="PACS_TESTE", porta=11112, pasta=None, worklist=None,
                 retorno=None, falhar_commitment=False, silencioso=True):
        self.aet, self.porta = aet, porta
        self.pasta = Path(pasta) if pasta else Path(tempfile.mkdtemp(prefix="dicomsim_"))
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.worklist = worklist if worklist is not None else worklista_ou_padrao()
        # AET do solicitante -> (ip, porta) onde ele escuta o N-EVENT-REPORT
        self.retorno = dict(retorno or {})
        self.falhar_commitment = falhar_commitment
        self.silencioso = silencioso
        self.instancias: dict[str, str] = {}   # sop_instance -> sop_class
        self.mpps: dict[str, dict] = {}
        self.filmes: list[dict] = []
        self.log: list[str] = []
        self._srv = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ util
    def _log(self, msg):
        self.log.append(msg)
        if not self.silencioso:
            print(f"[{self.aet}] {msg}", flush=True)

    def registrar_retorno(self, aet, ip, porta):
        self.retorno[aet] = (ip, porta)

    @property
    def alvo(self):
        return Alvo(self.aet, "127.0.0.1", self.porta)

    # ------------------------------------------------------------ handlers
    def _echo(self, event):
        return 0x0000

    def _store(self, event):
        ds = event.dataset
        ds.file_meta = event.file_meta
        sop = str(ds.SOPInstanceUID)
        try:
            ds.save_as(self.pasta / f"{sop}.dcm", enforce_file_format=True)
        except Exception as e:
            self._log(f"C-STORE erro ao gravar: {e}")
            return 0xA700
        with self._lock:
            self.instancias[sop] = str(ds.SOPClassUID)
        self._log(f"C-STORE {event.assoc.requestor.ae_title} {ds.get('Modality','')} {sop[-12:]}")
        return 0x0000

    def _find_mwl(self, event):
        req = event.identifier
        # filtros no padrão (dentro da sequência) ou, por compatibilidade, no topo
        seq = (getattr(req, "ScheduledProcedureStepSequence", None) or [Dataset()])[0]

        def filtro(nome):
            return getattr(seq, nome, "") or getattr(req, nome, "")

        n = 0
        for it in self.worklist:
            if not _casa(filtro("Modality"), it.get("Modality")):
                continue
            if not _casa(getattr(req, "PatientName", ""), it.get("PatientName")):
                continue
            est = filtro("ScheduledStationAETitle")
            if est and not _casa(est, it.get("ScheduledStationAETitle")):
                continue
            dt = filtro("ScheduledProcedureStepStartDate")
            if dt and not _casa(dt, it.get("ScheduledProcedureStepStartDate")):
                continue
            rsp = Dataset()
            sps = Dataset()
            for k, v in it.items():
                if k.startswith("ScheduledProcedureStep") or k in ("Modality", "ScheduledStationAETitle"):
                    setattr(sps, k, v)
                else:
                    setattr(rsp, k, v)
            rsp.ScheduledProcedureStepSequence = [sps]
            n += 1
            yield 0xFF00, rsp
        self._log(f"MWL {event.assoc.requestor.ae_title}: {n} item(ns)")
        yield 0x0000, None

    def _n_create(self, event):
        cls = str(event.request.AffectedSOPClassUID)
        uid = str(event.request.AffectedSOPInstanceUID or generate_uid())
        attr = event.attribute_list
        if cls == str(ModalityPerformedProcedureStep):
            with self._lock:
                self.mpps[uid] = {"status": attr.get("PerformedProcedureStepStatus", ""),
                                  "paciente": str(attr.get("PatientName", "")),
                                  "series": [], "criado_por": event.assoc.requestor.ae_title}
            self._log(f"MPPS N-CREATE {uid[-12:]} {self.mpps[uid]['status']}")
            rsp = Dataset()
            return 0x0000, rsp
        if cls == str(BasicFilmBox):
            rsp = Dataset()
            r = Dataset()
            r.ReferencedSOPClassUID = BasicGrayscaleImageBox
            r.ReferencedSOPInstanceUID = generate_uid()
            rsp.ReferencedImageBoxSequence = [r]
            return 0x0000, rsp
        return 0x0000, Dataset()

    def _n_set(self, event):
        cls = str(event.request.RequestedSOPClassUID)
        uid = str(event.request.RequestedSOPInstanceUID)
        attr = event.attribute_list
        if cls == str(ModalityPerformedProcedureStep):
            with self._lock:
                m = self.mpps.get(uid)
                if m is None:
                    return 0x0112, None   # No Such SOP Instance
                if m["status"] != "IN PROGRESS":
                    return 0xC300, None   # já finalizado: não pode mudar
                m["status"] = attr.get("PerformedProcedureStepStatus", m["status"])
                m["series"] = [str(s.SeriesInstanceUID)
                               for s in attr.get("PerformedSeriesSequence", [])]
            self._log(f"MPPS N-SET {uid[-12:]} → {m['status']}")
            return 0x0000, Dataset()
        if cls == str(BasicGrayscaleImageBox):
            self._pix = attr
            return 0x0000, Dataset()
        return 0x0000, Dataset()

    def _n_action(self, event):
        cls = str(event.request.RequestedSOPClassUID)
        if cls == str(StorageCommitmentPushModel):
            ds = event.action_information
            refs = [(str(r.ReferencedSOPClassUID), str(r.ReferencedSOPInstanceUID))
                    for r in ds.ReferencedSOPSequence]
            quem = event.assoc.requestor.ae_title
            end = self.retorno.get(quem)
            if end is None:
                end = (event.assoc.requestor.address, porta_escuta_padrao(quem))
            threading.Thread(target=self._commit_retorno,
                             args=(quem, end, str(ds.TransactionUID), refs),
                             daemon=True).start()
            self._log(f"COMMIT N-ACTION de {quem}: {len(refs)} ref(s)")
            return 0x0000, None
        if cls == str(BasicFilmBox):
            self.filmes.append({"quando": time.time(),
                                "de": event.assoc.requestor.ae_title})
            self._log(f"PRINT N-ACTION de {event.assoc.requestor.ae_title}")
            return 0x0000, None
        return 0x0000, None

    def _commit_retorno(self, quem, end, transacao, refs):
        time.sleep(0.2)
        ip, porta = end
        if not porta:
            self._log(f"COMMIT sem porta de retorno para {quem}")
            return
        ok_l, falha_l = [], []
        for cls, inst in refs:
            tem = inst in self.instancias and not self.falhar_commitment
            r = Dataset()
            r.ReferencedSOPClassUID = cls
            r.ReferencedSOPInstanceUID = inst
            (ok_l if tem else falha_l).append(r)
        rep = Dataset()
        rep.TransactionUID = transacao
        if ok_l:
            rep.ReferencedSOPSequence = ok_l
        if falha_l:
            for r in falha_l:
                r.FailureReason = 0x0110
            rep.FailedSOPSequence = falha_l
        tipo = 1 if not falha_l else 2
        ae = AE(ae_title=self.aet)
        ae.add_requested_context(StorageCommitmentPushModel)
        a = ae.associate(ip, porta, ae_title=quem)
        if not a.is_established:
            self._log(f"COMMIT retorno recusado por {quem}@{ip}:{porta}")
            return
        a.send_n_event_report(rep, tipo, StorageCommitmentPushModel,
                              "1.2.840.10008.1.20.1.1")
        a.release()

    # ------------------------------------------------------------ ciclo de vida
    def iniciar(self):
        ae = AE(ae_title=self.aet)
        ae.maximum_pdu_size = 0
        ae.add_supported_context(Verification, TS)
        # 128 é o limite de contextos: reservo os 9 não-storage
        for ctx in StoragePresentationContexts[:110]:
            ae.add_supported_context(ctx.abstract_syntax, TS)
        for uid in RETIRADAS:
            ae.add_supported_context(uid, TS)
        for sop in (ModalityWorklistInformationFind, ModalityPerformedProcedureStep,
                    StorageCommitmentPushModel, BasicGrayscalePrintManagementMeta,
                    BasicFilmSession, BasicFilmBox, BasicGrayscaleImageBox):
            ae.add_supported_context(sop, TS)
        ae.require_called_aet = False
        handlers = [
            (evt.EVT_C_ECHO, self._echo),
            (evt.EVT_C_STORE, self._store),
            (evt.EVT_C_FIND, self._find_mwl),
            (evt.EVT_N_CREATE, self._n_create),
            (evt.EVT_N_SET, self._n_set),
            (evt.EVT_N_ACTION, self._n_action),
        ]
        self._srv = ae.start_server(("127.0.0.1", self.porta), block=False,
                                    evt_handlers=handlers)
        return self

    def parar(self):
        if self._srv:
            self._srv.shutdown()
            self._srv = None

    def __enter__(self):
        return self.iniciar()

    def __exit__(self, *a):
        self.parar()


def worklista_ou_padrao():
    return worklist_padrao()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Servidor virtual PACS+RIS+MPPS+Commitment+Print")
    ap.add_argument("--aet", default="PACS_TESTE")
    ap.add_argument("--port", type=int, default=11112)
    ap.add_argument("--pasta", default=str(RAIZ / "received"))
    ap.add_argument("--retorno", action="append", default=[],
                    help="AET=porta onde o solicitante escuta o commitment (repetível)")
    a = ap.parse_args()
    ret = {}
    for r in a.retorno:
        k, p = r.split("=")
        ret[k] = ("127.0.0.1", int(p))
    srv = ServidorVirtual(a.aet, a.port, a.pasta, retorno=ret, silencioso=False).iniciar()
    print(f"[{a.aet}] servidor virtual na porta {a.port} — Ctrl+C para parar", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.parar()


if __name__ == "__main__":
    main()
