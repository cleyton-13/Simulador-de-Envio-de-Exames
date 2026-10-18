"""Um passo DICOM por função. Todos devolvem dados simples e emitem eventos."""
from __future__ import annotations

import threading
import functools
from datetime import datetime

from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    BasicFilmBox, BasicFilmSession, BasicGrayscaleImageBox,
    BasicGrayscalePrintManagementMeta, ModalityPerformedProcedureStep,
    ModalityWorklistInformationFind, StorageCommitmentPushModel,
)

from .events import AVISO, FALHA, OK, PULADO, Emissor
from .netutil import Alvo, associar, status_hex, status_ok

COMMITMENT_INSTANCIA = "1.2.840.10008.1.20.1.1"


def protegido(etapa, padrao=None):
    """Nenhum passo derruba o exame: exceção vira evento.

    "No presentation context ... accepted" = o destino aceitou a conexão mas NÃO
    suporta aquele serviço (ex.: PACS sem MPPS) → aviso, não falha.
    """
    def deco(fn):
        @functools.wraps(fn)
        def interno(em, *a, **k):
            try:
                return fn(em, *a, **k)
            except Exception as e:
                msg = str(e)
                if "presentation context" in msg.lower():
                    em.emitir(etapa, AVISO, "o destino não suporta este serviço "
                              "(contexto de apresentação recusado) — passo ignorado")
                else:
                    em.emitir(etapa, FALHA, f"{type(e).__name__}: {msg[:160]}")
                return padrao
        return interno
    return deco


def _agora():
    n = datetime.now()
    return n.strftime("%Y%m%d"), n.strftime("%H%M%S")


# ------------------------------------------------------------------ MWL
@protegido("worklist", None)
def consultar_worklist(em: Emissor, aet, alvo: Alvo, modalidade="", data="",
                       paciente="", estacao=""):
    """C-FIND MWL. Devolve lista de itens (dict) ou None se o RIS não respondeu."""
    with associar(aet, alvo, [ModalityWorklistInformationFind]) as assoc:
        if assoc is None:
            em.emitir("worklist", FALHA, f"associação recusada por {alvo}")
            return None
        # Formato padrão (PS3.4 K.6): Modality, estação e data ficam DENTRO da
        # ScheduledProcedureStepSequence. RIS reais ignoram esses campos no topo.
        q = Dataset()
        for k in ("PatientName", "PatientID", "PatientBirthDate", "PatientSex",
                  "AccessionNumber", "StudyInstanceUID", "RequestedProcedureID",
                  "RequestedProcedureDescription", "ReferringPhysicianName"):
            setattr(q, k, "")
        q.PatientName = paciente or ""
        sps = Dataset()
        sps.Modality = modalidade or ""
        sps.ScheduledStationAETitle = estacao or ""
        sps.ScheduledProcedureStepStartDate = data or ""
        sps.ScheduledProcedureStepStartTime = ""
        sps.ScheduledProcedureStepID = ""
        sps.ScheduledProcedureStepDescription = ""
        q.ScheduledProcedureStepSequence = [sps]
        itens = []
        for st, it in assoc.send_c_find(q, query_model=ModalityWorklistInformationFind):
            if getattr(st, "Status", None) in (0xFF00, 0xFF01) and it is not None:
                r = (it.get("ScheduledProcedureStepSequence") or [Dataset()])[0]
                itens.append({
                    "nome": str(it.get("PatientName", "")),
                    "id": str(it.get("PatientID", "")),
                    "nascimento": str(it.get("PatientBirthDate", "")),
                    "sexo": str(it.get("PatientSex", "")),
                    "acesso": str(it.get("AccessionNumber", "")),
                    "estudo_uid": str(it.get("StudyInstanceUID", "")),
                    "modalidade": str(r.get("Modality", it.get("Modality", modalidade))),
                    "procedimento": str(it.get("RequestedProcedureDescription", "")
                                        or r.get("ScheduledProcedureStepDescription", "")),
                    "proc_id": str(it.get("RequestedProcedureID", "")),
                    "estacao": str(r.get("ScheduledStationAETitle", "")),
                    "data": str(r.get("ScheduledProcedureStepStartDate", "")),
                    "passo": str(r.get("ScheduledProcedureStepID", "")),
                })
        dica = ""
        if not itens:
            dica = (f" — a maioria dos RIS só devolve exames agendados para o AE Title de "
                    f"quem pergunta; esta consulta usou '{aet}' como origem")
        em.emitir("worklist", OK, f"{len(itens)} exame(s) em {alvo}{dica}", total=len(itens))
        return itens


