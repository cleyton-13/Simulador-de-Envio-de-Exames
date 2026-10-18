"""PACS simulado (SCP de armazenamento, consulta e recuperação).

Guarda as imagens recebidas em ./received e responde:
  - C-ECHO   : verificação de conectividade
  - C-STORE  : salva o arquivo .dcm
  - C-FIND   : lista estudos / séries / imagens guardados
  - C-MOVE   : devolve imagens para um destino cadastrado

No C-MOVE o PACS abre uma NOVA conexão de volta para o destino. Informe esse
destino com --move-dest-aet / --move-dest-ip / --move-dest-port (padrão
RECURTOR_TESTE @ 127.0.0.1:11116, que é o receptor do teste de envio).

Uso:
    python 01_scp_pacs.py
    python 01_scp_pacs.py --aet PACS_PROD --port 104
    python 01_scp_pacs.py --port 11112 --move-dest-port 11116
"""

import argparse
import json
import sys
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset
from pydicom.filewriter import dcmwrite
from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
)
from pydicom.uid import (
    ExplicitVRBigEndian,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).parent
RECEIVED = BASE_DIR / "received"
RECEIVED.mkdir(exist_ok=True)

# SOP Classes aceitos (o máximo do padrão são 128 contextos por associação)
SOPS = {
    "1.2.840.10008.5.1.4.1.1.1": "Computed Radiography",
    "1.2.840.10008.5.1.4.1.1.1.1": "Digital X-Ray (apresentação)",
    "1.2.840.10008.5.1.4.1.1.1.2": "Mammography",
    "1.2.840.10008.5.1.4.1.1.2": "CT Image Storage",
    "1.2.840.10008.5.1.4.1.1.2.1": "Enhanced CT",
    "1.2.840.10008.5.1.4.1.1.4": "MR Image Storage",
    "1.2.840.10008.5.1.4.1.1.4.1": "Enhanced MR",
    "1.2.840.10008.5.1.4.1.1.6.1": "Ultrasound Image",
    "1.2.840.10008.5.1.4.1.1.7": "Secondary Capture",
    "1.2.840.10008.5.1.4.1.1.11.1": "Grayscale Softcopy Presentation State",
    "1.2.840.10008.5.1.4.1.1.12.1": "X-Ray Angiographic",
    "1.2.840.10008.5.1.4.1.1.12.2": "Radio Fluoroscopic",
    "1.2.840.10008.5.1.4.1.1.128": "PET Image",
}
TRANSFERENCIAS = [ImplicitVRLittleEndian, ExplicitVRLittleEndian, ExplicitVRBigEndian]

DESTINO = {"ip": "127.0.0.1", "porta": 11116, "aet": "RECURTOR_TESTE"}


def handle_echo(event):
    req = event.assoc.requestor
    print(f"[C-ECHO] de {req.ae_title}@{req.address}:{req.port} → 0x0000 Sucesso")
    return 0x0000


def _ts_para_arquivar(ds):
    """PACS de verdade normaliza para Explicit VR Little Endian — mas SÓ o que
    não é encapsulado. Pixel data comprimida (JPEG/JPEG2000/JPEG-LS/RLE) depende
    da sintaxe que declara o encapsulamento: trocar por uma sintaxe sem
    compressão corrompe o objeto."""
    ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
    if ts is None:
        return ExplicitVRLittleEndian
    uid = str(ts)
    nome = getattr(ts, "name", "")
    encapsulado = (
        uid.startswith(("1.2.840.10008.1.2.4", "1.2.840.10008.1.2.5"))
        or any(k in nome for k in ("JPEG", "RLE", "MPEG", "Deflated"))
        or getattr(ts, "is_deflated", False)
    )
    return ts if encapsulado else ExplicitVRLittleEndian


def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    destino_ts = _ts_para_arquivar(ds)
    ds.file_meta.TransferSyntaxUID = destino_ts
    fname = f"{ds.SOPInstanceUID}.dcm"
    dcmwrite(str(RECEIVED / fname), ds, enforce_file_format=True)
    print(f"[C-STORE] {event.assoc.requestor.ae_title} | "
          f"{getattr(ds, 'Modality', '?')} | {getattr(ds, 'PatientName', '?')} | "
          f"{fname} salvo em received/ como {destino_ts.name}")
    return 0x0000


def _listar():
    for f in RECEIVED.glob("*.dcm"):
        try:
            yield dcmread(str(f), stop_before_pixels=True)
        except Exception:
            continue


def handle_find(event):
    """Responde C-FIND no Study Root (STUDY, SERIES ou IMAGE)."""
    q = event.identifier
    nivel = str(getattr(q, "QueryRetrieveLevel", "STUDY"))
    print(f"[C-FIND] nível={nivel} de {event.assoc.requestor.ae_title}")

    vistos = set()
    for s in _listar():
        # filtros do pedido
        if not _combina(getattr(q, "PatientName", ""), str(s.get("PatientName", ""))):
            continue
        if not _combina(getattr(q, "PatientID", ""), str(s.get("PatientID", ""))):
            continue
        if not _combina(getattr(q, "StudyInstanceUID", ""), str(s.get("StudyInstanceUID", ""))):
            continue
        if not _combina(getattr(q, "SOPInstanceUID", ""), str(s.get("SOPInstanceUID", ""))):
            continue

        chave = (nivel, str(s.get("StudyInstanceUID", "")), str(s.get("SeriesInstanceUID", "")))
        if nivel != "IMAGE":
            chave = chave[:2] if nivel == "STUDY" else chave
            if chave in vistos:
                continue
        vistos.add(chave)

        r = Dataset()
        r.QueryRetrieveLevel = nivel
        if nivel == "STUDY":
            r.PatientName = s.get("PatientName", "")
            r.PatientID = s.get("PatientID", "")
            r.StudyInstanceUID = s.get("StudyInstanceUID", "")
            r.StudyDate = s.get("StudyDate", "")
            r.StudyDescription = s.get("StudyDescription", "")
            r.Modality = s.get("Modality", "")
        else:
            for k in ("PatientName", "PatientID", "StudyInstanceUID", "SeriesInstanceUID",
                      "SOPInstanceUID", "StudyDate", "Modality", "SOPClassUID"):
                if k in s:
                    setattr(r, k, getattr(s, k))
        yield (0xFF00, r)
    yield (0x0000, None)


