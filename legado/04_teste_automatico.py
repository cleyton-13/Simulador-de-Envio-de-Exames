"""Teste automatico em processo unico (evita 2 terminais).

Sobe o SCP em background (block=False), roda C-ECHO + C-STORE + C-FIND,
desliga. Ideal para validar que esta tudo OK.
Uso: python 04_teste_automatico.py
"""
import time
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset
from pynetdicom import AE, evt
from pynetdicom.presentation import (
    StoragePresentationContexts,
    VerificationPresentationContexts,
)
from pynetdicom.sop_class import (
    StudyRootQueryRetrieveInformationModelFind,
    Verification,
)

BASE = Path(__file__).parent
RECEIVED = BASE / "received"
RECEIVED.mkdir(exist_ok=True)
AET = "PACS_TESTE"
PORT = 11112


def handle_echo(event):
    return 0x0000


def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    ds.save_as(str(RECEIVED / f"{ds.SOPInstanceUID}.dcm"), write_like_original=False)
    print(f"[SCP C-STORE] recebido {ds.SOPInstanceUID}")
    return 0x0000


def handle_find(event):
    for f in RECEIVED.glob("*.dcm"):
        try:
            s = dcmread(str(f), stop_before_pixels=True)
        except Exception:
            continue
        rsp = Dataset()
        rsp.QueryRetrieveLevel = "STUDY"
        rsp.PatientName = s.get("PatientName", "")
        rsp.PatientID = s.get("PatientID", "")
        rsp.StudyInstanceUID = s.get("StudyInstanceUID", "")
        rsp.SeriesInstanceUID = s.get("SeriesInstanceUID", "")
        rsp.SOPInstanceUID = s.get("SOPInstanceUID", "")
        rsp.StudyDate = s.get("StudyDate", "")
        rsp.Modality = s.get("Modality", "")
        yield (0xFF00, rsp)
    yield (0x0000, None)


# --- sobe SCP ---
ae_scp = AE(ae_title=AET)
ae_scp.supported_contexts = (
    VerificationPresentationContexts + StoragePresentationContexts
)
ae_scp.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
scp = ae_scp.start_server(
    ("", PORT),
    block=False,
    evt_handlers=[
        (evt.EVT_C_ECHO, handle_echo),
        (evt.EVT_C_STORE, handle_store),
        (evt.EVT_C_FIND, handle_find),
    ],
)
time.sleep(1.0)
print(f"[SCP] ouvindo {AET}:{PORT}")

# --- SCU ---
ae = AE(ae_title="SIMULADOR")
ae.add_requested_context(Verification)
for ctx in StoragePresentationContexts:
    ae.add_requested_context(ctx.abstract_syntax, ctx.transfer_syntax)
ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)

ok = True

assoc = ae.associate("127.0.0.1", PORT, ae_title=AET)
assert assoc.is_established, "falha associate echo"
st = assoc.send_c_echo()
print(f"[TEST C-ECHO] status={hex(st.Status)}")
assert st.Status == 0x0000, "C-ECHO falhou"
assoc.release()

ds = dcmread(str(BASE / "teste_CT.dcm"))
assoc = ae.associate("127.0.0.1", PORT, ae_title=AET)
assert assoc.is_established, "falha associate store"
st = assoc.send_c_store(ds)
print(f"[TEST C-STORE] status={hex(st.Status)}")
assert st.Status == 0x0000, "C-STORE falhou"
assoc.release()

q = Dataset()
q.QueryRetrieveLevel = "STUDY"
q.PatientName = "*"
q.PatientID = ""
q.StudyInstanceUID = ""
q.SeriesInstanceUID = ""
q.SOPInstanceUID = ""
q.StudyDate = ""
q.Modality = ""
assoc = ae.associate("127.0.0.1", PORT, ae_title=AET)
assert assoc.is_established, "falha associate find"
n = 0
for status, ident in assoc.send_c_find(
    q, query_model=StudyRootQueryRetrieveInformationModelFind
):
    if status.Status in (0xFF00, 0xFF01):
        n += 1
        print(f"[TEST C-FIND] achou {ident.PatientName} {ident.StudyInstanceUID}")
assoc.release()
print(f"[TEST C-FIND] total={n}")
assert n >= 1, "C-FIND nao achou nada"

scp.shutdown()
print("TODOS OS TESTES PASSARAM: C-ECHO + C-STORE + C-FIND OK")
