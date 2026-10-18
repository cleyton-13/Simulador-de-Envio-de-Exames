"""Gerador do jogo de imagens DICOM de teste (pasta "Teste de Envio").

Cria um conjunto varietyado de imagens VALIDAS, uma por modalidade/SOP Class,
para enviar ao PACS como se fossemos a modalidade e conferir se chegaram.

Cada imagem ganha um hash SHA-256 do PixelData (manifesto.json), que permite
validar depois que o PACS devolveu exatamente os mesmos bytes.

Uso:
    python gerar_imagens_teste.py
    python gerar_imagens_teste.py --saida "../Teste de Envio"
"""

import sys
import argparse
import hashlib
import json
import struct
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.filewriter import dcmwrite
from pydicom.uid import (
    ExplicitVRBigEndian,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    generate_uid,
)

BASE = Path(__file__).parent
# As imagens REAIS de uso livre ficam em imagens/ e são o padrão do ENVIO.
# As sintéticas vão para a pasta sinteticas/ e NÃO entram no manifesto,
# para que o jogo enviado seja sempre de imagens reais.
SAIDA_PADRAO = BASE / "sinteticas"

# name, modality, SOP Class UID, SOP keyword, bits, samples, photometric, frames, TS
PERFIL = [
    ("CT", "CT", "1.2.840.10008.5.1.4.1.1.2", "CT Image Storage", 16, 1, "MONOCHROME2", 1, ExplicitVRLittleEndian),
    ("MR", "MR", "1.2.840.10008.5.1.4.1.1.4", "MR Image Storage", 16, 1, "MONOCHROME2", 1, ImplicitVRLittleEndian),
    ("CR", "CR", "1.2.840.10008.5.1.4.1.1.1", "Computed Radiography Image Storage", 16, 1, "MONOCHROME2", 1, ExplicitVRLittleEndian),
    ("DX", "DX", "1.2.840.10008.5.1.4.1.1.1.1", "Digital X-Ray Image Storage - Presentation", 16, 1, "MONOCHROME2", 1, ExplicitVRLittleEndian),
    ("US", "US", "1.2.840.10008.5.1.4.1.1.6.1", "Ultrasound Image Storage", 8, 1, "MONOCHROME2", 1, ExplicitVRLittleEndian),
    ("XA", "XA", "1.2.840.10008.5.1.4.1.1.12.1", "X-Ray Angiographic Image Storage", 16, 1, "MONOCHROME2", 1, ImplicitVRLittleEndian),
    ("MG", "MG", "1.2.840.10008.5.1.4.1.1.1.2", "Mammography Image Storage", 16, 1, "MONOCHROME2", 1, ExplicitVRLittleEndian),
    ("RF", "RF", "1.2.840.10008.5.1.4.1.1.12.2", "Radio Fluoroscopic Image Storage", 16, 1, "MONOCHROME2", 1, ExplicitVRLittleEndian),
    ("PET", "PT", "1.2.840.10008.5.1.4.1.1.128", "PET Image Storage", 16, 1, "MONOCHROME2", 1, ExplicitVRLittleEndian),
    ("SC", "OT", "1.2.840.10008.5.1.4.1.1.7", "Secondary Capture Image Storage", 8, 1, "MONOCHROME2", 1, ExplicitVRLittleEndian),
    ("CTMF", "CT", "1.2.840.10008.5.1.4.1.1.2", "CT Image Storage (multiframe)", 16, 1, "MONOCHROME2", 8, ExplicitVRLittleEndian),
    ("CTBE", "CT", "1.2.840.10008.5.1.4.1.1.2", "CT Image Storage (big endian)", 16, 1, "MONOCHROME2", 1, ExplicitVRBigEndian),
]

PACIENTES = [
    ("TESTE^MODALIDADE", "ENVIO001", "19850110", "M"),
    ("VALIDACAO^MARIA", "ENVIO002", "19920723", "F"),
]


def pixels(rows, cols, frames, bits, seed):
    """Gradiente + marcador unico por frame (para provar integridade)."""
    total = rows * cols * frames
    maxv = (1 << bits) - 1
    vals = [((i * 7 + seed * 13) % maxv) for i in range(total)]
    if bits == 8:
        return struct.pack(f"<{total}B", *vals)
    return struct.pack(f"<{total}H", *vals)


