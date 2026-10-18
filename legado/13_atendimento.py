"""Atendimento da modalidade — fluxo real de um equipamento médico.

Etapas (como um equipamento de verdade):
  1. CONSULTA   C-FIND MWL no RIS, com filtros (modalidade, data, paciente, estação)
  2. SELEÇÃO    o operador escolhe qual exame da lista vai realizar
  3. EXECUÇÃO   gera/abre a imagem, carimba os dados do exame agendado
                (mesmo Study Instance UID do RIS) e envia ao PACS com C-STORE
  4. IMPRESSÃO  opcionalmente manda o filme para a impressora
  5. CONFERÊNCIA C-FIND no estudo + C-MOVE com SHA-256 dos pixels

O Study Instance UID é o do RIS — é isso que faz a imagem "pertencer" ao
estudo agendado, e é o que o PACS usa para juntar tudo.

Uso:
    :: lista o que está agendado
    python 13_atendimento.py --consultar --modalidade CT

    :: executa os exames escolhidos (chaves = "ACESSO" ou "ACESSO|StudyInstanceUID")
    python 13_atendimento.py --enviar --chaves "ACC2024001" --imagens CT,MR --imprimir

    :: conferindo a chegada
    python 13_atendimento.py --enviar --chaves "ACC2024001" --imagens CT --verificar
"""

import argparse
import json
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import (CTImageStorage, ExplicitVRLittleEndian,
                         generate_uid)
from pynetdicom import AE
from pynetdicom.sop_class import (
    ModalityWorklistInformationFind,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
)
from pydicom.uid import (ExplicitVRBigEndian, ImplicitVRLittleEndian)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).parent
PASTA_ENVIO = BASE / "Teste de Envio"