# ------------------------------------------------------------------ MPPS
@protegido("mpps-inicio", None)
def mpps_criar(em: Emissor, aet, alvo: Alvo, item: dict, modalidade, estacao=""):
    """N-CREATE do MPPS (exame iniciado). Devolve o UID do MPPS ou None."""
    uid = generate_uid()
    d, h = _agora()
    ds = Dataset()
    ds.PatientName = item.get("nome", "")
    ds.PatientID = item.get("id", "")
    ds.PatientBirthDate = item.get("nascimento", "")
    ds.PatientSex = item.get("sexo", "")
    ds.PerformedStationAETitle = aet
    ds.PerformedStationName = estacao or aet
    ds.PerformedLocation = ""
    ds.PerformedProcedureStepStartDate = d
    ds.PerformedProcedureStepStartTime = h
    ds.PerformedProcedureStepEndDate = ""
    ds.PerformedProcedureStepEndTime = ""
    ds.PerformedProcedureStepStatus = "IN PROGRESS"
    ds.PerformedProcedureStepID = item.get("passo") or uid[-8:]
    ds.PerformedProcedureStepDescription = item.get("procedimento", "")
    ds.PerformedProcedureTypeDescription = ""
    ds.Modality = modalidade
    ds.StudyID = item.get("acesso", "") or "1"
    sch = Dataset()
    sch.StudyInstanceUID = item.get("estudo_uid", "")
    sch.AccessionNumber = item.get("acesso", "")
    sch.RequestedProcedureID = item.get("proc_id", "")
    sch.RequestedProcedureDescription = item.get("procedimento", "")
    sch.ScheduledProcedureStepID = item.get("passo", "")
    sch.ScheduledProcedureStepDescription = item.get("procedimento", "")
    ds.ScheduledStepAttributesSequence = [sch]
    ds.PerformedSeriesSequence = []
    with associar(aet, alvo, [ModalityPerformedProcedureStep]) as assoc:
        if assoc is None:
            em.emitir("mpps-inicio", FALHA, f"associação recusada por {alvo}")
            return None
        st, _ = assoc.send_n_create(ds, ModalityPerformedProcedureStep, uid)
        if status_ok(st):
            em.emitir("mpps-inicio", OK, f"IN PROGRESS {uid[-12:]}", mpps_uid=uid)
            return uid
        em.emitir("mpps-inicio", FALHA, f"N-CREATE {status_hex(st)}")
        return None


@protegido("mpps-fim", False)
def mpps_concluir(em: Emissor, aet, alvo: Alvo, mpps_uid, series: list[dict],
                  status="COMPLETED"):
    """N-SET do MPPS. `series` = [{uid, descricao, instancias:[(sop_class, sop_inst)]}]."""
    d, h = _agora()
    ds = Dataset()
    ds.PerformedProcedureStepStatus = status
    ds.PerformedProcedureStepEndDate = d
    ds.PerformedProcedureStepEndTime = h
    seq = []
    for s in series:
        it = Dataset()
        it.SeriesInstanceUID = s["uid"]
        it.SeriesDescription = s.get("descricao", "")
        it.PerformingPhysicianName = ""
        it.OperatorsName = ""
        it.ProtocolName = s.get("descricao", "") or "PROTOCOLO"
        it.RetrieveAETitle = ""
        refs = []
        for cls, inst in s["instancias"]:
            r = Dataset()
            r.ReferencedSOPClassUID = cls
            r.ReferencedSOPInstanceUID = inst
            refs.append(r)
        it.ReferencedImageSequence = refs
        it.ReferencedNonImageCompositeSOPInstanceSequence = []
        seq.append(it)
    ds.PerformedSeriesSequence = seq
    with associar(aet, alvo, [ModalityPerformedProcedureStep]) as assoc:
        if assoc is None:
            em.emitir("mpps-fim", FALHA, f"associação recusada por {alvo}")
            return False
        st, _ = assoc.send_n_set(ds, ModalityPerformedProcedureStep, mpps_uid)
        ok = status_ok(st)
        em.emitir("mpps-fim", OK if ok else FALHA,
                  f"{status} · {sum(len(s['instancias']) for s in series)} imagem(ns)"
                  if ok else f"N-SET {status_hex(st)}")
        return ok


