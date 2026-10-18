"""Gera uma imagem DICOM de teste (CT fake 128x128).

Uso:
    python 03_gerar_imagem.py
    python 03_gerar_imagem.py --patient "TESTE^SIMULADOR" --modality CT

Gera teste_CT.dcm na mesma pasta, pronto para C-STORE.
"""

import argparse
import json
import struct
from pathlib import Path

from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

BASE_DIR = Path(__file__).parent


def gerar(patient="TESTE^SIMULADOR", modality="CT", saida="teste_CT.dcm"):
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(saida, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = patient
    ds.PatientID = "TESTE001"
    ds.Modality = modality
    ds.StudyDate = "20261016"
    ds.StudyDescription = "Imagem fake gerada pelo simulador"
    ds.Rows, ds.Columns = 128, 128
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    # pixel data: gradiente simples sem numpy (128x128 uint16)
    total = 128 * 128
    ds.PixelData = struct.pack(f"<{total}H", *[(i % 4096) for i in range(total)])

    out = BASE_DIR / saida
    ds.save_as(str(out), write_like_original=False)

    # resumo do que foi gerado + para onde ele sera enviado (config.json)
    try:
        cfg = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    pacs = f"{cfg.get('pacs_aet', 'PACS_TESTE')} @ {cfg.get('pacs_ip', '127.0.0.1')}:{cfg.get('pacs_port', 11112)}"
    ris = f"{cfg.get('mwl_aet', 'RIS_TESTE')} @ {cfg.get('pacs_ip', '127.0.0.1')}:{cfg.get('mwl_port', 11114)}"
    prn = f"{cfg.get('printer_aet', 'PRINTER_TESTE')} @ {cfg.get('pacs_ip', '127.0.0.1')}:{cfg.get('printer_port', 11115)}"

    print(f"[OK] Gerado: {out}")
    print(f"     PatientName   = {ds.PatientName}   PatientID = {ds.PatientID}")
    print(f"     Modality      = {ds.Modality}   SOPClassUID = {ds.SOPClassUID.name}")
    print(f"     StudyInstanceUID = {ds.StudyInstanceUID}")
    print(f"     SeriesInstanceUID= {ds.SeriesInstanceUID}")
    print(f"     SOPInstanceUID    = {ds.SOPInstanceUID}")
    print(f"     TransferSyntax    = {ds.file_meta.TransferSyntaxUID.name}")
    print(f"     Pixels            = {ds.Rows}x{ds.Columns}, {ds.BitsAllocated} bits, "
          f"{len(ds.PixelData)} bytes")
    print("     Destinos configurados:")
    print(f"       PACS       {pacs}   (C-ECHO, C-STORE, C-FIND)")
    print(f"       RIS/MWL    {ris}   (C-FIND worklist)")
    print(f"       Impressora {prn}   (PRINT)")
    print(f"     Enviar:  python 02_scu_teste.py --teste store --arquivo {saida} "
          f"--ip {cfg.get('pacs_ip', '127.0.0.1')} --port {cfg.get('pacs_port', 11112)} "
          f"--aet {cfg.get('pacs_aet', 'PACS_TESTE')}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", default="TESTE^SIMULADOR")
    ap.add_argument("--modality", default="CT")
    ap.add_argument("--saida", default="teste_CT.dcm")
    a = ap.parse_args()
    gerar(a.patient, a.modality, a.saida)
