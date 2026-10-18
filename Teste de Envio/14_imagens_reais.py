"""Baixa imagens DICOM REAIS de uso livre e monta a biblioteca de envio.

Fonte principal — Open Microscopy Environment (OME):
    https://downloads.openmicroscopy.org/images/DICOM/samples/
    Domínio público (Creative Commons Public Domain Mark 1.0).
    Arquivos originais: https://barre.dev/medical/samples/
    Anexo: Sébastien Barré

Fonte complementar — amostras que já vêm instaladas com o pydicom
    (pacote pydicom, licença MIT): imagens reais anonimizadas e arquivos de
    borda (big endian, RLE, JPEG, JPEG2000, multiframe, coloridos).

O script é idempotente: se o arquivo já existe, não baixa de novo.
Depois de rodar, gere o manifesto com:

    python "Teste de Envio/montar_manifesto.py"
"""

import shutil
import ssl
import sys
import urllib.request
from pathlib import Path

from pydicom.uid import generate_uid

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
DESTINO = BASE / "imagens"
DESTINO.mkdir(parents=True, exist_ok=True)

URL_BASE = "https://downloads.openmicroscopy.org/images/DICOM/samples/"

# (arquivo de origem, rótulo, modalidade, descrição)
OME = [
    ("CR-MONO1-10-chest.dcm", "CR", "CR", "Tórax (CR digital)"),
    ("CT-MONO2-8-abdo.dcm", "CT", "CT", "Abdome"),
    ("CT-MONO2-12-lomb-an2.dcm", "CT", "CT", "Coluna lombar"),
    ("CT-MONO2-16-ankle.dcm", "CT", "CT", "Tornozelo"),
    ("CT-MONO2-16-brain.dcm", "CT", "CT", "Crânio"),
    ("CT-MONO2-16-chest.dcm", "CT", "CT", "Tórax"),
    ("CT-MONO2-16-ort.dcm", "CT", "CT", "Tórax / coluna"),
    ("MR-MONO2-12-an2.dcm", "MR", "MR", "Ankle"),
    ("MR-MONO2-12-angio-an1.dcm", "MR", "MR", "Angiografia"),
    ("MR-MONO2-12-shoulder.dcm", "MR", "MR", "Ombro"),
    ("MR-MONO2-16-head.dcm", "MR", "MR", "Crânio"),
    ("MR-MONO2-16-knee.dcm", "MR", "MR", "Joelho"),
    ("MR-MONO2-8-16x-heart.dcm", "MR", "MR", "Coração (16 quadros)"),
    ("NM-MONO2-16-13x-heart.dcm", "NM", "NM", "Medicina nuclear coração (13 quadros)"),
    ("US-MONO2-8-8x-execho.dcm", "US", "US", "Ecocardiograma (8 quadros)"),
    ("OT-MONO2-8-a7.dcm", "OT", "OT", "Documento secundário"),
    ("OT-MONO2-8-colon.dcm", "OT", "OT", "Colonoscopia"),
    ("OT-MONO2-8-hip.dcm", "OT", "OT", "Quadril"),
]

# amostras reais que já vêm no pydicom (imagens de verdade, anonimizadas)
PYDICOM_REAIS = [
    ("CT_small.dcm", "CT", "CT", "TC de corpo inteiro"),
    ("liver_1frame.dcm", "CT", "CT", "Fígado"),
    ("MR_small.dcm", "MR", "MR", "RM de cabeça"),
    ("MR_small_implicit.dcm", "MR", "MR", "RM (VR implícito)"),
    ("MR_small_bigendian.dcm", "MR", "MR", "RM (big endian)"),
    ("MR_small_RLE.dcm", "MR", "MR", "RM comprimida RLE"),
    ("US_small_UNCR.dcm", "US", "US", "Ultrassonografia"),
    ("US_VOLUME_6.dcm", "US", "US", "Ultrassonografia volumétrica"),
    ("chrUS.dcm", "US", "US", "Ultrassonografia 3D"),
    ("color-pl.dcm", "OT", "OT", "Imagem colorida"),
    ("examples_rgb_color.dcm", "OT", "OT", "Imagem RGB"),
    ("examples_palette.dcm", "OT", "OT", "Imagem com paleta de cores"),
    ("examples_ybr_color.dcm", "OT", "OT", "Imagem YBR"),
    ("SC_rgb_rle_32bit_2frame.dcm", "OT", "OT", "Captura secundária RGB multiframe"),
    ("rtdose.dcm", "RTDOSE", "RTDOSE", "Dose de radioterapia"),
    ("test-SR.dcm", "SR", "SR", "Relatório estruturado"),
    ("waveform_ecg.dcm", "ECG", "ECG", "ECG (onda)"),
]


def pydicom_dir():
    import pydicom
    return Path(pydicom.__file__).parent / "data"


def baixar(url, destino: Path):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r, open(destino, "wb") as f:
        shutil.copyfileobj(r, f)