# ------------------------------------------------------------------ STORE
def _classe_ts(ds):
    cls = getattr(ds, "SOPClassUID", None) or getattr(getattr(ds, "file_meta", None),
                                                      "MediaStorageSOPClassUID", None)
    ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
    return (str(cls) if cls else None), (str(ts) if ts else None)


def armazenar(em: Emissor, aet, alvo: Alvo, datasets: list, anomalas=False):
    """C-STORE de uma lista de Dataset numa única associação.

    Oferece cada (SOP Class, Transfer Syntax) real da imagem — imagens comprimidas
    precisam do seu contexto. Com `anomalas=True` a recusa do PACS é só um aviso
    (é o comportamento esperado de um teste negativo).
    Devolve lista de dicts {classe, instancia, ok, status}.
    """
    pares = sorted({(c, t) for c, t in map(_classe_ts, datasets) if c})
    res = []
    contextos = [(c, [t]) if t else c for c, t in pares]
    with associar(aet, alvo, contextos) as assoc:
        if assoc is None:
            em.emitir("store", AVISO if anomalas else FALHA,
                      f"associação recusada por {alvo} (AET/porta/SOP?)")
            return [{"classe": _classe_ts(d)[0] or "?", "instancia": str(getattr(d, "SOPInstanceUID", "?")),
                     "ok": False, "status": "recusada"} for d in datasets]
        for i, ds in enumerate(datasets, 1):
            cls = _classe_ts(ds)[0]
            if cls is None:
                res.append({"classe": "?", "instancia": "?", "ok": False,
                            "status": "sem SOP Class"})
                em.emitir("store", AVISO, f"imagem {i}/{len(datasets)} sem SOP Class — não enviada")
                continue
            try:
                st = assoc.send_c_store(ds)
                motivo = status_hex(st)
                ok = status_ok(st, (0x0000, 0xB000, 0xB006, 0xB007))
            except Exception as e:  # contexto não aceito, objeto malformado etc.
                motivo, ok = f"{type(e).__name__}: {str(e)[:80]}", False
            res.append({"classe": cls, "instancia": str(getattr(ds, "SOPInstanceUID", "?")),
                        "ok": ok, "status": motivo})
            if ok:
                em.emitir("store", OK, f"imagem {i}/{len(datasets)} {motivo}")
            else:
                em.emitir("store", AVISO if anomalas else FALHA,
                          f"imagem {i}/{len(datasets)} {motivo}"
                          + (" (recusa esperada em caso anômalo)" if anomalas else ""))
    return res


# ------------------------------------------------------------------ COMMITMENT
@protegido("commitment", False)
def commitment(em: Emissor, aet, alvo: Alvo, refs: list[tuple[str, str]],
               porta_escuta: int, timeout=10.0):
    """Storage Commitment Push. Abre um listener local para receber o N-EVENT-REPORT."""
    if not refs:
        em.emitir("commitment", PULADO, "sem imagens")
        return True
    resp = {}
    pronto = threading.Event()

    def on_report(event):
        resp["info"] = event.event_information
        pronto.set()
        return 0x0000, None

    ae = AE(ae_title=aet)
    ae.add_supported_context(StorageCommitmentPushModel)
    srv = ae.start_server(("0.0.0.0", porta_escuta), block=False,
                          evt_handlers=[(evt.EVT_N_EVENT_REPORT, on_report)])
    try:
        ds = Dataset()
        ds.TransactionUID = generate_uid()
        seq = []
        for cls, inst in refs:
            r = Dataset()
            r.ReferencedSOPClassUID = cls
            r.ReferencedSOPInstanceUID = inst
            seq.append(r)
        ds.ReferencedSOPSequence = seq
        with associar(aet, alvo, [StorageCommitmentPushModel]) as assoc:
            if assoc is None:
                em.emitir("commitment", FALHA, f"associação recusada por {alvo}")
                return False
            st, _ = assoc.send_n_action(ds, 1, StorageCommitmentPushModel,
                                        COMMITMENT_INSTANCIA)
            if not status_ok(st):
                em.emitir("commitment", FALHA, f"N-ACTION {status_hex(st)}")
                return False
        if not pronto.wait(timeout):
            em.emitir("commitment", AVISO,
                      f"N-ACTION aceito, mas sem N-EVENT-REPORT em {timeout:.0f}s "
                      f"(o PACS precisa conectar na porta {porta_escuta})")
            return False
        info = resp["info"]
        falhas = len(getattr(info, "FailedSOPSequence", []) or [])
        okn = len(getattr(info, "ReferencedSOPSequence", []) or [])
        em.emitir("commitment", OK if falhas == 0 else FALHA,
                  f"{okn} confirmada(s), {falhas} falha(s)")
        return falhas == 0
    finally:
        srv.shutdown()


