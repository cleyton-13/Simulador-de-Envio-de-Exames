"""Print SCP — simula IMPRESSORA DICOM (Basic Grayscale Print Management).

Suporta o fluxo que a modalidade real faz:
  N-CREATE Film Session (1.2.840.10008.5.1.1.1)
  N-CREATE Film Box     (1.2.840.10008.5.1.1.2)
  N-SET    Image Box    (1.2.840.10008.5.1.1.4)
  N-ACTION Film Box     (imprimir, action_type=1)
  N-GET    Printer      (1.2.840.10008.5.1.1.16 -> status)
  N-DELETE (limpeza)

Cada PRINT gera um registro em ./printed/print_jobs.log
(na impressora real sairia papel; aqui valida que a modalidade
 montou o job corretamente).

Uso:
    python 06_print_scp.py
    python 06_print_scp.py --port 11115 --aet PRINTER_TESTE

Teste:
    python 02_scu_teste.py --teste print
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path

from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    BasicFilmBox,
    BasicFilmSession,
    BasicGrayscaleImageBox,
    BasicGrayscalePrintManagementMeta,
    Printer,
)

BASE_DIR = Path(__file__).parent
PRINTED = BASE_DIR / "printed"
PRINTED.mkdir(exist_ok=True)

SESSIONS = {}
FILMBOXES = {}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(PRINTED / "print_jobs.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def handle_n_create(event):
    req = event.assoc.requestor
    sop_class = event.request.AffectedSOPClassUID
    name = str(sop_class)
    # SCU pode mandar o UID (nosso teste manda) ou None (impressora real cria)
    wanted = getattr(event.request, "AffectedSOPInstanceUID", None)
    if sop_class == BasicFilmSession:
        uid = str(wanted) if wanted else generate_uid()
        SESSIONS[uid] = {"from": req.ae_title, "dataset": event.attribute_list}
        log(f"[PRINT N-CREATE FilmSession] de {req.ae_title} -> {uid}")
        rsp = Dataset()
        rsp.AffectedSOPClassUID = BasicFilmSession
        rsp.AffectedSOPInstanceUID = uid
        return 0x0000, rsp
    if sop_class == BasicFilmBox:
        uid = str(wanted) if wanted else generate_uid()
        img_uid = generate_uid()
        FILMBOXES[uid] = {"from": req.ae_title, "image_box_uid": img_uid}
        log(f"[PRINT N-CREATE FilmBox] de {req.ae_title} -> {uid} (ImageBox {img_uid})")
        rsp = Dataset()
        rsp.AffectedSOPClassUID = BasicFilmBox
        rsp.AffectedSOPInstanceUID = uid
        # Sequencia padrao do FilmBox (tags numericas p/ evitar warning de keyword)
        # (0008,1140) Referenced Image Sequence
        seq_item = Dataset()
        seq_item.ReferencedSOPClassUID = BasicGrayscaleImageBox
        seq_item.ReferencedSOPInstanceUID = img_uid
        rsp.ReferencedFilmBoxSequence = [seq_item]
        return 0x0000, rsp
    log(f"[PRINT N-CREATE] SOP desconhecido {name} -> rejeita")
    return 0x0112, None


def handle_n_set(event):
    try:
        sop_inst = getattr(event.request, "RequestedSOPInstanceUID", "?")
        log(f"[PRINT N-SET ImageBox {sop_inst}] de {event.assoc.requestor.ae_title} "
            f"(Rows={getattr(event.attribute_list, 'Rows', '?')}) -> 0x0000")
        return 0x0000, event.attribute_list
    except Exception as e:
        log(f"[PRINT N-SET ERRO] {e}")
        return 0x0110, None


def handle_n_action(event):
    try:
        sop_inst = getattr(event.request, "RequestedSOPInstanceUID", "?")
        action = getattr(event.request, "ActionTypeID", "?")
        log(f"[PRINT N-ACTION FilmBox {sop_inst} action={action}] IMPRIMIR "
            f"de {event.assoc.requestor.ae_title} → papel simulado OK")
        return 0x0000, None
    except Exception as e:
        log(f"[PRINT N-ACTION ERRO] {e}")
        return 0x0110, None


def handle_n_get(event):
    log(f"[PRINT N-GET Printer] de {event.assoc.requestor.ae_title} -> NORMAL")
    rsp = Dataset()
    rsp.PrinterStatus = "NORMAL"
    rsp.PrinterStatusInfo = "NORMAL"
    rsp.PrinterName = "PRINTER_TESTE_SIMULADA"
    return 0x0000, rsp


def handle_n_delete(event):
    sop_inst = getattr(event.request, "RequestedSOPInstanceUID", "?")
    SESSIONS.pop(sop_inst, None)
    FILMBOXES.pop(sop_inst, None)
    log(f"[PRINT N-DELETE {sop_inst}] limpeza concluída")
    return 0x0000


def main():
    ap = argparse.ArgumentParser(description="Print SCP (impressora simulada)")
    ap.add_argument("--aet", default="PRINTER_TESTE")
    ap.add_argument("--port", type=int, default=11115)
    args = ap.parse_args()

    ae = AE(ae_title=args.aet)
    # Meta SOP ja inclui Session/Box/ImageBox/Printer. Adiciona explicito p/ garantir.
    ae.add_supported_context(BasicGrayscalePrintManagementMeta)
    ae.add_supported_context(BasicFilmSession)
    ae.add_supported_context(BasicFilmBox)
    ae.add_supported_context(BasicGrayscaleImageBox)
    ae.add_supported_context(Printer)

    handlers = [
        (evt.EVT_N_CREATE, handle_n_create),
        (evt.EVT_N_SET, handle_n_set),
        (evt.EVT_N_ACTION, handle_n_action),
        (evt.EVT_N_GET, handle_n_get),
        (evt.EVT_N_DELETE, handle_n_delete),
    ]
    print(f"[PRINT SCP] Impressora '{args.aet}' porta {args.port} ...")
    print(f"[PRINT SCP] Registro em: {PRINTED / 'print_jobs.log'}")
    ae.start_server(("", args.port), block=True, evt_handlers=handlers)


if __name__ == "__main__":
    main()
