"""Monta o manifesto.json varrendo Teste de Envio/imagens.

O agrupamento (campo `tag`) vem da **modalidade real do arquivo** — não do
nome do arquivo, porque nomes de amostra nem sempre correspondem ao conteúdo
(ex.: CT-MONO2-16-ankle.dcm é Secondary Capture e liver_1frame.dcm é
Segmentação).

Para cada imagem calcula:
  - SOP Class, SOP Instance, Study e Series Instance UID
  - Transfer Syntax, modalidade, paciente, descrição em português
  - dimensões, quadros, bits, photometric interpretation
  - sha256 do array de pixels DECODIFICADO (independe da sintaxe)
  - sha256 dos bytes crus do PixelData e do arquivo inteiro
  - `hash_tipo`: qual hash usar na conferência
      "decodificado" — dá para decodificar os pixels aqui
      "bytes"        — comprimido sem decodificador local; compara os bytes
      "sem_pixels"   — objeto sem pixel data (SR, RT Dose, ECG)

Uso:
    python "Teste de Envio/montar_manifesto.py"
"""

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from pydicom import dcmread

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
IMAGENS = BASE / "imagens"
MANIFESTO = BASE / "manifesto.json"

DESCRICOES = {
    "1.2.840.10008.5.1.4.1.1.1": "CR — radiografia computacional",
    "1.2.840.10008.5.1.4.1.1.1.1": "DX — radiografia digital",
    "1.2.840.10008.5.1.4.1.1.2": "CT — tomografia computadorizada",
    "1.2.840.10008.5.1.4.1.1.4": "MR — ressonância magnética",
    "1.2.840.10008.5.1.4.1.1.6.1": "US — ultrassonografia",
    "1.2.840.10008.5.1.4.1.1.7": "SC — captura secundária",
    "1.2.840.10008.5.1.4.1.1.7.4": "SC — captura secundária multiframe",
    "1.2.840.10008.5.1.4.1.1.12.1": "XA — angiografia por raios X",
    "1.2.840.10008.5.1.4.1.1.12.2": "RF — fluoroscopia",
    "1.2.840.10008.5.1.4.1.1.20": "NM — imagem de medicina nuclear",
    "1.2.840.10008.5.1.4.1.1.128": "PT — imagem de PET",
    "1.2.840.10008.5.1.4.1.1.481.1": "RT Dose — dose de radioterapia",
    "1.2.840.10008.5.1.4.1.1.481.2": "RT Structure — estrutura de radioterapia",
    "1.2.840.10008.5.1.4.1.1.66.1": "SEG — segmentação",
    "1.2.840.10008.5.1.4.1.1.88.33": "SR — relatório estruturado",
    "1.2.840.10008.5.1.4.1.1.9.1.1": "ECG — traçado de 12 derivações",
    "1.2.840.10008.5.1.4.1.1.9.1.3": "ECG — observações",
    "1.2.840.10008.5.1.4.1.1.11.1": "GSPS — estado de apresentação",
}
SEM_PIXEL = ("1.2.840.10008.5.1.4.1.1.88.33", "1.2.840.10008.5.1.4.1.1.481.1",
             "1.2.840.10008.5.1.4.1.1.481.2", "1.2.840.10008.5.1.4.1.1.9.1.1",
             "1.2.840.10008.5.1.4.1.1.9.1.3", "1.2.840.10008.5.1.4.1.1.11.1")


def tag_real(ds):
    """Grupo de agrupamento pela modalidade real do objeto."""
    mod = str(getattr(ds, "Modality", "") or "").strip().upper()
    if mod:
        return mod
    nome = getattr(ds.SOPClassUID, "name", "")
    for chave in ("CT Image", "MR Image", "Ultrasound", "Computed Radiography",
                  "Digital X-Ray", "X-Ray Angiographic", "Secondary Capture",
                  "Nuclear Medicine", "PET", "RT Dose", "Structured Report",
                  "Segmentation", "Enhanced"):
        if chave in nome:
            return chave.split()[0].upper()
    return "OUT"


