"""Cliente de teste (SCU) — simula a MODALIDADE.

Testa um PACS / equipamento real que esteja no papel de SCP:
- echo : C-ECHO  (conectividade / Verification SOP 1.2.840.10008.1.1)
- store: C-STORE (envia um .dcm real para o PACS)
- find : C-FIND  (consulta Study Root por PatientName / StudyDate)
- move : C-MOVE  (pede ao PACS para enviar estudos para um destino)
- mwl  : C-FIND MWL (1.2.840.10008.5.1.4.31, pergunta exames agendados ao RIS)
- print: N-CREATE/N-SET/N-ACTION (impressao Basic Grayscale 1.2.840.10008.5.1.1.9)

Uso tipico (2 terminais):
    Terminal 1: python 01_scp_pacs.py
    Terminal 2: python 02_scu_teste.py --teste echo
                python 02_scu_teste.py --teste store --arquivo teste_CT.dcm
                python 02_scu_teste.py --teste find --patient-name "TESTE*"

Contra equipamento real:
    python 02_scu_teste.py --teste echo --ip 192.168.1.50 --port 104 --aet PACS_REAL
    python 02_scu_teste.py --teste store --ip 192.168.1.50 --port 104 --aet PACS_REAL --arquivo teste_CT.dcm
"""

import sys
import argparse
import json
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.presentation import (
    StoragePresentationContexts,
    VerificationPresentationContexts,
)
from pynetdicom.sop_class import (
    BasicFilmBox,
    BasicFilmSession,
    BasicGrayscaleImageBox,
    BasicGrayscalePrintManagementMeta,
    ModalityWorklistInformationFind,
    Printer,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
)

BASE_DIR = Path(__file__).parent


def load_config():
    cfg_path = BASE_DIR / "config.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {}


def build_ae(my_aet: str, teste: str = "", arquivo: str = "") -> AE:
    """Monta a AE pedindo SO os contextos do teste (PACS real pode
    rejeitar associacao com 128 contextos; e fica claro no log o que
    cada teste negociou)."""
    ae = AE(ae_title=my_aet)
    if teste == "echo":
        ae.add_requested_context(Verification)
    elif teste == "store":
        # pede so o SOP da imagem + Verification (ex: CT Image Storage)
        sop = None
        try:
            fp = Path(arquivo)
            if not fp.exists():
                fp = BASE_DIR / arquivo
            sop = dcmread(str(fp), stop_before_pixels=True).SOPClassUID
        except Exception:
            pass
        if sop:
            ae.add_requested_context(Verification)
            ae.add_requested_context(sop)
        else:  # fallback: todos os Storage
            ae.add_requested_context(Verification)
            for ctx in StoragePresentationContexts:
                ae.add_requested_context(ctx.abstract_syntax, ctx.transfer_syntax)
    elif teste == "find":
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    elif teste == "move":
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
    elif teste == "mwl":
        ae.add_requested_context(ModalityWorklistInformationFind)
    elif teste == "print":
        ae.add_requested_context(BasicGrayscalePrintManagementMeta)
        ae.add_requested_context(BasicFilmSession)
        ae.add_requested_context(BasicFilmBox)
        ae.add_requested_context(BasicGrayscaleImageBox)
        ae.add_requested_context(Printer)
    else:  # compat: todos (uso local)
        ae.add_requested_context(Verification)
        for ctx in StoragePresentationContexts[:100]:
            ae.add_requested_context(ctx.abstract_syntax, ctx.transfer_syntax)
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    return ae


def test_echo(ae, ip, port, remote_aet):
    assoc = ae.associate(ip, port, ae_title=remote_aet)
    if not assoc.is_established:
        print("[C-ECHO] FALHA na associação (confira IP, porta, AE Title e firewall).")
        return False
    status = assoc.send_c_echo()
    assoc.release()
    if status and status.Status == 0x0000:
        print(f"[C-ECHO] SUCESSO contra {remote_aet}@{ip}:{port} (0x0000).")
        return True
    print(f"[C-ECHO] Resposta inesperada: {status}.")
    return False


