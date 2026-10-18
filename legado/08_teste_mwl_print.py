"""Teste automatico MWL + Print em processo unico.

Sobe MWL SCP (11114) + Print SCP (11115) em background,
roda C-FIND MWL + fluxo Print completo, desliga.

Uso: python 08_teste_mwl_print.py
"""
import json
import struct
import time
from pathlib import Path

from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    BasicFilmBox,
    BasicFilmSession,
    BasicGrayscaleImageBox,
    BasicGrayscalePrintManagementMeta,
    ModalityWorklistInformationFind,
    Printer,
)

BASE = Path(__file__).parent
PRINTED = BASE / "printed"
PRINTED.mkdir(exist_ok=True)


def load_worklist():
    return json.loads((BASE / "worklist.json").read_text(encoding="utf-8"))


def handle_mwl(event):
    req = event.identifier
    for it in load_worklist():
        f_mod = getattr(req, "Modality", "")
        if f_mod not in (None, "", "*") and str(f_mod) != it["Modality"]:
            continue
        rsp = Dataset()
        rsp.PatientName = it["PatientName"]
        rsp.PatientID = it["PatientID"]
        rsp.AccessionNumber = it["AccessionNumber"]
        rsp.StudyInstanceUID = it["StudyInstanceUID"]
        rsp.Modality = it["Modality"]
        rsp.RequestedProcedureDescription = it.get("RequestedProcedureDescription", "")
        rsp.ScheduledProcedureStepStartDate = it.get("ScheduledProcedureStepStartDate", "")
        rsp.ScheduledProcedureStepID = it.get("ScheduledProcedureStepID", "")
        yield (0xFF00, rsp)
    yield (0x0000, None)


def handle_n_create(event):
    sop = event.request.AffectedSOPClassUID
    wanted = getattr(event.request, "AffectedSOPInstanceUID", None)
    uid = str(wanted) if wanted else generate_uid()
    rsp = Dataset()
    rsp.AffectedSOPClassUID = sop
    rsp.AffectedSOPInstanceUID = uid
    if sop == BasicFilmBox:
        img_uid = generate_uid()
        seq_item = Dataset()
        seq_item.ReferencedSOPClassUID = BasicGrayscaleImageBox
        seq_item.ReferencedSOPInstanceUID = img_uid
        rsp.ReferencedFilmBoxSequence = [seq_item]
    return 0x0000, rsp


def handle_n_set(event):
    try:
        return 0x0000, event.attribute_list
    except Exception as e:
        print(f"[SCP N-SET ERRO] {e}")
        return 0x0110, None


def handle_n_action(event):
    try:
        uid = getattr(event.request, "RequestedSOPInstanceUID", "?")
        with open(PRINTED / "print_jobs.log", "a", encoding="utf-8") as f:
            f.write(f"[AUTO-TEST] PRINT OK FilmBox={uid}\n")
        print(f"[SCP N-ACTION] FilmBox={uid} -> 0x0000")
        return 0x0000, None
    except Exception as e:
        print(f"[SCP N-ACTION ERRO] {e}")
        return 0x0110, None


def handle_n_get(event):
    rsp = Dataset()
    rsp.PrinterStatus = "NORMAL"
    rsp.PrinterName = "PRINTER_TESTE_SIMULADA"
    return 0x0000, rsp


def handle_n_delete(event):
    return 0x0000


ae_mwl = AE(ae_title="RIS_TESTE")
ae_mwl.add_supported_context(ModalityWorklistInformationFind)
mwl_scp = ae_mwl.start_server(("", 11114), block=False,
                              evt_handlers=[(evt.EVT_C_FIND, handle_mwl)])

ae_prn = AE(ae_title="PRINTER_TESTE")
ae_prn.add_supported_context(BasicGrayscalePrintManagementMeta)
ae_prn.add_supported_context(BasicFilmSession)
ae_prn.add_supported_context(BasicFilmBox)
ae_prn.add_supported_context(BasicGrayscaleImageBox)
ae_prn.add_supported_context(Printer)
prn_scp = ae_prn.start_server(
    ("", 11115), block=False,
    evt_handlers=[
        (evt.EVT_N_CREATE, handle_n_create),
        (evt.EVT_N_SET, handle_n_set),
        (evt.EVT_N_ACTION, handle_n_action),
        (evt.EVT_N_GET, handle_n_get),
        (evt.EVT_N_DELETE, handle_n_delete),
    ],
)
time.sleep(1.0)
print("[SCP] MWL 11114 + PRINT 11115 no ar")

ae = AE(ae_title="SIMULADOR")
ae.add_requested_context(ModalityWorklistInformationFind)
ae.add_requested_context(BasicGrayscalePrintManagementMeta)
ae.add_requested_context(BasicFilmSession)
ae.add_requested_context(BasicFilmBox)
ae.add_requested_context(BasicGrayscaleImageBox)
ae.add_requested_context(Printer)

