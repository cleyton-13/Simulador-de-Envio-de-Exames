"""Simulador de equipamento medico (MODALIDADE).

Faz o que uma modalidade real faz, passo a passo:
  1. C-FIND MWL no RIS  -> busca a lista de exames agendados
  2. C-STORE no PACS    -> envia a imagem de cada exame
  3. Impressao          -> manda o filme para a impressora

Repete em N ciclos, como se o tecnico fosse haciendo os exames em sequencia.

Uso (tudo opcional, o que faltar e apenas ignorado):
    python 12_simulador_modalidade.py
    python 12_simulador_modalidade.py --modalidade MR --ciclos 3
    python 12_simulador_modalidade.py --sem-worklist --sem-print
    python 12_simulador_modalidade.py --pacs-aet PACS_REAL --pacs-ip 192.168.1.50 --pacs-port 104
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.sop_class import ModalityWorklistInformationFind

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
PASTA_ENVIO = BASE / "Teste de Envio"


def emitir(n, total, etapa="", item="", status=""):
    print("@P " + json.dumps({"n": n, "total": total, "etapa": etapa,
                             "item": item, "status": status}), flush=True)


def nova_ae(aet, com_find=True):
    ae = AE(ae_title=aet)
    if com_find:
        ae.add_requested_context(ModalityWorklistInformationFind)
    return ae


def consultar_worklist(ip, porta, aet_ric, aet_mod, modalidade):
    """C-FIND MWL. Devolve lista de dicts (ou [] se nao houver RIS)."""
    ae = nova_ae(aet_mod)
    assoc = ae.associate(ip, porta, ae_title=aet_ric)
    if not assoc.is_established:
        print(f"[AVISO] RIS {aet_ric} @ {ip}:{porta} nao respondeu — seguindo sem worklist.")
        return None

    q = Dataset()
    for k in ("PatientName", "PatientID", "AccessionNumber", "StudyInstanceUID",
              "RequestedProcedureID", "RequestedProcedureDescription",
              "ScheduledStationAETitle", "ScheduledProcedureStepStartDate",
              "ScheduledProcedureStepID"):
        setattr(q, k, "")
    q.Modality = modalidade or ""

    itens = []
    for st, it in assoc.send_c_find(q, query_model=ModalityWorklistInformationFind):
        if st.Status in (0xFF00, 0xFF01):
            itens.append({
                "patient": str(it.get("PatientName", "")),
                "id": str(it.get("PatientID", "")),
                "acesso": str(it.get("AccessionNumber", "")),
                "exame": str(it.get("RequestedProcedureDescription", "")),
                "study": str(it.get("StudyInstanceUID", "")),
                "modalidade": str(it.get("Modality", modalidade)),
            })
    assoc.release()
    return itens


def escolher_imagem(modalidade):
    """Acha uma imagem da pasta de teste que sirva para a modalidade."""
    mf = PASTA_ENVIO / "manifesto.json"
    if not mf.exists():
        return None, None
    dados = json.loads(mf.read_text(encoding="utf-8"))
    for m in dados:
        if m["modality"] == modalidade:
            return m, PASTA_ENVIO / m["arquivo"]
    return dados[0], PASTA_ENVIO / dados[0]["arquivo"]


def enviar_pacs(aet_mod, ip, porta, aet_pacs, ds, sobrescrever_study=None):
    """C-STORE de 1 imagem. Devolve (ok, mensagem).

    IMPORTANTE: a associacao precisa incluir o contexto Verification (1.2.840.10008.1.1)
    alem do SOP da imagem — muitos PACS recusam a associacao sem ele.
    """
    from pynetdicom.sop_class import Verification
    ae = nova_ae(aet_mod, com_find=False)
    ae.add_requested_context(Verification)
    ae.add_requested_context(ds.SOPClassUID)
    assoc = ae.associate(ip, porta, ae_title=aet_pacs)
    if not assoc.is_established:
        return False, "associacao negada (faltou Verification ou AET/porta?)"
    if sobrescrever_study:
        ds.StudyInstanceUID = sobrescrever_study
    st = assoc.send_c_store(ds)
    assoc.release()
    cod = getattr(st, "Status", None)
    return cod == 0x0000, f"status={hex(cod) if cod is not None else st}"


def imprimir(aet_mod, ip, porta, aet_prn):
    """Fluxo de filme: N-CREATE session/box, N-SET pixels, N-ACTION imprimir."""
    import struct
    from pydicom.uid import generate_uid
    from pynetdicom.sop_class import (
        BasicFilmBox, BasicFilmSession, BasicGrayscaleImageBox,
        BasicGrayscalePrintManagementMeta,
    )
    ae = nova_ae(aet_mod, com_find=False)
    for c in (BasicGrayscalePrintManagementMeta, BasicFilmSession, BasicFilmBox,
              BasicGrayscaleImageBox):
        ae.add_requested_context(c)
    assoc = ae.associate(ip, porta, ae_title=aet_prn)
    if not assoc.is_established:
        return False, "associacao negada"

    su = generate_uid()
    se = Dataset()
    se.NumberOfCopies = "1"
    se.PrintPriority = "MEDIUM"
    se.MediumType = "PAPER"
    se.FilmDestination = "MAGAZINE"
    st, _ = assoc.send_n_create(se, BasicFilmSession, su,
                                meta_uid=BasicGrayscalePrintManagementMeta)
    if getattr(st, "Status", None) != 0x0000:
        assoc.release()
        return False, f"film session {hex(getattr(st, 'Status', 0) or 0)}"

    bu = generate_uid()
    bx = Dataset()
    bx.ImageDisplayFormat = "STANDARD\\1,1"
    bx.FilmOrientation = "PORTRAIT"
    bx.FilmSizeID = "8INX10IN"
    bx.MagnificationType = "REPLICATE"
    rf = Dataset()
    rf.ReferencedSOPClassUID = BasicFilmSession
    rf.ReferencedSOPInstanceUID = su
    bx.ReferencedFilmSessionSequence = [rf]
    st, ba = assoc.send_n_create(bx, BasicFilmBox, bu,
                                 meta_uid=BasicGrayscalePrintManagementMeta)
    if getattr(st, "Status", None) != 0x0000:
        assoc.release()
        return False, f"film box {hex(getattr(st, 'Status', 0) or 0)}"

    iu = generate_uid()
    if ba is not None:
        for kw in ("ReferencedFilmBoxSequence", "ReferencedImageSequence",
                   "ReferencedBasicGrayscaleImageBoxSequence"):
            sq = getattr(ba, kw, None)
            if sq:
                iu = sq[0].ReferencedSOPInstanceUID
                break

    tot = 128 * 128
    im = Dataset()
    im.ImageBoxPosition = 1
    im.Rows = 128
    im.Columns = 128
    im.BitsAllocated = 8
    im.BitsStored = 8
    im.HighBit = 7
    im.PixelRepresentation = 0
    im.SamplesPerPixel = 1
    im.PhotometricInterpretation = "MONOCHROME2"
    im.PixelData = struct.pack(f"<{tot}B", *[(i % 256) for i in range(tot)])
    st, _ = assoc.send_n_set(im, BasicGrayscaleImageBox, iu,
                             meta_uid=BasicGrayscalePrintManagementMeta)
    if getattr(st, "Status", None) != 0x0000:
        assoc.release()
        return False, f"image box {hex(getattr(st, 'Status', 0) or 0)}"

    st, _ = assoc.send_n_action(None, 1, BasicFilmBox, bu,
                                meta_uid=BasicGrayscalePrintManagementMeta)
    assoc.release()
    cod = getattr(st, "Status", None)
    return cod == 0x0000, f"status={hex(cod) if cod is not None else st}"


def main():
    ap = argparse.ArgumentParser(description="Simulador de equipamento medico (modalidade)")
    ap.add_argument("--aet", default="MODALIDADE1", help="Calling AE Title desta modalidade")
    ap.add_argument("--modalidade", default="CT", help="CT, MR, CR, DX, US, XA, MG, RF, PT, OT")
    ap.add_argument("--ciclos", type=int, default=1, help="quantos exames simula")
    ap.add_argument("--pacs-aet", default="PACS_TESTE")
    ap.add_argument("--pacs-ip", default="127.0.0.1")
    ap.add_argument("--pacs-port", type=int, default=11112)
    ap.add_argument("--ris-aet", default="RIS_TESTE")
    ap.add_argument("--ris-ip", default="127.0.0.1")
    ap.add_argument("--ris-port", type=int, default=11114)
    ap.add_argument("--print-aet", default="PRINTER_TESTE")
    ap.add_argument("--print-ip", default="127.0.0.1")
    ap.add_argument("--print-port", type=int, default=11115)
    ap.add_argument("--sem-worklist", action="store_true")
    ap.add_argument("--sem-print", action="store_true")
    args = ap.parse_args()

    print(f"[MODALIDADE] {args.aet} · modalidade {args.modalidade} · {args.ciclos} ciclo(s)")
    print(f"[DESTINOS] PACS {args.pacs_aet} @ {args.pacs_ip}:{args.pacs_port} | "
          f"RIS {args.ris_aet} @ {args.ris_ip}:{args.ris_port} | "
          f"Impressora {args.print_aet} @ {args.print_ip}:{args.print_port}")

    item_img, caminho = escolher_imagem(args.modalidade)
    if not caminho or not caminho.exists():
        raise SystemExit("[ERRO] Sem imagens de teste. Rode: "
                         "python \"Teste de Envio\\gerar_imagens_teste.py\"")
    print(f"[IMAGEM] usando {caminho.name} (SOP {item_img['sop_classe_nome']})")

    # ---------- passo 1: worklist ----------
    agenda = []
    if not args.sem_worklist:
        emitir(0, args.ciclos, "worklist", args.ris_aet, "consultando")
        r = consultar_worklist(args.ris_ip, args.ris_port, args.ris_aet, args.aet,
                               args.modalidade)
        if r:
            agenda = r
            print(f"[WORKLIST] {len(agenda)} exame(s) agendado(s):")
            for i in agenda:
                print(f"          {i['patient']} | {i['acesso']} | {i['exame']} "
                      f"| {i['modalidade']}")
        else:
            agenda = [{"patient": "TESTE^MODALIDADE", "id": "SIM0001", "acesso": "SIMACC1",
                       "exame": f"Simulado {args.modalidade}", "study": "",
                       "modalidade": args.modalidade}]
            print("[WORKLIST] usando exame simulado (RIS nao respondeu).")

    # ---------- passo 2 e 3: enviar e imprimir ----------
    if not agenda:
        agenda = [{"patient": "TESTE^MODALIDADE", "id": "SIM0001",
                   "acesso": "SIMACC1", "exame": f"Simulado {args.modalidade}",
                   "study": "", "modalidade": args.modalidade}]
        print("[WORKLIST] usando exame simulado.")

    resumo = []
    total = max(args.ciclos, 1)
    for i in range(args.ciclos):
        item = agenda[i % len(agenda)]
        print(f"\n--- exame {i + 1}/{total}: {item['patient']} ({item['acesso']}) ---")
        emitir(i, total, "enviando", item["patient"], "C-STORE")
        ds = dcmread(str(caminho))
        ds.PatientName = item["patient"]
        ds.PatientID = item["id"]
        ds.AccessionNumber = item["acesso"]
        ds.StudyDescription = item["exame"]
        if item["study"]:
            ds.StudyInstanceUID = item["study"]
        ok_p, msg_p = enviar_pacs(args.aet, args.pacs_ip, args.pacs_port,
                                  args.pacs_aet, ds)
        print(f"[C-STORE] {'OK' if ok_p else 'FALHOU'} — {msg_p}")

        ok_i, msg_i = True, "pulada"
        if not args.sem_print:
            emitir(i + 0.4, total, "imprimindo", item["patient"], "PRINT")
            ok_i, msg_i = imprimir(args.aet, args.print_ip, args.print_port,
                                   args.print_aet)
            print(f"[PRINT]   {'OK' if ok_i else 'FALHOU'} — {msg_i}")
        emitir(i + 1, total, "concluído", item["patient"],
               "ok" if ok_p else "falha")
        resumo.append((item, ok_p, ok_i))

    tudo_ok = all(r[1] for r in resumo) if resumo else False
    print(f"\n[RESUMO] {sum(1 for r in resumo if r[1])}/{len(resumo)} exame(s) "
          f"enviado(s) para {args.pacs_aet} @ {args.pacs_ip}:{args.pacs_port}")
    print(f"[FIM] {datetime.now():%Y-%m-%d %H:%M:%S}")
    if resumo and not tudo_ok:
        raise SystemExit("FALHA: algum exame não foi enviado ao PACS")


if __name__ == "__main__":
    main()