def _combina(filtro, valor):
    """Filtro DICOM: vazio ou * = tudo, *txt* = contém, resto = igual."""
    if filtro in (None, "", "*"):
        return True
    f = str(filtro).strip()
    v = str(valor or "")
    if f.startswith("*") and f.endswith("*"):
        return f.strip("*").upper() in v.upper()
    if f.endswith("*"):
        return v.upper().startswith(f[:-1].upper())
    if f.startswith("*"):
        return v.upper().endswith(f[1:].upper())
    return v.upper() == f.upper()


def handle_move(event):
    """C-MOVE: entrega as instâncias pedidas no destino configurado.

    No C-MOVE o mesmo AE volta a associar como SCU — por isso os SOP Classes
    também são registrados como contextos *requested* (sem isso dá erro).
    """
    q = event.identifier
    print(f"[C-MOVE] de {event.assoc.requestor.ae_title} para "
          f"{DESTINO['aet']} @ {DESTINO['ip']}:{DESTINO['porta']}")

    arquivos = []
    for f in RECEIVED.glob("*.dcm"):
        try:
            s = dcmread(str(f), stop_before_pixels=True)
        except Exception:
            continue
        if not _combina(getattr(q, "SOPInstanceUID", ""), str(s.get("SOPInstanceUID", ""))):
            continue
        if not _combina(getattr(q, "StudyInstanceUID", ""), str(s.get("StudyInstanceUID", ""))):
            continue
        arquivos.append(f)

    yield (DESTINO["ip"], DESTINO["porta"])   # destino
    yield len(arquivos)                        # nº de suboperações
    for f in arquivos:                         # uma por instância, com pixels
        ds = dcmread(str(f))
        print(f"[C-MOVE] enviando {str(ds.SOPInstanceUID)[:40]}…")
        yield (0xFF00, ds)


def contextos_necessarios():
    """Descobre SOP Classes e Transfer Syntaxes a partir do manifesto.

    Sem isso o PACS recusaria imagens reais comprimidas (JPEG, JPEG2000):
    em estudos reais, sintaxe comprimida é o normal, não a exceção.
    """
    pares = {}
    mf = BASE_DIR / "Teste de Envio" / "manifesto.json"
    if mf.exists():
        try:
            for m in json.loads(mf.read_text(encoding="utf-8")):
                sop, ts = m["sop_class_uid"], m["transfer_syntax"]
                if sop and ts:
                    pares.setdefault(sop, set()).add(ts)
        except Exception:
            pares = {}
    if not pares:
        for sop in SOPS:
            pares[sop] = set(TRANSFERENCIAS)
    # garante as três transferências clássicas para todo SOP encontrado
    return {sop: sorted(ts | set(TRANSFERENCIAS)) for sop, ts in pares.items()}


def main():
    ap = argparse.ArgumentParser(description="PACS simulado (SCP)")
    ap.add_argument("--aet", default="PACS_TESTE")
    ap.add_argument("--port", type=int, default=11112)
    ap.add_argument("--move-dest-aet", default="RECURTOR_TESTE",
                    help="AE Title para onde o C-MOVE entrega")
    ap.add_argument("--move-dest-ip", default="127.0.0.1")
    ap.add_argument("--move-dest-port", type=int, default=11116)
    args = ap.parse_args()

    DESTINO.update({"aet": args.move_dest_aet, "ip": args.move_dest_ip,
                    "porta": args.move_dest_port})

    ae = AE(ae_title=args.aet)
    ae.add_supported_context(Verification)
    n = 0
    for sop, tss in contextos_necessarios().items():
        ae.add_supported_context(sop, tss)
        ae.add_requested_context(sop, tss)   # necessário para o C-MOVE
        n += 1
    ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
    ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)

    handlers = [
        (evt.EVT_C_ECHO, handle_echo),
        (evt.EVT_C_STORE, handle_store),
        (evt.EVT_C_FIND, handle_find),
        (evt.EVT_C_MOVE, handle_move),
    ]

    print(f"[SCP] PACS '{args.aet}' ouvindo na porta {args.port} …")
    print(f"[SCP] Recebendo C-STORE em: {RECEIVED}")
    print(f"[SCP] C-MOVE entrega em: {DESTINO['aet']} @ {DESTINO['ip']}:{DESTINO['porta']}")
    print(f"[SCP] SOP Classes: {n} (com as Transfer Syntaxes do manifesto)")
    print("[SCP] Ctrl+C para parar.")
    ae.start_server(("", args.port), block=True, evt_handlers=handlers)


if __name__ == "__main__":
    main()