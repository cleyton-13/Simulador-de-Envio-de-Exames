"""Bateria completa local em 1 processo + relatorio de exemplo.

Sobe PACS (11112) + RIS/MWL (11114) + Impressora (11115) em background,
roda echo/store/find/mwl/print como a modalidade CT_SALA1 e grava
relatorios/relatorio_CT_SALA1_<data>.md no mesmo formato da tela.

Uso: python 09_bateria_relatorio.py
"""
import sys
import json
import struct
import time
from datetime import datetime
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from pynetdicom import AE, evt
from pynetdicom.presentation import StoragePresentationContexts, VerificationPresentationContexts
from pynetdicom.sop_class import (
    BasicFilmBox,
    BasicFilmSession,
    BasicGrayscaleImageBox,
    BasicGrayscalePrintManagementMeta,
    ModalityWorklistInformationFind,
    Printer,
    StudyRootQueryRetrieveInformationModelFind,
    Verification,
)

BASE = Path(__file__).parent
RECEIVED = BASE / "received"
PRINTED = BASE / "printed"
REL_DIR = BASE / "relatorios"
for d in (RECEIVED, PRINTED, REL_DIR):
    d.mkdir(exist_ok=True)

MOD = {"nome": "CT-SALA-1", "aet": "CT_SALA1", "setor": "Imagem - Sala 1",
       "ip_equip": "127.0.0.1 (simuladores locais)"}
PACS = ("PACS_TESTE", "127.0.0.1", 11112)
RIS = ("RIS_TESTE", "127.0.0.1", 11114)
PRN = ("PRINTER_TESTE", "127.0.0.1", 11115)


# ---------- SCPs ----------
def h_echo(event):
    return 0x0000


def h_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    ds.save_as(str(RECEIVED / f"{ds.SOPInstanceUID}.dcm"), write_like_original=False)
    return 0x0000


def h_find(event):
    for f in RECEIVED.glob("*.dcm"):
        try:
            s = dcmread(str(f), stop_before_pixels=True)
        except Exception:
            continue
        r = Dataset()
        r.QueryRetrieveLevel = "STUDY"
        for k in ("PatientName", "PatientID", "StudyInstanceUID", "SeriesInstanceUID",
                  "SOPInstanceUID", "StudyDate", "Modality"):
            setattr(r, k, s.get(k, ""))
        yield (0xFF00, r)
    yield (0x0000, None)


def h_mwl(event):
    for it in json.loads((BASE / "worklist.json").read_text(encoding="utf-8")):
        r = Dataset()
        r.PatientName = it["PatientName"]
        r.PatientID = it["PatientID"]
        r.AccessionNumber = it["AccessionNumber"]
        r.StudyInstanceUID = it["StudyInstanceUID"]
        r.Modality = it["Modality"]
        r.RequestedProcedureDescription = it.get("RequestedProcedureDescription", "")
        r.ScheduledProcedureStepStartDate = it.get("ScheduledProcedureStepStartDate", "")
        r.ScheduledProcedureStepID = it.get("ScheduledProcedureStepID", "")
        yield (0xFF00, r)
    yield (0x0000, None)


def h_ncreate(event):
    sop = event.request.AffectedSOPClassUID
    uid = str(getattr(event.request, "AffectedSOPInstanceUID", None) or generate_uid())
    rsp = Dataset()
    rsp.AffectedSOPClassUID = sop
    rsp.AffectedSOPInstanceUID = uid
    if sop == BasicFilmBox:
        iu = generate_uid()
        item = Dataset()
        item.ReferencedSOPClassUID = BasicGrayscaleImageBox
        item.ReferencedSOPInstanceUID = iu
        rsp.ReferencedFilmBoxSequence = [item]
    return 0x0000, rsp


def h_nset(event):
    return 0x0000, event.attribute_list


def h_naction(event):
    with open(PRINTED / "print_jobs.log", "a", encoding="utf-8") as f:
        f.write(f"[BATERIA] PRINT OK {datetime.now():%Y-%m-%d %H:%M:%S} "
                f"FilmBox={event.request.RequestedSOPInstanceUID}\n")
    return 0x0000, None


def h_nget(event):
    r = Dataset()
    r.PrinterStatus = "NORMAL"
    r.PrinterName = "PRINTER_TESTE_SIMULADA"
    return 0x0000, r


def h_ndelete(event):
    return 0x0000


