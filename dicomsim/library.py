"""Biblioteca de imagens: reais (Teste de Envio/manifesto.json) ou sintéticas."""
from __future__ import annotations

import json
import struct
from datetime import datetime
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

RAIZ = Path(__file__).resolve().parent.parent
PASTA_ENVIO = RAIZ / "Teste de Envio"
PASTA_TCIA = PASTA_ENVIO / "imagens_tcia"   # baixadas por baixar_imagens.py (não vão ao git)

SOP_POR_MODALIDADE = {
    "CT": "1.2.840.10008.5.1.4.1.1.2",
    "MR": "1.2.840.10008.5.1.4.1.1.4",
    "CR": "1.2.840.10008.5.1.4.1.1.1",
    "DX": "1.2.840.10008.5.1.4.1.1.1.1",
    "US": "1.2.840.10008.5.1.4.1.1.6.1",
    "XA": "1.2.840.10008.5.1.4.1.1.12.1",
    "MG": "1.2.840.10008.5.1.4.1.1.1.2",
    "RF": "1.2.840.10008.5.1.4.1.1.12.2",
    "PT": "1.2.840.10008.5.1.4.1.1.128",
    "OT": "1.2.840.10008.5.1.4.1.1.7",
}


def manifesto(pasta=PASTA_ENVIO):
    mf = Path(pasta) / "manifesto.json"
    return json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else []


def imagem_real(modalidade, pasta=PASTA_ENVIO):
    """Primeira imagem real da modalidade (por tag), com pixels. None se não houver."""
    for m in manifesto(pasta):
        if m.get("tag") == modalidade and m.get("tem_pixels"):
            p = Path(pasta) / m["arquivo"]
            if p.exists():
                return dcmread(str(p))
    return None


def imagem_sintetica(modalidade, indice=0, lado=256):
    """Imagem nova de 16 bits com padrão determinístico — sempre disponível."""
    sop = SOP_POR_MODALIDADE.get(modalidade, SOP_POR_MODALIDADE["OT"])
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = sop
    fm.MediaStorageSOPInstanceUID = generate_uid()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset("", {}, file_meta=fm, preamble=b"\0" * 128)
    ds.SOPClassUID = sop
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
    ds.Modality = modalidade
    ds.InstanceNumber = indice + 1
    ds.Rows = ds.Columns = lado
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    if modalidade == "CT":
        ds.RescaleIntercept = "-1024"
        ds.RescaleSlope = "1"
    # círculo com gradiente que "anda" a cada corte
    c = lado / 2
    px = bytearray()
    for y in range(lado):
        for x in range(lado):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            v = 3000 - int(d * 10) + indice * 40 if d < c * 0.9 else 100
            px += struct.pack("<H", max(0, min(4095, v)))
    ds.PixelData = bytes(px)
    return ds


def listar_reais(modalidade, pasta=PASTA_ENVIO):
    """Todos os arquivos reais da modalidade, em ordem estável:
    1º os do manifesto (Teste de Envio/imagens), 2º os baixados do TCIA (imagens_tcia/<MOD>)."""
    out = []
    for m in manifesto(pasta):
        if m.get("tag") == modalidade:
            p = Path(pasta) / m["arquivo"]
            if p.exists():
                out.append(p)
    tcia = Path(pasta) / "imagens_tcia" / modalidade
    if tcia.exists():
        out += sorted(tcia.glob("*.dcm"))
    return out


def listar_anomalas(pasta=PASTA_ENVIO):
    d = Path(pasta) / "casos_especiais"
    return sorted(d.glob("*.dcm")) if d.exists() else []


def obter_imagem(modalidade, indice=0, origem="real"):
    """Dataset novo (cópia) para o `indice`-ésimo envio.

    origem: "real"      imagens reais anonimizadas da modalidade (rotaciona entre elas)
            "anomala"   casos de borda (sem meta, ACR-NEMA, truncada...) — teste negativo
            "sintetica" gerada na hora
    Se a origem pedida não tem arquivos, cai para sintética.
    """
    if origem == "anomala":
        arqs = listar_anomalas()
        if arqs:
            return dcmread(str(arqs[indice % len(arqs)]), force=True)
    elif origem == "real":
        arqs = listar_reais(modalidade)
        if arqs:
            return dcmread(str(arqs[indice % len(arqs)]))
    return imagem_sintetica(modalidade, indice)


def carimbar(ds, paciente, estudo_uid, serie_uid, serie_num, instancia_num,
             fabricante=None, modelo=None, estacao="", aet_local="", sop_uid=None):
    """Amarra a imagem ao exame (paciente + estudo da worklist) e cria UIDs novos."""
    agora = datetime.now()
    # Acentos exigem declarar o conjunto de caracteres, senão o PACS mostra "JosÃ©".
    textos = " ".join(str(paciente.get(k, "")) for k in ("nome", "id", "procedimento", "acesso"))
    if not textos.isascii():
        try:
            textos.encode("latin-1")
            ds.SpecificCharacterSet = "ISO_IR 100"      # Latin-1: o que os sistemas brasileiros usam
        except UnicodeEncodeError:
            ds.SpecificCharacterSet = "ISO_IR 192"      # UTF-8
    ds.PatientName = paciente.get("nome", "")
    ds.PatientID = paciente.get("id", "")
    if paciente.get("nascimento"):
        ds.PatientBirthDate = paciente["nascimento"]
    if paciente.get("sexo"):
        ds.PatientSex = paciente["sexo"]
    ds.AccessionNumber = paciente.get("acesso", "")
    ds.StudyID = paciente.get("acesso", "") or "1"
    ds.StudyDescription = paciente.get("procedimento", "")
    ds.StudyInstanceUID = estudo_uid
    ds.SeriesInstanceUID = serie_uid
    ds.SeriesNumber = serie_num
    ds.InstanceNumber = instancia_num
    ds.StudyDate = paciente.get("data") or agora.strftime("%Y%m%d")
    ds.StudyTime = agora.strftime("%H%M%S")
    ds.ContentDate = agora.strftime("%Y%m%d")
    ds.ContentTime = agora.strftime("%H%M%S")
    ds.SOPInstanceUID = sop_uid or generate_uid()
    if hasattr(ds, "file_meta"):
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    if fabricante:
        ds.Manufacturer = fabricante
    if modelo:
        ds.ManufacturerModelName = modelo
    if estacao:
        ds.StationName = estacao
    if paciente.get("modalidade"):
        ds.Modality = paciente["modalidade"]
    return ds