def main():
    arquivos = sorted(IMAGENS.glob("*.dcm"))
    if not arquivos:
        print(f"Nenhuma imagem em {IMAGENS}")
        print('Rode antes:  python "Teste de Envio/14_imagens_reais.py"')
        return

    itens, ignoradas = [], []
    for f in arquivos:
        try:
            ds = dcmread(str(f))
        except Exception as e:
            ignoradas.append((f.name, str(e)[:60]))
            continue

        ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
        sop = str(ds.SOPClassUID)
        tem_pixels = "PixelData" in ds and len(ds.PixelData or b"") > 0

        decodavel, decoded_hash = False, ""
        if tem_pixels:
            try:
                arr = ds.pixel_array
                decoded_hash = hashlib.sha256(arr.tobytes()).hexdigest()
                decodavel = True
            except Exception:
                decodavel = False

        if decodavel:
            hash_tipo = "decodificado"
        elif tem_pixels:
            hash_tipo = "bytes"
        else:
            hash_tipo = "sem_pixels"

        tag = tag_real(ds)
        itens.append({
            "arquivo": f"imagens/{f.name}",
            "tag": tag,
            "origem": "real" if f.name.startswith("REAL_") else "sintetica",
            "descricao": DESCRICOES.get(sop, getattr(ds.SOPClassUID, "name", sop)),
            "sop_classe_nome": getattr(ds.SOPClassUID, "name", sop),
            "sop_class_uid": sop,
            "sop_instance_uid": str(ds.SOPInstanceUID),
            "study_instance_uid": str(getattr(ds, "StudyInstanceUID", "")),
            "series_instance_uid": str(getattr(ds, "SeriesInstanceUID", "")),
            "patient_id": str(getattr(ds, "PatientID", "")),
            "patient_name": str(getattr(ds, "PatientName", "")),
            "modality": str(getattr(ds, "Modality", "")),
            "transfer_syntax": str(ts) if ts else "",
            "transfer_syntax_nome": ts.name if ts else "desconhecida",
            "rows": int(getattr(ds, "Rows", 0) or 0),
            "columns": int(getattr(ds, "Columns", 0) or 0),
            "frames": int(getattr(ds, "NumberOfFrames", 1) or 1),
            "bits": int(getattr(ds, "BitsAllocated", 0) or 0),
            "samples": int(getattr(ds, "SamplesPerPixel", 1) or 1),
            "photometric": str(getattr(ds, "PhotometricInterpretation", "")),
            "bytes_pixels": len(ds.PixelData) if tem_pixels else 0,
            "tem_pixels": tem_pixels,
            "decodavel": decodavel,
            "hash_tipo": hash_tipo,
            "pixel_sha256": decoded_hash,
            "raw_sha256": hashlib.sha256(ds.PixelData).hexdigest() if tem_pixels else "",
            "arquivo_sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
        })

    MANIFESTO.write_text(json.dumps(itens, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    grupos = {}
    for i in itens:
        grupos.setdefault(i["tag"], []).append(i)

    print(f"{len(itens)} imagens no manifesto · {len(ignoradas)} ignorada(s)")
    print(f"manifesto: {MANIFESTO}\n")
    print(f"{'grupo':9s} {'n':>3s} {'confere':9s}  SOP Class / sintaxe")
    print("-" * 78)
    for t, lst in sorted(grupos.items()):
        a = lst[0]
        ts = a["transfer_syntax_nome"].replace("Explicit VR ", "EVR ").replace(
            "Implicit VR ", "IVR ")
        conf = sum(1 for x in lst if x["hash_tipo"] == "decodificado")
        print(f"{t:9s} {len(lst):3d} {conf:4d}/{len(lst):<4d} {a['sop_classe_nome'][:30]:30s} {ts}")
    print("-" * 78)
    bytes_ = [i["tag"] for i in itens if i["hash_tipo"] == "bytes"]
    sempx = [i["tag"] for i in itens if i["hash_tipo"] == "sem_pixels"]
    if bytes_:
        print(f"Conferência por bytes (comprimido sem decodificador local): "
              f"{', '.join(sorted(set(bytes_)))}")
    if sempx:
        print(f"Sem pixel data — só envio (SR, RT Dose, ECG, GSPS): "
              f"{', '.join(sorted(set(sempx)))}")
    if ignoradas:
        for n, e in ignoradas:
            print(f"  ignorada: {n} ({e})")
    print(f"\nGerado em {datetime.now():%Y-%m-%d %H:%M:%S}")


if __name__ == "__main__":
    main()