ae_pacs = AE(ae_title=PACS[0])
ae_pacs.supported_contexts = VerificationPresentationContexts + StoragePresentationContexts
ae_pacs.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
s1 = ae_pacs.start_server(("", PACS[2]), block=False,
                          evt_handlers=[(evt.EVT_C_ECHO, h_echo), (evt.EVT_C_STORE, h_store),
                                        (evt.EVT_C_FIND, h_find)])
ae_ris = AE(ae_title=RIS[0])
ae_ris.add_supported_context(ModalityWorklistInformationFind)
s2 = ae_ris.start_server(("", RIS[2]), block=False,
                         evt_handlers=[(evt.EVT_C_FIND, h_mwl)])
ae_prn = AE(ae_title=PRN[0])
for c in (BasicGrayscalePrintManagementMeta, BasicFilmSession, BasicFilmBox,
          BasicGrayscaleImageBox, Printer):
    ae_prn.add_supported_context(c)
s3 = ae_prn.start_server(("", PRN[2]), block=False,
                         evt_handlers=[(evt.EVT_N_CREATE, h_ncreate), (evt.EVT_N_SET, h_nset),
                                       (evt.EVT_N_ACTION, h_naction), (evt.EVT_N_GET, h_nget),
                                       (evt.EVT_N_DELETE, h_ndelete)])
time.sleep(1.0)
print(f"[SCP] PACS:{PACS[2]} RIS:{RIS[2]} PRN:{PRN[2]} no ar")


# ---------- SCU ----------
def new_ae():
    ae = AE(ae_title=MOD["aet"])
    ae.add_requested_context(Verification)
    for c in StoragePresentationContexts:
        ae.add_requested_context(c.abstract_syntax, c.transfer_syntax)
    for c in (StudyRootQueryRetrieveInformationModelFind, ModalityWorklistInformationFind,
              BasicGrayscalePrintManagementMeta, BasicFilmSession, BasicFilmBox,
              BasicGrayscaleImageBox, Printer):
        ae.add_requested_context(c)
    return ae


ae = new_ae()
res = []


def emit(n, total, etapa="", item="", status=""):
    print("@P " + json.dumps({"n": n, "total": total, "etapa": etapa,
                             "item": item, "status": status}), flush=True)


def rec(titulo, ok, dt, detalhe):
    res.append((titulo, ok, dt, detalhe))
    print(f"[{'PASS' if ok else 'FAIL'}] {titulo} ({dt:.1f}s) {detalhe}")


t0 = time.time()
a = ae.associate(PACS[1], PACS[2], ae_title=PACS[0])
st = a.send_c_echo()
a.release()
emit(1, 5, "C-ECHO", MOD["aet"], "ok" if st.Status == 0x0000 else "falha")
rec("C-ECHO", st.Status == 0x0000, time.time() - t0, f"status={hex(st.Status)}")

t0 = time.time()
ds = dcmread(str(BASE / "teste_CT.dcm"))
a = ae.associate(PACS[1], PACS[2], ae_title=PACS[0])
st = a.send_c_store(ds)
a.release()
emit(2, 5, "C-STORE", MOD["aet"], "ok" if st.Status == 0x0000 else "falha")
rec("C-STORE", st.Status == 0x0000, time.time() - t0, f"status={hex(st.Status)} SOP={ds.SOPInstanceUID}")

t0 = time.time()
q = Dataset()
q.QueryRetrieveLevel = "STUDY"
q.PatientName = "*"
for k in ("PatientID", "StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID",
          "StudyDate", "Modality"):
    setattr(q, k, "")
a = ae.associate(PACS[1], PACS[2], ae_title=PACS[0])
n = sum(1 for s, _ in a.send_c_find(q, query_model=StudyRootQueryRetrieveInformationModelFind)
        if s.Status in (0xFF00, 0xFF01))
a.release()
emit(3, 5, "C-FIND", MOD["aet"], "ok")
rec("C-FIND", n >= 1, time.time() - t0, f"{n} estudo(s)")

t0 = time.time()
m = Dataset()
for k in ("PatientName", "PatientID", "AccessionNumber", "StudyInstanceUID",
          "RequestedProcedureID", "RequestedProcedureDescription", "Modality",
          "ScheduledStationAETitle", "ScheduledProcedureStepStartDate",
          "ScheduledProcedureStepID"):
    setattr(m, k, "")
a = ae.associate(RIS[1], RIS[2], ae_title=RIS[0])
n = sum(1 for s, _ in a.send_c_find(m, query_model=ModalityWorklistInformationFind)
        if s.Status in (0xFF00, 0xFF01))