# --- MWL ---
q = Dataset()
q.PatientName = ""
q.PatientID = ""
q.AccessionNumber = ""
q.StudyInstanceUID = ""
q.RequestedProcedureID = ""
q.RequestedProcedureDescription = ""
q.Modality = ""
q.ScheduledStationAETitle = ""
q.ScheduledProcedureStepStartDate = ""
q.ScheduledProcedureStepID = ""
assoc = ae.associate("127.0.0.1", 11114, ae_title="RIS_TESTE")
assert assoc.is_established, "MWL associate falhou"
n = 0
for st, item in assoc.send_c_find(q, query_model=ModalityWorklistInformationFind):
    if st.Status in (0xFF00, 0xFF01):
        n += 1
        print(f"[TEST MWL] {item.PatientName} | {item.AccessionNumber} | {item.Modality}")
assoc.release()
assert n >= 3, f"MWL esperava 3, achou {n}"
print(f"[TEST MWL] OK total={n}")

# MWL com filtro
q2 = Dataset()
for k in ("PatientName", "PatientID", "AccessionNumber", "StudyInstanceUID",
          "RequestedProcedureID", "RequestedProcedureDescription",
          "ScheduledStationAETitle", "ScheduledProcedureStepStartDate",
          "ScheduledProcedureStepID"):
    setattr(q2, k, "")
q2.Modality = "CT"
assoc = ae.associate("127.0.0.1", 11114, ae_title="RIS_TESTE")
n2 = sum(1 for st, _ in assoc.send_c_find(q2, query_model=ModalityWorklistInformationFind)
         if st.Status in (0xFF00, 0xFF01))
assoc.release()
assert n2 >= 1, "MWL filtro CT falhou"
print(f"[TEST MWL filtro CT] OK total={n2}")

# --- PRINT ---
assoc = ae.associate("127.0.0.1", 11115, ae_title="PRINTER_TESTE")
assert assoc.is_established, "PRINT associate falhou"
sess_uid = generate_uid()
sess = Dataset()
sess.NumberOfCopies = "1"
sess.PrintPriority = "HIGH"
sess.MediumType = "PAPER"
sess.FilmDestination = "MAGAZINE"
st, _ = assoc.send_n_create(
    sess, BasicFilmSession, sess_uid, meta_uid=BasicGrayscalePrintManagementMeta)
assert st.Status == 0x0000, f"N-CREATE session falhou: {st}"
print(f"[TEST PRINT session] {sess_uid}")

box_uid = generate_uid()
box = Dataset()
box.ImageDisplayFormat = "STANDARD\\1,1"
box.FilmOrientation = "PORTRAIT"
box.FilmSizeID = "8INX10IN"
box.MagnificationType = "REPLICATE"
ref = Dataset()
ref.ReferencedSOPClassUID = BasicFilmSession
ref.ReferencedSOPInstanceUID = sess_uid
box.ReferencedFilmSessionSequence = [ref]
st, box_attr = assoc.send_n_create(
    box, BasicFilmBox, box_uid, meta_uid=BasicGrayscalePrintManagementMeta)
assert st.Status == 0x0000, f"N-CREATE filmbox falhou: {st}"
print(f"[TEST PRINT filmbox] {box_uid} attr={box_attr}")
img_uid = generate_uid()
if box_attr is not None:
    for seq_kw in ("ReferencedFilmBoxSequence", "ReferencedImageSequence",
                   "ReferencedBasicGrayscaleImageBoxSequence"):
        seq = getattr(box_attr, seq_kw, None)
        if seq:
            try:
                img_uid = seq[0].ReferencedSOPInstanceUID
                break
            except Exception:
                pass
print(f"[TEST PRINT imgbox] {img_uid}")

total = 64 * 64
img = Dataset()
img.ImageBoxPosition = 1
img.Rows = 64
img.Columns = 64
img.BitsAllocated = 8
img.BitsStored = 8
img.HighBit = 7
img.PixelRepresentation = 0
img.SamplesPerPixel = 1
img.PhotometricInterpretation = "MONOCHROME2"
img.PixelData = struct.pack(f"<{total}B", *[(i % 256) for i in range(total)])
st, _ = assoc.send_n_set(img, BasicGrayscaleImageBox, img_uid,
                           meta_uid=BasicGrayscalePrintManagementMeta)
assert st.Status == 0x0000, "N-SET imagebox falhou"
print("[TEST PRINT n-set] OK")

st, _ = assoc.send_n_action(None, 1, BasicFilmBox, box_uid,
                            meta_uid=BasicGrayscalePrintManagementMeta)
print(f"[TEST PRINT n-action] raw={st}")
assert getattr(st, "Status", None) == 0x0000, f"N-ACTION print falhou: {st}"
print("[TEST PRINT n-action] OK - impresso")

assoc.send_n_delete(BasicFilmBox, box_uid,
                    meta_uid=BasicGrayscalePrintManagementMeta)
assoc.send_n_delete(BasicFilmSession, sess_uid,
                    meta_uid=BasicGrayscalePrintManagementMeta)

assoc.release()

mwl_scp.shutdown()
prn_scp.shutdown()
print("TODOS OS TESTES MWL + PRINT PASSARAM")