# ------------------------------------------------------------------ PRINT
def _pixels_8bit(ds, lado=256):
    try:
        import numpy as np
        a = ds.pixel_array
        if a.ndim > 2:
            a = a[0] if a.shape[-1] not in (3, 4) else a.mean(axis=-1)
        a = a.astype("float64")
        lo, hi = a.min(), a.max()
        a = (a - lo) / (hi - lo if hi > lo else 1) * 255
        h, w = a.shape
        ys = np.arange(lado) * h // lado
        xs = np.arange(lado) * w // lado
        return a[np.ix_(ys, xs)].astype("uint8").tobytes(), lado
    except Exception:
        return bytes((i % 256) for i in range(lado * lado)), lado


@protegido("print", False)
def imprimir(em: Emissor, aet, alvo: Alvo, ds_imagem=None):
    """Filme DICOM: FilmSession → FilmBox → ImageBox (pixels reais) → imprimir."""
    ctxs = [BasicGrayscalePrintManagementMeta, BasicFilmSession, BasicFilmBox,
            BasicGrayscaleImageBox]
    meta = BasicGrayscalePrintManagementMeta
    with associar(aet, alvo, ctxs, verification=False) as assoc:
        if assoc is None:
            em.emitir("print", FALHA, f"associação recusada por {alvo}")
            return False
        su = generate_uid()
        se = Dataset()
        se.NumberOfCopies = "1"
        se.PrintPriority = "MED"
        se.MediumType = "PAPER"
        se.FilmDestination = "MAGAZINE"
        st, _ = assoc.send_n_create(se, BasicFilmSession, su, meta_uid=meta)
        if not status_ok(st):
            em.emitir("print", FALHA, f"FilmSession {status_hex(st)}")
            return False
        bu = generate_uid()
        bx = Dataset()
        bx.ImageDisplayFormat = "STANDARD\\1,1"
        bx.FilmOrientation = "PORTRAIT"
        bx.FilmSizeID = "8INX10IN"
        bx.MagnificationType = "REPLICATE"
        rf = Dataset()
        rf.ReferencedSOPClassUID = BasicFilmSession
        rf.ReferencedSOPInstanceUID = su
        bx.ReferencedFilmSessionSequence = [rf]
        st, ba = assoc.send_n_create(bx, BasicFilmBox, bu, meta_uid=meta)
        if not status_ok(st):
            em.emitir("print", FALHA, f"FilmBox {status_hex(st)}")
            return False
        iu = generate_uid()
        if ba is not None:
            for kw in ("ReferencedImageBoxSequence", "ReferencedBasicGrayscaleImageBoxSequence",
                       "ReferencedImageSequence", "ReferencedFilmBoxSequence"):
                sq = getattr(ba, kw, None)
                if sq:
                    iu = sq[0].ReferencedSOPInstanceUID
                    break
        px, lado = _pixels_8bit(ds_imagem)
        im = Dataset()
        im.ImageBoxPosition = 1
        pix = Dataset()
        pix.Rows = pix.Columns = lado
        pix.BitsAllocated = 8
        pix.BitsStored = 8
        pix.HighBit = 7
        pix.PixelRepresentation = 0
        pix.SamplesPerPixel = 1
        pix.PhotometricInterpretation = "MONOCHROME2"
        pix.PixelData = px
        im.BasicGrayscaleImageSequence = [pix]
        st, _ = assoc.send_n_set(im, BasicGrayscaleImageBox, iu, meta_uid=meta)
        if not status_ok(st):
            em.emitir("print", FALHA, f"ImageBox {status_hex(st)}")
            return False
        st, _ = assoc.send_n_action(None, 1, BasicFilmBox, bu, meta_uid=meta)
        ok = status_ok(st)
        em.emitir("print", OK if ok else FALHA,
                  "filme enviado" if ok else f"N-ACTION {status_hex(st)}")
        return ok