a.release()
emit(4, 5, "MWL", MOD["aet"], "ok")
rec("MWL", n >= 3, time.time() - t0, f"{n} agendamento(s)")

t0 = time.time()
okp, det = False, ""
try:
    a = ae.associate(PRN[1], PRN[2], ae_title=PRN[0])
    se = Dataset()
    se.NumberOfCopies = "1"
    se.PrintPriority = "HIGH"
    se.MediumType = "PAPER"
    se.FilmDestination = "MAGAZINE"
    suid = generate_uid()
    st, _ = a.send_n_create(se, BasicFilmSession, suid,
                            meta_uid=BasicGrayscalePrintManagementMeta)
    buid = generate_uid()
    bx = Dataset()
    bx.ImageDisplayFormat = "STANDARD\\1,1"
    bx.FilmOrientation = "PORTRAIT"
    bx.FilmSizeID = "8INX10IN"
    bx.MagnificationType = "REPLICATE"
    rf = Dataset()
    rf.ReferencedSOPClassUID = BasicFilmSession
    rf.ReferencedSOPInstanceUID = suid
    bx.ReferencedFilmSessionSequence = [rf]
    st, ba = a.send_n_create(bx, BasicFilmBox, buid,
                             meta_uid=BasicGrayscalePrintManagementMeta)
    iuid = generate_uid()
    for kw in ("ReferencedFilmBoxSequence", "ReferencedImageSequence",
               "ReferencedBasicGrayscaleImageBoxSequence"):
        sq = getattr(ba, kw, None) if ba is not None else None
        if sq:
            iuid = sq[0].ReferencedSOPInstanceUID
            break
    tot = 64 * 64
    im = Dataset()
    im.ImageBoxPosition = 1
    im.Rows = 64
    im.Columns = 64
    im.BitsAllocated = 8
    im.BitsStored = 8
    im.HighBit = 7
    im.PixelRepresentation = 0
    im.SamplesPerPixel = 1
    im.PhotometricInterpretation = "MONOCHROME2"
    im.PixelData = struct.pack(f"<{tot}B", *[(i % 256) for i in range(tot)])
    st, _ = a.send_n_set(im, BasicGrayscaleImageBox, iuid,
                         meta_uid=BasicGrayscalePrintManagementMeta)
    st, _ = a.send_n_action(None, 1, BasicFilmBox, buid,
                            meta_uid=BasicGrayscalePrintManagementMeta)
    okp = getattr(st, "Status", None) == 0x0000
    det = f"status={hex(getattr(st, 'Status', 0) or 0)}"
    a.release()
except Exception as e:
    det = f"ERRO: {e}"
rec("PRINT", okp, time.time() - t0, det)
emit(5, 5, "PRINT", MOD["aet"], "ok" if okp else "falha")

npass = sum(1 for _, ok, _, _ in res if ok)
agora = datetime.now()
linhas = [f"# Relatório DICOM — {agora:%Y-%m-%d %H:%M:%S}",
          f"Modalidade: {MOD['nome']} (CallingAET={MOD['aet']})",
          f"Setor/Leito: {MOD['setor']} | IP equipamento: {MOD['ip_equip']}",
          f"PACS: {PACS[0]}@{PACS[1]}:{PACS[2]} | RIS: {RIS[0]}@{RIS[1]}:{RIS[2]} | "
          f"Printer: {PRN[0]}@{PRN[1]}:{PRN[2]}",
          f"**Resumo: {'🟢' if npass == 5 else '🔴'} {npass}/5 PASS**", "",
          "| Teste | Status | Tempo |", "|---|---|---|"]
for t, ok, dt, _ in res:
    linhas.append(f"| {t} | {'🟢 PASS' if ok else '🔴 FAIL'} | {dt:.1f}s |")
linhas.append("")
for t, ok, dt, d in res:
    linhas += [f"## {'🟢' if ok else '🔴'} {t}: {'PASS' if ok else 'FAIL'} ({dt:.1f}s)", d, ""]
txt = "\n".join(linhas)
fname = f"relatorio_{MOD['aet']}_{agora:%Y%m%d_%H%M%S}.md"
(REL_DIR / fname).write_text(txt, encoding="utf-8")
print(f"[RELATORIO] {REL_DIR / fname} ({npass}/5 PASS)")

s1.shutdown()
s2.shutdown()
s3.shutdown()
assert npass == 5, f"Bateria com falha: {npass}/5"
print("BATERIA COMPLETA: 5/5 PASS")