def gerar(saida: Path):
    saida.mkdir(parents=True, exist_ok=True)
    # apaga SOMENTE as sintéticas que este script criou
    for f in saida.glob("SINT_*.dcm"):
        f.unlink()
    manifesto = []

    for idx, (tag, modality, sop_uid, sop_nome, bits, samples, photo, frames, ts) in enumerate(PERFIL):
        print("@P " + json.dumps({"n": idx, "total": len(PERFIL),
                                 "etapa": "gerando", "item": tag, "status": "..."}),
              flush=True)
        pidx = idx % len(PACIENTES)
        pname, pid, dob, sexo = PACIENTES[pidx]
        rows, cols = (256, 256) if modality in ("CR", "DX", "US", "MG") else (128, 128)

        fm = FileMetaDataset()
        fm.MediaStorageSOPClassUID = sop_uid
        fm.MediaStorageSOPInstanceUID = generate_uid()
        fm.TransferSyntaxUID = ts
        sop_uid_inst = fm.MediaStorageSOPInstanceUID
        study_uid = generate_uid()
        series_uid = generate_uid()

        nome = f"SINT_{tag}_{pid}_{sop_uid_inst}.dcm"
        ds = FileDataset(str(saida / nome), {}, file_meta=fm, preamble=b"\0" * 128)

        # IOD de imagem
        ds.ImageType = ["DERIVED", "SECONDARY", "AXIAL"]
        ds.SOPClassUID = sop_uid
        ds.SOPInstanceUID = sop_uid_inst
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.PatientName = pname
        ds.PatientID = pid
        ds.PatientBirthDate = dob
        ds.PatientSex = sexo
        ds.Modality = modality
        ds.Manufacturer = "SIMULADOR DICOM"
        ds.ManufacturerModelName = "ENVIO-TEST"
        ds.StudyDate = "20261016"
        ds.StudyTime = f"{9 + (idx % 8):02d}{idx % 60:02d}00"
        ds.StudyDescription = f"Envio de teste {sop_nome}"
        ds.SeriesNumber = 1
        ds.InstanceNumber = 1
        ds.StudyID = "1"
        ds.AccessionNumber = f"ACC{9000 + idx}"
        ds.PatientPosition = "HFS"
        ds.Rows = rows
        ds.Columns = cols
        ds.SamplesPerPixel = samples
        ds.PhotometricInterpretation = photo
        ds.BitsAllocated = bits
        ds.BitsStored = bits
        ds.HighBit = bits - 1
        ds.PixelRepresentation = 0
        ds.RescaleIntercept = "-1024"
        ds.RescaleSlope = "1"
        ds.PixelSpacing = [0.5, 0.5]
        ds.SliceThickness = 5.0
        ds.KVP = 120
        if frames > 1:
            ds.NumberOfFrames = str(frames)
        ds.PixelData = pixels(rows, cols, frames, bits, idx)

        ds.save_as(str(saida / nome), write_like_original=False) if ts != ExplicitVRBigEndian \
            else dcmwrite(str(saida / nome), ds, enforce_file_format=True)

        # hash do array DECODIFICADO, lido do arquivo ja gravado:
        # (para big-endian o pydicom troca os bytes na escrita, entao so
        #  re-lendo o arquivo o hash reflete o que realmente vai trafegar)
        salvo = dcmread(str(saida / nome))
        arr = salvo.pixel_array
        arr_bytes = arr.tobytes()

        manifesto.append({
            "arquivo": nome,
            "tag": tag,
            "sop_classe_nome": sop_nome,
            "sop_class_uid": sop_uid,
            "sop_instance_uid": sop_uid_inst,
            "study_instance_uid": study_uid,
            "series_instance_uid": series_uid,
            "patient_id": pid,
            "patient_name": pname,
            "modality": modality,
            "transfer_syntax": ts,
            "transfer_syntax_nome": ts.name,
            "rows": rows,
            "columns": cols,
            "frames": frames,
            "bits": bits,
            "bytes_pixels": len(salvo.PixelData),
            "pixel_dtype": str(arr.dtype),
            "pixel_sha256": hashlib.sha256(arr_bytes).hexdigest(),
            "raw_sha256": hashlib.sha256(salvo.PixelData).hexdigest(),
        })
        print(f"[OK] {nome:52s} {sop_nome[:38]:38s} {ts.name}")
        print("@P " + json.dumps({"n": idx + 1, "total": len(PERFIL),
                                 "etapa": "gerando", "item": tag, "status": "ok"}),
              flush=True)

    mf = saida / "manifesto_sinteticas.json"
    mf.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(manifesto)} imagens em {saida}")
    print(f"manifesto: {mf}")

    try:
        cfg = json.loads((BASE.parent / "config.json").read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    ip = cfg.get("pacs_ip", "127.0.0.1")
    print("\nDestinos configurados (AE Title @ host:PORTA):")
    print(f"  PACS        {cfg.get('pacs_aet', 'PACS_TESTE')} @ {ip}:{cfg.get('pacs_port', 11112)}")
    print(f"  RIS / MWL   {cfg.get('mwl_aet', 'RIS_TESTE')} @ {ip}:{cfg.get('mwl_port', 11114)}")
    print(f"  Impressora  {cfg.get('printer_aet', 'PRINTER_TESTE')} @ {ip}:{cfg.get('printer_port', 11115)}")
    print("\nEnviar e validar:")
    print(f"  python 10_envio_validacao.py --pacs-ip {ip} "
          f"--pacs-port {cfg.get('pacs_port', 11112)} "
          f"--pacs-aet {cfg.get('pacs_aet', 'PACS_TESTE')} --meu-aet SUA_MODALIDADE")
    return manifesto


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    a = ap.parse_args()
    gerar(Path(a.saida))