def test_store(ae, ip, port, remote_aet, arquivo):
    fpath = Path(arquivo)
    if not fpath.exists():
        # tenta achar na pasta do projeto
        fpath = BASE_DIR / arquivo
    if not fpath.exists():
        print(f"[C-STORE] Arquivo não encontrado: {arquivo}")
        print("Gere um com: python 03_gerar_imagem.py")
        return False
    ds = dcmread(str(fpath))
    assoc = ae.associate(ip, port, ae_title=remote_aet)
    if not assoc.is_established:
        print("[C-STORE] FALHA na associação.")
        return False
    print(f"[C-STORE] Enviando {fpath.name} ({ds.SOPInstanceUID}) ...")
    status = assoc.send_c_store(ds)
    assoc.release()
    code = getattr(status, "Status", None)
    print(f"[C-STORE] Status retornado: {hex(code) if code is not None else status}")
    if code == 0x0000:
        print("[C-STORE] SUCESSO.")
        return True
    print("[C-STORE] Falha / warning — ver log do PACS.")
    return False


def test_find(ae, ip, port, remote_aet, patient_name="*", study_date=""):
    ds = Dataset()
    ds.QueryRetrieveLevel = "STUDY"
    ds.PatientName = patient_name
    ds.PatientID = ""
    ds.StudyInstanceUID = ""
    ds.SeriesInstanceUID = ""
    ds.SOPInstanceUID = ""
    ds.StudyDate = study_date
    ds.Modality = ""
    ds.StudyDescription = ""

    assoc = ae.associate(ip, port, ae_title=remote_aet)
    if not assoc.is_established:
        print("[C-FIND] FALHA na associação.")
        return False
    print(f"[C-FIND] QueryRetrieveLevel=STUDY PatientName={patient_name}")
    n = 0
    for status, identifier in assoc.send_c_find(
        ds, query_model=StudyRootQueryRetrieveInformationModelFind
    ):
        if status.Status in (0xFF00, 0xFF01):
            n += 1
            print(
                f"  -> {identifier.PatientName} | {identifier.PatientID} | "
                f"{identifier.StudyInstanceUID} | {identifier.Modality}"
            )
        elif status.Status == 0x0000:
            print(f"[C-FIND] Fim. {n} estudo(s) encontrado(s).")
    assoc.release()
    return True


def test_move(ae, ip, port, remote_aet, dest_aet, study_uid=""):
    ds = Dataset()
    ds.QueryRetrieveLevel = "STUDY"
    ds.StudyInstanceUID = study_uid
    ds.PatientID = ""
    assoc = ae.associate(ip, port, ae_title=remote_aet)
    if not assoc.is_established:
        print("[C-MOVE] FALHA na associação.")
        return False
    print(f"[C-MOVE] Pedindo o estudo {study_uid or '*'} para o destino {dest_aet} ...")
    print("OBS: o PACS abre uma NOVA conexão de volta para o destino (porta do C-MOVE).")
    for status, identifier in assoc.send_c_move(
        ds, dest_aet, query_model=StudyRootQueryRetrieveInformationModelMove
    ):
        print(f"  status={hex(status.Status)} remaining={getattr(status, 'NumberOfRemainingSuboperations', '?')}")
    assoc.release()
    return True


def test_mwl(ae, ip, port, remote_aet, modality="", patient_name="",
             station_aet="", start_date=""):
    """C-FIND MWL: pergunta ao RIS quais exames agendados."""
    ds = Dataset()
    ds.PatientName = patient_name or ""
    ds.PatientID = ""
    ds.AccessionNumber = ""
    ds.StudyInstanceUID = ""
    ds.RequestedProcedureID = ""
    ds.RequestedProcedureDescription = ""
    ds.Modality = modality or ""
    ds.ScheduledStationAETitle = station_aet or ""
    ds.ScheduledProcedureStepStartDate = start_date or ""
    ds.ScheduledProcedureStepID = ""

    assoc = ae.associate(ip, port, ae_title=remote_aet)
    if not assoc.is_established:
        print("[MWL] FALHA na associação (confira IP, porta e AE Title do RIS).")
        return False
    print(f"[MWL C-FIND] Modality={modality or '*'} Patient={patient_name or '*'} "
          f"Date={start_date or '*'} contra {remote_aet}@{ip}:{port}")
    n = 0
    for status, item in assoc.send_c_find(
        ds, query_model=ModalityWorklistInformationFind
    ):
        if status.Status in (0xFF00, 0xFF01):
            n += 1
            print(
                f"  -> {item.PatientName} | {item.PatientID} | "
                f"{item.AccessionNumber} | {item.Modality} | "
                f"{getattr(item, 'RequestedProcedureDescription', '')} | "
                f"{getattr(item, 'ScheduledProcedureStepStartDate', '')}"
            )
        elif status.Status == 0x0000:
            print(f"[MWL] Fim. {n} agendamento(s).")
    assoc.release()
    if n == 0:
        print("[MWL] Zero resultados — tente sem filtro ou confira worklist.json no RIS.")
    return True