def main():
    print("=" * 74)
    print("IMAGENS REAIS DE USO LIVRE — pasta Teste de Envio")
    print("=" * 74)

    print("\n[1] Amostras reais do Open Microscopy Environment (domínio público)")
    ok = fail = 0
    for arquivo, tag, mod, desc in OME:
        dest = DESTINO / f"REAL_{tag}_{arquivo}"
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"    já existe: {dest.name}")
            ok += 1
            continue
        try:
            baixar(URL_BASE + arquivo, dest)
            kb = dest.stat().st_size / 1024
            print(f"    baixado: {dest.name} ({kb:.0f} KB) — {mod}: {desc}")
            ok += 1
        except Exception as e:
            print(f"    FALHOU {arquivo}: {e}")
            fail += 1

    print(f"\n[2] Amostras reais que já vêm com o pydicom (MIT)")
    base = pydicom_dir()
    achados = list(base.rglob("*.dcm")) if base.exists() else []
    mapa = {a[0]: a for a in PYDICOM_REAIS}
    for f in achados:
        if f.name in mapa:
            tag, mod, desc = mapa[f.name][1], mapa[f.name][2], mapa[f.name][3]
            dest = DESTINO / f"REAL_{tag}_{f.name}"
            if dest.exists() and dest.stat().st_size > 1000:
                print(f"    já existe: {dest.name}")
                ok += 1
                continue
            shutil.copy2(f, dest)
            print(f"    copiado: {dest.name} ({dest.stat().st_size / 1024:.0f} KB) — {desc}")
            ok += 1
    faltando = set(mapa) - {f.name for f in achados}
    if faltando:
        print(f"    (não encontrados nesta versão do pydicom: {', '.join(sorted(faltando))})")

    print(f"\n[3] Casos de borda / anômalos (fora do manifesto — teste negativo)")
    ESPECIAIS = DESTINO.parent / "casos_especiais"
    ESPECIAIS.mkdir(exist_ok=True)
    especiais = [
        ("MR_truncated.dcm", "Arquivo truncado (pixel data incompleto)"),
        ("no_meta.dcm", "Sem File Meta Information"),
        ("badVR.dcm", "VR inválido no dataset"),
        ("J2K_pixelrep_mismatch.dcm", "JPEG2000 com Pixel Representation divergente"),
        ("examples_jpeg2k.dcm", "Pixel data encapsulada em JPEG2000"),
        ("SC_rgb_jpeg_dcmd.dcm", "Captura secundária comprimida em JPEG"),
        ("JPEG-lossy.dcm", "JPEG com perdas"),
        ("examples_overlay.dcm", "Objeto com overlay"),
        ("MR_small_padded.dcm", "RM com padding"),
    ]
    for f in achados:
        nome = f.name
        if any(nome == e[0] for e in especiais):
            dest = ESPECIAIS / f"ANOM_{nome}"
            if not dest.exists():
                shutil.copy2(f, dest)
                print(f"    copiado: casos_especiais/{dest.name} — "
                      f"{dict(especiais)[nome]}")

    # [4] normaliza arquivos sem File Meta (não são Part 10 válidos)
    print(f"\n[4] Normalizando arquivos sem File Meta Information (Part 10)")
    from pydicom import dcmread
    from pydicom.dataset import FileMetaDataset
    from pydicom.filewriter import dcmwrite
    from pydicom.uid import ImplicitVRLittleEndian

    normalizados = 0
    for f in sorted(DESTINO.glob("*.dcm")):
        try:
            dcmread(str(f))
            continue                      # já está válido
        except Exception:
            pass
        orig = ESPECIAIS / f"ANOM_SEM_META_{f.name}"
        if not orig.exists():
            shutil.copy2(f, orig)
        try:
            ds = dcmread(str(f), force=True)
            if not hasattr(ds, "SOPClassUID"):
                # formato ACR-NEMA 1.0/2.0 (1996/1997), anterior ao Part 10:
                # não tem SOP Class UID — muitos PACS modernos recusam.
                dest = ESPECIAIS / f"ANOM_ACRNEMA_{f.name}"
                if not dest.exists():
                    shutil.move(str(f), str(dest))
                    print(f"    movido: {f.name} → casos_especiais/{dest.name}")
                    print(f"              (ACR-NEMA legado, sem SOP Class UID)")
                continue
            fm = FileMetaDataset()
            fm.MediaStorageSOPClassUID = ds.SOPClassUID
            fm.MediaStorageSOPInstanceUID = getattr(ds, "SOPInstanceUID", None) or \
                generate_uid()
            fm.TransferSyntaxUID = ImplicitVRLittleEndian
            ds.file_meta = fm
            ds.preamble = b"\0" * 128
            dcmwrite(str(f), ds, enforce_file_format=True)
            print(f"    normalizado: {f.name} → Part 10 válido (VR implícito)")
            print(f"    original guardado em: casos_especiais/{orig.name}")
            normalizados += 1
        except Exception as e:
            print(f"    não foi possível normalizar {f.name}: {e}")
    if not normalizados:
        print("    nada a normalizar")

    print(f"\n[RESULTADO] {ok} arquivo(s) em imagens/ · {fail} falha(s) de download")
    print(f"Casos de borda em: {ESPECIAIS}")
    print("\nPróximo passo:  python \"Teste de Envio/montar_manifesto.py\"")


if __name__ == "__main__":
    main()