"""Baixa imagens DICOM REAIS e anonimizadas do TCIA (The Cancer Imaging Archive).

Uma imagem por série, escolhida de coleções e fabricantes diferentes, só com
licença livre (CC BY / CC0). As imagens vão para `imagens_tcia/<MODALIDADE>/` e
NÃO são versionadas no git: o que vale é `fontes_tcia.json`, que registra de onde
veio cada arquivo (coleção, UIDs, licença, DOI) e permite baixar de novo igual.

    python baixar_imagens.py                    # 10 por modalidade (padrão)
    python baixar_imagens.py --por-modalidade 15 --modalidades XA,RF
    python baixar_imagens.py --so-fontes        # só escolhe e grava fontes_tcia.json
    python baixar_imagens.py --refazer          # ignora fontes_tcia.json e escolhe de novo

Se `fontes_tcia.json` existe, ele é a lista oficial: baixa exatamente aquelas imagens.
Atribuição: cada coleção tem seus créditos em fontes_tcia.json (campo `doi`) e em
CREDITAOS.md. As licenças CC BY exigem citar a coleção ao divulgar resultados.
"""
import argparse
import hashlib
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
DESTINO = BASE / "imagens_tcia"
FONTES = BASE / "fontes_tcia.json"
API = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
MODALIDADES = ["CT", "MR", "CR", "DX", "US", "XA", "MG", "RF", "PT", "NM", "OT"]

# Coleções que NÃO são imagem real de paciente (simuladas/sintéticas) ou que
# são gigantes demais para servir de amostra.
EXCLUIR_COLECAO = ("MIDI-B", "VICTRE", "Synthetic", "Breast-Cancer-Screening-DBT")
LIMITE_MB = {"default": 9.0, "MG": 25.0, "DX": 14.0, "CR": 14.0, "RF": 30.0, "XA": 14.0}


def get_json(rota, **params):
    url = f"{API}/{rota}?" + urllib.parse.urlencode(params)
    for tentativa in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dicomsim/0.1"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if tentativa == 3:
                raise
            time.sleep(2 * (tentativa + 1))


def licenca_livre(nome):
    n = (nome or "").lower()
    if "noncommercial" in n or "non-commercial" in n or "nc" in n.split():
        return False
    return "creative commons attribution" in n or "creative commons zero" in n or "cc0" in n


def escolher(mod, quantos, semente=7):
    """Seleciona séries diversas (coleção x fabricante) para a modalidade."""
    series = get_json("getSeries", Modality=mod)
    limite = LIMITE_MB.get(mod, LIMITE_MB["default"]) * 1024 * 1024
    boas = []
    for s in series:
        if any(x in s["Collection"] for x in EXCLUIR_COLECAO):
            continue
        if not licenca_livre(s.get("LicenseName")):
            continue
        n = max(int(s.get("ImageCount") or 1), 1)
        if (s.get("FileSize") or 0) / n > limite:
            continue
        boas.append(s)
    grupos = {}
    for s in boas:
        grupos.setdefault((s["Collection"], s.get("Manufacturer") or "?",
                           s.get("ManufacturerModelName") or "?"), []).append(s)
    rnd = random.Random(semente)
    for g in grupos.values():
        rnd.shuffle(g)
    # rodízio entre grupos: máxima variedade de origem
    chaves = sorted(grupos)
    rnd.shuffle(chaves)          # ordem aleatória (fixa pela semente): varia as coleções
    escolhidas = []
    while len(escolhidas) < quantos and any(grupos.values()):
        for k in chaves:
            if grupos[k] and len(escolhidas) < quantos:
                escolhidas.append(grupos[k].pop())
    return escolhidas, len(boas)


def ficha(s, sop):
    return {
        "modalidade": s["Modality"], "colecao": s["Collection"],
        "fabricante": s.get("Manufacturer"), "modelo": s.get("ManufacturerModelName"),
        "descricao": s.get("SeriesDescription"), "series_uid": s["SeriesInstanceUID"],
        "sop_uid": sop, "licenca": s.get("LicenseName"), "licenca_url": s.get("LicenseURI"),
        "doi": s.get("CollectionURI"),
    }