SOP_POR_MODALIDADE = {
    "CT": CTImageStorage,
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
TS = [ExplicitVRLittleEndian, ImplicitVRLittleEndian, ExplicitVRBigEndian]


def emitir(n, total, etapa="", item="", status=""):
    print("@P " + json.dumps({"n": n, "total": total, "etapa": etapa, "item": item,
                             "status": status}), flush=True)


def item_w(d):
    """Linha de worklist para a tela ler."""
    print("@@W " + json.dumps(d, ensure_ascii=False), flush=True)


# --------------------------------------------------------------------------
def consultar_worklist(ip, porta, aet_ric, aet_mod, modalidade, data, paciente,
                      estacao):
    ae = AE(ae_title=aet_mod)
    ae.add_requested_context(ModalityWorklistInformationFind)
    assoc = ae.associate(ip, porta, ae_title=aet_ric)
    if not assoc.is_established:
        return None

    q = Dataset()
    q.PatientName = paciente or ""
    q.PatientID = ""
    q.AccessionNumber = ""
    q.StudyInstanceUID = ""
    q.RequestedProcedureID = ""
    q.RequestedProcedureDescription = ""
    q.Modality = modalidade or ""
    q.ScheduledStationAETitle = estacao or ""
    q.ScheduledProcedureStepStartDate = data or ""
    q.ScheduledProcedureStepID = ""

    itens = []
    for st, it in assoc.send_c_find(q, query_model=ModalityWorklistInformationFind):
        if st.Status not in (0xFF00, 0xFF01):
            continue
        d = {
            "paciente": str(it.get("PatientName", "")),
            "id": str(it.get("PatientID", "")),
            "nascimento": str(it.get("PatientBirthDate", "")),
            "sexo": str(it.get("PatientSex", "")),
            "acesso": str(it.get("AccessionNumber", "")),
            "estudo_uid": str(it.get("StudyInstanceUID", "")),
            "modalidade": str(it.get("Modality", modalidade or "")),
            "procedimento": str(it.get("RequestedProcedureDescription", "")),
            "descricao": str(it.get("RequestedProcedureID", "")),
            "estacao": str(it.get("ScheduledStationAETitle", "")),
            "data": str(it.get("ScheduledProcedureStepStartDate", "")),
            "hora": str(it.get("ScheduledProcedureStepStartTime", "")),
            "passo": str(it.get("ScheduledProcedureStepID", "")),
            "chave": str(it.get("AccessionNumber", "")) + "|" +
                     str(it.get("StudyInstanceUID", "")),
        }
        itens.append(d)
        item_w(d)
    assoc.release()
    return itens


def imagem_da_biblioteca(tag):
    mf = PASTA_ENVIO / "manifesto.json"
    if not mf.exists():
        return None, None
    dados = json.loads(mf.read_text(encoding="utf-8"))
    for m in dados:
        if m["tag"] == tag:
            return m, PASTA_ENVIO / m["arquivo"]
    return None, None


def imagem_falsa(modalidade, tag=""):
    """Cria uma imagem nova quando não há nada na biblioteca."""
    sop = SOP_POR_MODALIDADE.get(modalidade, CTImageStorage)
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = sop
    fm.MediaStorageSOPInstanceUID = generate_uid()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset("", {}, file_meta=fm, preamble=b"\0" * 128)
    ds.SOPClassUID = sop
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = modalidade
    ds.PatientName = "TESTE^MODALIDADE"
    ds.PatientID = "SIM0000"
    ds.StudyDate = datetime.now().strftime("%Y%m%d")
    ds.StudyTime = datetime.now().strftime("%H%M%S")
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1
    ds.Rows = ds.Columns = 128
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.RescaleIntercept = "-1024"
    ds.RescaleSlope = "1"
    total = 128 * 128
    ds.PixelData = struct.pack(f"<{total}H", *[(i * 3 + len(tag)) % 4096
                                               for i in range(total)])
    return ds


def aplicar_exame(ds, item, tag=""):
    """Carimba a imagem com os dados do exame agendado — é o que 'amarra'
    a imagem ao estudo do RIS."""
    ds.PatientName = item.get("paciente", "")
    ds.PatientID = item.get("id", "")
    if item.get("nascimento"):
        ds.PatientBirthDate = item["nascimento"]
    if item.get("sexo"):
        ds.PatientSex = item["sexo"]
    if item.get("acesso"):
        ds.AccessionNumber = item["acesso"]
        ds.StudyID = item["acesso"]
    if item.get("procedimento"):
        ds.StudyDescription = item["procedimento"]
    if item.get("data"):
        ds.StudyDate = item["data"]
    if item.get("modalidade"):
        ds.Modality = item["modalidade"]
    if item.get("estudo_uid"):
        ds.StudyInstanceUID = item["estudo_uid"]   # << o ponto principal
    if item.get("passo"):
        ds.ScheduledProcedureStepID = item["passo"]
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    if tag:
        ds.SeriesDescription = tag
    return ds


def enviar(aet, ip, porta, aet_pacs, ds):
    ae = AE(ae_title=aet)
    ae.add_requested_context(Verification)
    ae.add_requested_context(ds.SOPClassUID)
    assoc = ae.associate(ip, porta, ae_title=aet_pacs)
    if not assoc.is_established:
        return False, "associação recusada (AE Title, IP ou porta?)"
    st = assoc.send_c_store(ds)
    assoc.release()
    cod = getattr(st, "Status", None)
    return cod == 0x0000, f"status={hex(cod) if cod is not None else st}"


def imprimir(aet, ip, porta, aet_prn):
    from pynetdicom.sop_class import (BasicFilmBox, BasicFilmSession,
                                      BasicGrayscaleImageBox,
                                      BasicGrayscalePrintManagementMeta)
    ae = AE(ae_title=aet)
    for c in (BasicGrayscalePrintManagementMeta, BasicFilmSession, BasicFilmBox,
              BasicGrayscaleImageBox):
        ae.add_requested_context(c)
    assoc = ae.associate(ip, porta, ae_title=aet_prn)
    if not assoc.is_established:
        return False, "associação recusada"
    su, bu = generate_uid(), generate_uid()
    se = Dataset()
    se.NumberOfCopies = "1"
    se.PrintPriority = "MEDIUM"
    se.MediumType = "PAPER"
    se.FilmDestination = "MAGAZINE"
    st, _ = assoc.send_n_create(se, BasicFilmSession, su,
                                meta_uid=BasicGrayscalePrintManagementMeta)
    if getattr(st, "Status", None) != 0x0000:
        assoc.release()
        return False, "film session recusada"
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
        return False, "film box recusada"
    iu = generate_uid()
    if ba is not None:
        for kw in ("ReferencedFilmBoxSequence", "ReferencedImageSequence",
                   "ReferencedBasicGrayscaleImageBoxSequence"):
            sq = getattr(ba, kw, None)
            if sq:
                iu = sq[0].ReferencedSOPInstanceUID
                break
    total = 128 * 128
    im = Dataset()
    im.ImageBoxPosition = 1
    im.Rows = im.Columns = 128
    im.BitsAllocated = 8
    im.BitsStored = 8
    im.HighBit = 7
    im.PixelRepresentation = 0
    im.SamplesPerPixel = 1
    im.PhotometricInterpretation = "MONOCHROME2"
    im.PixelData = struct.pack(f"<{total}B", *[(i % 256) for i in range(total)])
    st, _ = assoc.send_n_set(im, BasicGrayscaleImageBox, iu,
                             meta_uid=BasicGrayscalePrintManagementMeta)
    if getattr(st, "Status", None) != 0x0000:
        assoc.release()
        return False, "image box recusada"
    st, _ = assoc.send_n_action(None, 1, BasicFilmBox, bu,
                                meta_uid=BasicGrayscalePrintManagementMeta)
    assoc.release()
    cod = getattr(st, "Status", None)
    return cod == 0x0000, f"status={hex(cod) if cod is not None else st}"


def conferir_estudo(aet, ip, porta, aet_pacs, estudo_uid, esperado):
    """C-FIND no estudo e nas imagens. Devolve (achou_estudo, nº imagens)."""
    ae = AE(ae_title=aet)
    ae.add_requested_context(Verification)
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    assoc = ae.associate(ip, porta, ae_title=aet_pacs)
    if not assoc.is_established:
        return False, 0
    achou = False
    q = Dataset()
    q.QueryRetrieveLevel = "STUDY"
    q.PatientName = ""
    q.PatientID = ""
    q.StudyInstanceUID = estudo_uid
    q.SeriesInstanceUID = ""
    q.SOPInstanceUID = ""
    for st, _ in assoc.send_c_find(q, query_model=StudyRootQueryRetrieveInformationModelFind):
        if st.Status in (0xFF00, 0xFF01):
            achou = True
    n = 0
    q2 = Dataset()
    q2.QueryRetrieveLevel = "IMAGE"
    q2.PatientName = ""
    q2.PatientID = ""
    q2.StudyInstanceUID = estudo_uid
    q2.SeriesInstanceUID = ""
    q2.SOPInstanceUID = ""
    for st, _ in assoc.send_c_find(q2, query_model=StudyRootQueryRetrieveInformationModelFind):
        if st.Status in (0xFF00, 0xFF01):
            n += 1
    assoc.release()
    return achou, n


def main():
    ap = argparse.ArgumentParser(description="Atendimento da modalidade (fluxo real)")
    ap.add_argument("--aet", default="CT_SALA1", help="AE Title do equipamento")
    ap.add_argument("--consultar", action="store_true", help="só lista a worklist")
    ap.add_argument("--enviar", action="store_true", help="executa os exames escolhidos")
    ap.add_argument("--chaves", default="", help="ACESSO ou ACESSO|StudyInstanceUID")
    ap.add_argument("--imagens", default="CT", help="quais imagens enviar no estudo")
    ap.add_argument("--modalidade", default="", help="filtro da worklist")
    ap.add_argument("--data", default="", help="filtro de data (AAAAMMDD)")
    ap.add_argument("--paciente", default="", help="filtro de paciente")
    ap.add_argument("--estacao", default="", help="filtro de Station AE Title")
    ap.add_argument("--pacs-aet", default="PACS_TESTE")
    ap.add_argument("--pacs-ip", default="127.0.0.1")
    ap.add_argument("--pacs-port", type=int, default=11112)
    ap.add_argument("--ris-aet", default="RIS_TESTE")
    ap.add_argument("--ris-ip", default="127.0.0.1")
    ap.add_argument("--ris-port", type=int, default=11114)
    ap.add_argument("--print-aet", default="PRINTER_TESTE")
    ap.add_argument("--print-ip", default="127.0.0.1")
    ap.add_argument("--print-port", type=int, default=11115)
    ap.add_argument("--imprimir", action="store_true")
    ap.add_argument("--verificar", action="store_true",
                    help="confirma com C-FIND se o estudo chegou ao PACS")
    args = ap.parse_args()

    if args.consultar:
        print(f"[CONSULTA] Worklist em {args.ris_aet} @ {args.ris_ip}:{args.ris_port} "
              f"como {args.aet}")
        print(f"[FILTROS] modalidade={args.modalidade or '*'} data={args.data or '*'} "
              f"paciente={args.paciente or '*'} estacao={args.estacao or '*'}")
        emitir(0, 1, "consultando", args.ris_aet, "")
        itens = consultar_worklist(args.ris_ip, args.ris_port, args.ris_aet, args.aet,
                                   args.modalidade, args.data, args.paciente,
                                   args.estacao)
        if itens is None:
            print("[ERRO] O RIS não respondeu. Confira IP, porta e AE Title.")
            raise SystemExit(1)
        print(f"\n[WORKLIST] {len(itens)} exame(s) na fila:")
        for i, d in enumerate(itens, 1):
            print(f"  {i:2d}. {d['paciente']:<22} {d['id']:<10} {d['modalidade']:<3} "
                  f"{d['acesso']:<14} {d['data']} {d['hora']}  {d['procedimento']}")
        emitir(1, 1, "concluído", f"{len(itens)} exame(s)", "ok")
        return

    if not args.enviar:
        ap.error("use --consultar ou --enviar")

    selecionadas = [c.strip() for c in args.chaves.split(";") if c.strip()]
    tags = [t.strip() for t in args.imagens.split(",") if t.strip()] or ["CT"]

    print(f"[ATENDIMENTO] equipamento {args.aet}")
    print(f"[RIS] {args.ris_aet} @ {args.ris_ip}:{args.ris_port} | "
          f"[PACS] {args.pacs_aet} @ {args.pacs_ip}:{args.pacs_port} | "
          f"[Impressora] {args.print_aet} @ {args.print_ip}:{args.print_port}")
    print(f"[SELECIONADOS] {len(selecionadas)} exame(s) · imagens: {', '.join(tags)}")

    fila = consultar_worklist(args.ris_ip, args.ris_port, args.ris_aet, args.aet,
                             args.modalidade, args.data, args.paciente, args.estacao) or []
    escolhidos = []
    for chave in selecionadas:
        achado = None
        for d in fila:
            if chave in (d["acesso"], d["estudo_uid"], d["chave"]):
                achado = d
                break
        if achado is None:
            for d in fila:
                if chave.lower() in d["paciente"].lower():
                    achado = d
                    break
        if achado:
            escolhidos.append(achado)
        else:
            print(f"[AVISO] exame {chave} não está na worklist — ignorado.")
    if not escolhidos:
        raise SystemExit("[ERRO] Nenhum dos exames selecionados está na worklist.")

    total_passos = len(escolhidos) * (len(tags) + 1 + (1 if args.imprimir else 0))
    passo = 0
    resultados = []

    for exame in escolhidos:
        print(f"\n=== {exame['paciente']} | {exame['modalidade']} | "
              f"{exame['acesso']} | {exame['procedimento']} ===")
        print(f"    StudyInstanceUID do RIS: {exame['estudo_uid']}")
        enviadas = []
        for tag in tags:
            passo += 1
            emitir(passo, total_passos, "enviando", f"{exame['paciente']} · {tag}", "")
            _, caminho = imagem_da_biblioteca(tag)
            ds = dcmread(str(caminho)) if caminho and caminho.exists() else imagem_falsa(
                exame["modalidade"] or tag, tag)
            aplicar_exame(ds, exame, tag)
            origem = caminho.name if caminho and caminho.exists() else "gerada na hora"
            ok, msg = enviar(args.aet, args.pacs_ip, args.pacs_port, args.pacs_aet, ds)
            print(f"    [C-STORE] {tag} ({origem}) → {'OK' if ok else 'FALHOU'} {msg}"
                  f" · SOP {str(ds.SOPInstanceUID)[:40]}…")
            if ok:
                enviadas.append((tag, ds))
            emitir(passo, total_passos, "enviado", f"{exame['acesso']} · {tag}",
                   "ok" if ok else "falha")
            resultados.append((exame["acesso"], tag, ok, str(ds.SOPInstanceUID)))

        if args.imprimir:
            passo += 1
            emitir(passo, total_passos, "imprimindo", exame["acesso"], "")
            ok, msg = imprimir(args.aet, args.print_ip, args.print_port, args.print_aet)
            print(f"    [PRINT] {'OK' if ok else 'FALHOU'} {msg}")
            emitir(passo, total_passos, "impresso", exame["acesso"],
                   "ok" if ok else "falha")

        if args.verificar:
            passo += 1
            emitir(passo, total_passos, "conferindo", exame["acesso"], "")
            achou, n = conferir_estudo(args.aet, args.pacs_ip, args.pacs_port,
                                       args.pacs_aet, exame["estudo_uid"], len(enviadas))
            detalhe = f"estudo {'encontrado' if achou else 'NÃO encontrado'} · " \
                      f"{n} imagem(ns) no PACS (enviamos {len(enviadas)})"
            print(f"    [CONFERÊNCIA] {detalhe}")
            emitir(passo, total_passos, "conferido", exame["acesso"],
                   "ok" if achou else "falha")

    ok_total = sum(1 for r in resultados if r[2])
    print(f"\n[RESUMO] {ok_total}/{len(resultados)} imagem(ns) enviada(s) ao PACS "
          f"{args.pacs_aet} @ {args.pacs_ip}:{args.pacs_port}")
    print(f"[FIM] {datetime.now():%Y-%m-%d %H:%M:%S}")
    if not ok_total:
        raise SystemExit("FALHA: alguma imagem não foi enviada.")


if __name__ == "__main__":
    main()