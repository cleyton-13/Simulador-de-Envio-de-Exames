"""MWL SCP — simula RIS / Worklist Server.

Responde C-FIND com SOP Modality Worklist Information Find
UID 1.2.840.10008.5.1.4.31 usando worklist.json como base.

Uso:
    python 05_mwl_scp.py
    python 05_mwl_scp.py --port 11114 --aet RIS_TESTE

Teste:
    python 02_scu_teste.py --teste mwl
    python 02_scu_teste.py --teste mwl --ip 192.168.1.60 --port 104 --aet RIS_REAL --modality CT
"""

import sys
import argparse
import json
from pathlib import Path

from pydicom.dataset import Dataset
from pynetdicom import AE, evt
from pynetdicom.sop_class import ModalityWorklistInformationFind

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


BASE_DIR = Path(__file__).parent


def load_worklist():
    fp = BASE_DIR / "worklist.json"
    if not fp.exists():
        return []
    return json.loads(fp.read_text(encoding="utf-8"))


def match(val_filtro, val_item):
    """Filtro DICOM simplificado: vazio/* = tudo, *xxx* = contem, resto = igual."""
    if val_filtro in (None, "", "*"):
        return True
    f = str(val_filtro).strip()
    v = str(val_item or "")
    if f.startswith("*") and f.endswith("*"):
        return f.strip("*").upper() in v.upper()
    if f.endswith("*"):
        return v.upper().startswith(f[:-1].upper())
    if f.startswith("*"):
        return v.upper().endswith(f[1:].upper())
    return v.upper() == f.upper()


def handle_mwl_find(event):
    req = event.identifier
    print(
        f"[MWL C-FIND] de {event.assoc.requestor.ae_title} "
        f"Modalidade={getattr(req, 'Modality', '')} "
        f"Paciente={getattr(req, 'PatientName', '')} "
        f"Data={getattr(req, 'ScheduledProcedureStepStartDate', '')}"
    )
    items = load_worklist()
    n = 0
    for it in items:
        if not match(getattr(req, "Modality", ""), it.get("Modality", "")):
            continue
        if not match(getattr(req, "PatientName", ""), it.get("PatientName", "")):
            continue
        if not match(getattr(req, "PatientID", ""), it.get("PatientID", "")):
            continue
        if not match(getattr(req, "AccessionNumber", ""), it.get("AccessionNumber", "")):
            continue
        sps_date = getattr(req, "ScheduledProcedureStepStartDate", "")
        if sps_date not in (None, ""):
            if not match(sps_date, it.get("ScheduledProcedureStepStartDate", "")):
                continue

        rsp = Dataset()
        rsp.PatientName = it["PatientName"]
        rsp.PatientID = it["PatientID"]
        rsp.PatientBirthDate = it.get("PatientBirthDate", "")
        rsp.PatientSex = it.get("PatientSex", "")
        rsp.AccessionNumber = it["AccessionNumber"]
        rsp.StudyInstanceUID = it["StudyInstanceUID"]
        rsp.RequestedProcedureID = it.get("RequestedProcedureID", "")
        rsp.RequestedProcedureDescription = it.get("RequestedProcedureDescription", "")
        rsp.Modality = it["Modality"]
        rsp.ScheduledStationAETitle = it.get("ScheduledStationAETitle", "")
        rsp.ScheduledProcedureStepStartDate = it.get("ScheduledProcedureStepStartDate", "")
        rsp.ScheduledProcedureStepStartTime = it.get("ScheduledProcedureStepStartTime", "")
        rsp.ScheduledProcedureStepID = it.get("ScheduledProcedureStepID", "")
        n += 1
        yield (0xFF00, rsp)

    print(f"[MWL C-FIND] {n} item(ns) retornado(s).")
    yield (0x0000, None)


def main():
    ap = argparse.ArgumentParser(description="MWL SCP (RIS simulado)")
    ap.add_argument("--aet", default="RIS_TESTE")
    ap.add_argument("--port", type=int, default=11114)
    args = ap.parse_args()

    ae = AE(ae_title=args.aet)
    ae.add_supported_context(ModalityWorklistInformationFind)

    print(f"[MWL SCP] RIS '{args.aet}' porta {args.port} ...")
    print(f"[MWL SCP] Base: {BASE_DIR / 'worklist.json'} (edite para seus pacientes)")
    ae.start_server(("", args.port), block=True,
                    evt_handlers=[(evt.EVT_C_FIND, handle_mwl_find)])


if __name__ == "__main__":
    main()