def test_print(ae, ip, port, remote_aet):
    """Fluxo Print Grayscale: N-CREATE session/box, N-SET image, N-ACTION print."""
    import struct
    from pydicom.uid import generate_uid

    assoc = ae.associate(ip, port, ae_title=remote_aet)
    if not assoc.is_established:
        print("[PRINT] FALHA na associação (confira IP, porta e AE Title da impressora).")
        return False

    # 1) Film Session (SCU gera o UID e manda no request — pynetdicom nao
    #    expoe o UID criado pelo SCP no retorno, entao ja vamos com o nosso)
    sess_uid = generate_uid()
    sess = Dataset()
    sess.NumberOfCopies = "1"
    sess.PrintPriority = "HIGH"
    sess.MediumType = "PAPER"
    sess.FilmDestination = "MAGAZINE"
    st, _ = assoc.send_n_create(
        sess, BasicFilmSession, sess_uid,
        meta_uid=BasicGrayscalePrintManagementMeta)
    print(f"[PRINT N-CREATE Session] status={hex(st.Status)} uid={sess_uid}")
    if st.Status != 0x0000:
        print(f"[PRINT] detalhe: {st}")
        assoc.release()
        return False

    # 2) Film Box
    box_uid = generate_uid()
    box = Dataset()
    box.ImageDisplayFormat = "STANDARD\\1,1"
    box.FilmOrientation = "PORTRAIT"
    box.FilmSizeID = "8INX10IN"
    box.MagnificationType = "REPLICATE"
    ref = Dataset()
    ref.ReferencedSOPClassUID = BasicFilmSession
    ref.ReferencedSOPInstanceUID = sess_uid
    box.ReferencedFilmSessionSequence = [ref]
    st, box_attr = assoc.send_n_create(
        box, BasicFilmBox, box_uid,
        meta_uid=BasicGrayscalePrintManagementMeta)
    print(f"[PRINT N-CREATE FilmBox] status={hex(st.Status)} uid={box_uid}")
    if st.Status != 0x0000:
        print(f"[PRINT] detalhe: {st}")
        assoc.release()
        return False
    # Tenta descobrir o ImageBox UID retornado; senao gera um (nosso SCP aceita)
    img_uid = None
    if box_attr is not None:
        for seq_kw in ("ReferencedFilmBoxSequence", "ReferencedImageSequence",
                       "ReferencedBasicGrayscaleImageBoxSequence"):
            seq = getattr(box_attr, seq_kw, None)
            if seq:
                try:
                    img_uid = seq[0].ReferencedSOPInstanceUID
                    print(f"[PRINT] ImageBox do SCP ({seq_kw}): {img_uid}")
                    break
                except Exception:
                    pass
    if not img_uid:
        img_uid = generate_uid()
        print(f"[PRINT] usando o ImageBox UID gerado: {img_uid}")

    # 3) N-SET Image Box (imagem 64x64 fake)
    total = 64 * 64
    img = Dataset()
    img.ImageBoxPosition = 1
    img.Rows = 64
    img.Columns = 64
    img.BitsAllocated = 8
    img.BitsStored = 8
    img.HighBit = 7
    img.PixelRepresentation = 0
    img.SamplesPerPixel = 1
    img.PhotometricInterpretation = "MONOCHROME2"
    img.PixelData = struct.pack(f"<{total}B", *[(i % 256) for i in range(total)])
    st, _ = assoc.send_n_set(img, BasicGrayscaleImageBox, img_uid,
                             meta_uid=BasicGrayscalePrintManagementMeta)
    print(f"[PRINT N-SET ImageBox] status={hex(st.Status)}")
    if st.Status != 0x0000:
        assoc.release()
        return False

    # 4) N-ACTION print
    st, _ = assoc.send_n_action(None, 1, BasicFilmBox, box_uid,
                                meta_uid=BasicGrayscalePrintManagementMeta)
    print(f"[PRINT N-ACTION (imprimir)] status={hex(st.Status)}")
    ok = st.Status == 0x0000

    # 5) N-GET printer status
    try:
        from pydicom.tag import Tag
        st, rsp = assoc.send_n_get(
            [Tag(0x2110, 0x0010), Tag(0x2110, 0x0020)],
            Printer, None,
            meta_uid=BasicGrayscalePrintManagementMeta)
        print(f"[PRINT N-GET Printer] status={hex(st.Status)} "
              f"PrinterStatus={getattr(rsp or st, 'PrinterStatus', '?')}")
    except Exception as e:
        print(f"[PRINT N-GET] pulado (impressora sem N-GET ou UID exigido): {e}")

    # 6) limpeza
    try:
        assoc.send_n_delete(BasicFilmBox, box_uid,
                            meta_uid=BasicGrayscalePrintManagementMeta)
        assoc.send_n_delete(BasicFilmSession, sess_uid,
                            meta_uid=BasicGrayscalePrintManagementMeta)
    except Exception:
        pass
    assoc.release()
    print("[PRINT] SUCESSO — job impresso." if ok else "[PRINT] FALHA no N-ACTION.")
    return ok


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description="SCU de teste DICOM (simula modalidade)")
    ap.add_argument("--teste", choices=["echo", "store", "find", "move", "mwl", "print"],
                    required=True, help="qual servico DIMSE testar")
    ap.add_argument("--ip", default=cfg.get("pacs_ip", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=cfg.get("pacs_port", 11112))
    ap.add_argument("--aet", default=cfg.get("pacs_aet", "PACS_TESTE"),
                    help="AE Title do destino (SCP)")
    ap.add_argument("--meu-aet", default=cfg.get("meu_aet", "SIMULADOR"))
    ap.add_argument("--arquivo", default="teste_CT.dcm", help="para --teste store")
    ap.add_argument("--patient-name", default="*", help="para --teste find")
    ap.add_argument("--dest-aet", default="SIMULADOR", help="para --teste move")
    ap.add_argument("--study-uid", default="", help="para --teste move")
    ap.add_argument("--modality", default="", help="para --teste mwl (ex: CT)")
    ap.add_argument("--station-aet", default="", help="para --teste mwl")
    ap.add_argument("--start-date", default="", help="para --teste mwl (AAAAMMDD)")
    ap.add_argument("--mwl-port", type=int, default=11114, help="porta MWL SCP")
    ap.add_argument("--mwl-aet", default="RIS_TESTE", help="AET do RIS")
    ap.add_argument("--print-port", type=int, default=11115, help="porta Print SCP")
    ap.add_argument("--print-aet", default="PRINTER_TESTE", help="AET da impressora")
    args = ap.parse_args()

    ae = build_ae(args.meu_aet, args.teste, args.arquivo)
    ae.connection_timeout = cfg.get("timeout_acse", 10)

    if args.teste == "echo":
        test_echo(ae, args.ip, args.port, args.aet)
    elif args.teste == "store":
        test_store(ae, args.ip, args.port, args.aet, args.arquivo)
    elif args.teste == "find":
        test_find(ae, args.ip, args.port, args.aet, args.patient_name)
    elif args.teste == "move":
        test_move(ae, args.ip, args.port, args.aet, args.dest_aet, args.study_uid)
    elif args.teste == "mwl":
        test_mwl(ae, args.ip, args.mwl_port, args.mwl_aet,
                 args.modality, args.patient_name, args.station_aet, args.start_date)
    elif args.teste == "print":
        test_print(ae, args.ip, args.print_port, args.print_aet)


if __name__ == "__main__":
    main()