def montar_fontes(modalidades, quantos):
    fontes = []
    for mod in modalidades:
        esc, disponiveis = escolher(mod, quantos)
        print(f"[{mod}] {disponiveis} séries elegíveis → {len(esc)} escolhidas")
        for s in esc:
            sops = get_json("getSOPInstanceUIDs", SeriesInstanceUID=s["SeriesInstanceUID"])
            uids = [x["SOPInstanceUID"] if isinstance(x, dict) else x for x in sops]
            if not uids:
                continue
            fontes.append(ficha(s, uids[len(uids) // 2]))   # imagem do meio da série
        time.sleep(0.3)
    return fontes


def caminho(f):
    return DESTINO / f["modalidade"] / f"TCIA_{f['modalidade']}_{f['colecao']}_{f['sop_uid'][-12:]}.dcm".replace(" ", "_")


def baixar(f):
    dest = caminho(f)
    if dest.exists() and dest.stat().st_size > 0:
        return "ja_existia"
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{API}/getSingleImage?" + urllib.parse.urlencode(
        {"SeriesInstanceUID": f["series_uid"], "SOPInstanceUID": f["sop_uid"]})
    for tentativa in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dicomsim/0.1"})
            with urllib.request.urlopen(req, timeout=300) as r:
                dado = r.read()
            if dado[128:132] != b"DICM":
                raise ValueError("resposta não é um DICOM Part 10")
            dest.write_bytes(dado)
            return "baixada"
        except Exception as e:
            if tentativa == 2:
                return f"erro: {e}"
            time.sleep(3)


def conferir(f):
    """Abre o arquivo e preenche os dados técnicos na ficha."""
    from pydicom import dcmread
    p = caminho(f)
    try:
        ds = dcmread(str(p))
    except Exception as e:
        return f"ilegivel: {e}"
    f["arquivo"] = str(p.relative_to(BASE)).replace("\\", "/")
    f["bytes"] = p.stat().st_size
    f["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    f["sop_class_uid"] = str(ds.SOPClassUID)
    f["transfer_syntax"] = str(ds.file_meta.TransferSyntaxUID)
    f["modality_dicom"] = str(ds.get("Modality", ""))
    f["linhas"], f["colunas"] = ds.get("Rows"), ds.get("Columns")
    f["quadros"] = int(ds.get("NumberOfFrames", 1) or 1)
    f["tem_pixels"] = "PixelData" in ds
    f["paciente_anonimo"] = str(ds.get("PatientName", ""))
    return "ok"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--por-modalidade", type=int, default=10)
    ap.add_argument("--modalidades", default=",".join(MODALIDADES))
    ap.add_argument("--so-fontes", action="store_true")
    ap.add_argument("--refazer", action="store_true")
    a = ap.parse_args()
    mods = [m.strip().upper() for m in a.modalidades.split(",") if m.strip()]

    if FONTES.exists() and not a.refazer:
        fontes = json.loads(FONTES.read_text(encoding="utf-8"))
        faltam = [m for m in mods if sum(1 for f in fontes if f["modalidade"] == m) < a.por_modalidade]
        if faltam:
            print(f"fontes_tcia.json tem menos de {a.por_modalidade} para: {', '.join(faltam)} — completando")
            novas = montar_fontes(faltam, a.por_modalidade)
            ja = {f["sop_uid"] for f in fontes}
            fontes += [f for f in novas if f["sop_uid"] not in ja]
    else:
        fontes = montar_fontes(mods, a.por_modalidade)
    FONTES.write_text(json.dumps(fontes, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.so_fontes:
        print(f"{len(fontes)} fontes gravadas em {FONTES.name}")
        return

    alvo = [f for f in fontes if f["modalidade"] in mods]
    ok = err = 0
    for i, f in enumerate(alvo, 1):
        r = baixar(f)
        if r.startswith("erro"):
            err += 1
            print(f"  [{i}/{len(alvo)}] {f['modalidade']} {f['colecao']}: {r}")
            continue
        c = conferir(f)
        ok += c == "ok"
        print(f"  [{i}/{len(alvo)}] {f['modalidade']:3} {f['colecao'][:28]:28} {r:10} {c}")
    FONTES.write_text(json.dumps(fontes, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nconcluído: {ok} ok, {err} com erro, de {len(alvo)}")


if __name__ == "__main__":
    main()
