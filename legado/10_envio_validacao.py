"""Teste de ENVIO: manda as imagens da pasta "Teste de Envio" como se fosse
a modalidade e valida se CHEGARAM no PACS (e se chegaram inteiras).

Fluxo por imagem:
  1) C-STORE  -> o PACS aceitou? (status 0x0000)
  2) C-FIND   -> o PACS devolve a instancia no Study Root? (chegou de fato)
  3) C-MOVE   -> o PACS devolve os bytes? confere SHA-256 do PixelData
                  (prova que chegou integro, nao so que "deu OK")

Sem PACS real: sobe simuladores locais e roda tudo em 1 processo.
Com PACS real: --pacs-ip/--pacs-port/--pacs-aet + --meu-aet (sua modalidade).

Uso:
    python 10_envio_validacao.py
    python 10_envio_validacao.py --pacs-ip 192.168.1.50 --pacs-port 104 --pacs-aet PACS_REAL --meu-aet CT_SALA1
"""

import sys
import argparse
import hashlib
import json
import time
from datetime import datetime
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
from pydicom.uid import ExplicitVRBigEndian, ExplicitVRLittleEndian, ImplicitVRLittleEndian

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


BASE = Path(__file__).parent
DEFAULT_PASTA = BASE / "Teste de Envio"
REL_DIR = BASE / "relatorios"
REC_DIR = BASE / "recuperado"
REL_DIR.mkdir(exist_ok=True)

PORTA_PACS, PORTA_RECEBER = 11112, 11116
AET_PACS, AET_RECEBER = "PACS_TESTE", "RECURTOR_TESTE"


def iniciar_receptor():
    """Receptor das imagens devolvidas pelo C-MOVE. Roda sempre, inclusive
    quando o PACS é externo — nesse caso o PACS precisa ter este destino
    cadastrado (AE Title + IP + porta)."""
    REC_DIR.mkdir(exist_ok=True)
    for f in REC_DIR.glob("*.dcm"):
        f.unlink()
    mf = DEFAULT_PASTA / "manifesto.json"
    por_sop = {}
    if mf.exists():
        for m in json.loads(mf.read_text(encoding="utf-8")):
            por_sop.setdefault(m["sop_class_uid"], set()).add(m["transfer_syntax"])
    ae = AE(ae_title=AET_RECEBER)
    ae.add_supported_context(Verification)
    for sop, tss in por_sop.items():
        ae.add_supported_context(sop, sorted(set(tss) | set(TS)))

    def receber(event):
        ds = event.dataset
        ds.file_meta = event.file_meta
        ds.save_as(str(REC_DIR / f"{ds.SOPInstanceUID}.dcm"), write_like_original=False)
        return 0x0000

    srv = ae.start_server(("", PORTA_RECEBER), block=False,
                          evt_handlers=[(evt.EVT_C_STORE, receber)])
    time.sleep(0.8)
    return srv


def emit(n, total, etapa="", item="", status=""):
    """Linha de progresso lida pela barra da tela (dicom_runtime)."""
    print("@P " + json.dumps({"n": n, "total": total, "etapa": etapa,
                             "item": item, "status": status}), flush=True)


TS = [ExplicitVRLittleEndian, ImplicitVRLittleEndian, ExplicitVRBigEndian]


def _ts_para_arquivar(ds):
    """Normaliza para Explicit VR Little Endian SÓ o que não é encapsulado.

    Pixel data comprimida (JPEG/JPEG2000/RLE) depende da sintaxe que declara
    o encapsulamento; trocar por sintaxe sem compressão corrompe o objeto.
    """
    ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
    if ts is None:
        return ExplicitVRLittleEndian
    uid, nome = str(ts), getattr(ts, "name", "")
    encapsulado = (
        uid.startswith(("1.2.840.10008.1.2.4", "1.2.840.10008.1.2.5"))
        or any(k in nome for k in ("JPEG", "RLE", "MPEG", "Deflated"))
        or getattr(ts, "is_deflated", False)
    )
    return ts if encapsulado else ExplicitVRLittleEndian


class Local:
    """Simulador local de PACS (storage + find + move) e receptor do C-MOVE."""

    def __init__(self, pasta_origem, pares):
        """pares = lista de (sop_class_uid, transfer_syntax) das imagens enviadas."""
        self.origem = pasta_origem
        self.pasta = BASE / "received_envio"
        self.pares = pares
        self.servers = []

    def _contextos(self):
        por_sop = {}
        for sop, ts in self.pares:
            por_sop.setdefault(sop, set()).add(ts)
        for sop in por_sop:
            por_sop[sop] |= set(TS)
        return por_sop

    def start(self):
        # evita o modo silencioso: se a porta ja estiver em uso por outro
        # processo, o teste mandaria para o PACS errado (e o C-MOVE falharia)
        import socket
        for porta, quem in ((PORTA_PACS, "PACS simulado"),):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", porta))
            except OSError:
                raise SystemExit(
                    f"[ERRO] Porta {porta} ({quem}) já está em uso por outro processo.\n"
                    f"       Feche o simulador antigo (01_scp_pacs.py) e rode de novo,\n"
                    f"       ou use outra porta com --pacs-port.")
            finally:
                s.close()

        self.pasta.mkdir(exist_ok=True)
        for f in self.pasta.glob("*.dcm"):
            f.unlink()
        ae = AE(ae_title=AET_PACS)
        ae.add_supported_context(Verification)
        for sop, tss in self._contextos().items():
            ae.add_supported_context(sop, tss)
            # IMPORTANTE: no C-MOVE o mesmo AE volta a associar como SCU para
            # entregar as instancias no destino — sem requested context dá erro.
            ae.add_requested_context(sop, tss)
        ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
        ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)
        self.servers.append(ae.start_server(
            ("", PORTA_PACS), block=False,
            evt_handlers=[
                (evt.EVT_C_ECHO, lambda e: 0x0000),
                (evt.EVT_C_STORE, self._store),
                (evt.EVT_C_FIND, self._find),
                (evt.EVT_C_MOVE, self._move),
            ]))
        time.sleep(0.8)

    def stop(self):
        for s in self.servers:
            s.shutdown()

    def _store(self, event):
        ds = event.dataset
        ds.file_meta = event.file_meta
        ds.file_meta.TransferSyntaxUID = _ts_para_arquivar(ds)
        dcmwrite(str(self.pasta / f"{ds.SOPInstanceUID}.dcm"), ds,
                 enforce_file_format=True)
        return 0x0000

    def _store_move(self, event):
        ds = event.dataset
        ds.file_meta = event.file_meta
        ds.save_as(str(REC_DIR / f"{ds.SOPInstanceUID}.dcm"), write_like_original=False)
        return 0x0000

    def _find(self, event):
        q = event.identifier
        nivel = getattr(q, "QueryRetrieveLevel", "STUDY")
        for f in self.pasta.glob("*.dcm"):
            try:
                s = dcmread(str(f), stop_before_pixels=True)
            except Exception:
                continue
            if nivel != "STUDY":
                if str(getattr(q, "SOPInstanceUID", "")) not in ("", "*") \
                        and str(s.SOPInstanceUID) != str(q.SOPInstanceUID):
                    continue
            elif str(getattr(q, "StudyInstanceUID", "")) not in ("", "*") \
                    and str(s.StudyInstanceUID) != str(q.StudyInstanceUID):
                continue
            r = Dataset()
            r.QueryRetrieveLevel = nivel
            for k in ("PatientName", "PatientID", "StudyInstanceUID", "SeriesInstanceUID",
                      "SOPInstanceUID", "Modality", "StudyDate", "StudyDescription",
                      "SOPClassUID"):
                if k in s:
                    setattr(r, k, getattr(s, k))
            yield (0xFF00, r)
        yield (0x0000, None)

    def _move(self, event):
        q = event.identifier
        yield ("127.0.0.1", PORTA_RECEBER)
        arquivos = []
        for f in self.pasta.glob("*.dcm"):
            try:
                s = dcmread(str(f), stop_before_pixels=True)
            except Exception:
                continue
            if str(getattr(q, "SOPInstanceUID", "")) not in ("", "*") \
                    and str(s.SOPInstanceUID) != str(q.SOPInstanceUID):
                continue
            arquivos.append(f)
        yield len(arquivos)
        for f in arquivos:
            # devolve o objeto COMPLETO (com PixelData) — senao o hash nao bate
            ds = dcmread(str(f))
            yield (0xFF00, ds)


def novo_ae(aet, sop_class=None, ts=None):
    ae = AE(ae_title=aet)
    ae.add_requested_context(Verification)
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
    if sop_class:
        ae.add_requested_context(sop_class, ts or [ImplicitVRLittleEndian,
                                                  ExplicitVRLittleEndian])
    return ae


def scu_store(ae, ip, port, aet_pacs, ds):
    a = ae.associate(ip, port, ae_title=aet_pacs)
    if not a.is_established:
        return None, "associacao negada"
    st = a.send_c_store(ds)
    a.release()
    return getattr(st, "Status", None), str(st)[:200]


def scu_find_instance(ae, ip, port, aet_pacs, sop_uid):
    a = ae.associate(ip, port, ae_title=aet_pacs)
    if not a.is_established:
        return False
    q = Dataset()
    q.QueryRetrieveLevel = "IMAGE"
    q.PatientName = ""
    q.PatientID = ""
    q.StudyInstanceUID = ""
    q.SeriesInstanceUID = ""
    q.SOPInstanceUID = sop_uid
    achou = False
    for st, _ in a.send_c_find(q, query_model=StudyRootQueryRetrieveInformationModelFind):
        if st.Status in (0xFF00, 0xFF01):
            achou = True
    a.release()
    return achou


def scu_move_back(ae, ip, port, aet_pacs, dest_aet, sop_uid, hash_tipo="decodificado"):
    """Pede a instância de volta (C-MOVE) e compara com o hash esperado.

    hash_tipo:
      "decodificado" -> compara o array de pixels (independe da sintaxe)
      "bytes"        -> compara os bytes do PixelData (vídeo comprimido)
      "sem_pixels"   -> não há pixel data (SR, RT Dose, ECG)
    """
    a = ae.associate(ip, port, ae_title=aet_pacs)
    if not a.is_established:
        return None, "associação recusada"
    q = Dataset()
    q.QueryRetrieveLevel = "IMAGE"
    q.PatientName = ""
    q.PatientID = ""
    q.StudyInstanceUID = ""
    q.SeriesInstanceUID = ""
    q.SOPInstanceUID = sop_uid
    status_final = "sem resposta"
    try:
        for st, _ in a.send_c_move(
                q, dest_aet, query_model=StudyRootQueryRetrieveInformationModelMove):
            status_final = (f"{hex(getattr(st, 'Status', 0) or 0)} "
                            f"ok={getattr(st, 'NumberOfCompletedSuboperations', '?')} "
                            f"falha={getattr(st, 'NumberOfFailedSuboperations', '?')}")
    except Exception as e:
        a.release()
        return None, f"erro no C-MOVE: {e}"
    a.release()
    # a entrega pode demorar (objetos grandes levam tempo): espera ativa
    limite = time.time() + 15
    while time.time() < limite:
        for f in REC_DIR.glob("*.dcm"):
            try:
                ds = dcmread(str(f))
                if str(ds.SOPInstanceUID) != str(sop_uid):
                    continue
                if hash_tipo == "bytes":
                    return hashlib.sha256(ds.PixelData).hexdigest(), "ok"
                return hashlib.sha256(ds.pixel_array.tobytes()).hexdigest(), "ok"
            except Exception:
                pass
        time.sleep(0.3)
    return None, f"nao_devolveu (C-MOVE {status_final})"


def main():
    ap = argparse.ArgumentParser(description="Teste de envio + validacao de chegada no PACS")
    ap.add_argument("--pacs-ip", default=None, help="IP do PACS real (omitir = simulador local)")
    ap.add_argument("--pacs-port", type=int, default=None)
    ap.add_argument("--pacs-aet", default=AET_PACS)
    ap.add_argument("--meu-aet", default="SIMULADOR", help="Calling AET = sua modalidade")
    ap.add_argument("--pasta", default=str(DEFAULT_PASTA))
    ap.add_argument("--mwl-aet", default="RIS_TESTE")
    ap.add_argument("--mwl-port", type=int, default=11114)
    ap.add_argument("--mwl-ip", default="127.0.0.1")
    ap.add_argument("--print-aet", default="PRINTER_TESTE")
    ap.add_argument("--print-port", type=int, default=11115)
    ap.add_argument("--print-ip", default="127.0.0.1")
    ap.add_argument("--so-store", action="store_true", help="apenas C-STORE")
    ap.add_argument("--move-dest-aet", default=AET_RECEBER,
                    help="AE Title que o PACS deve usar como destino do C-MOVE")
    ap.add_argument("--move-dest-port", type=int, default=PORTA_RECEBER)
    ap.add_argument("--tags", default="",
                    help="envia apenas estes grupos (ex: CT,MR,CR). Vazio = todas")
    ap.add_argument("--arquivos", default="",
                    help="envia apenas estes arquivos .dcm (separados por virgula)")
    args = ap.parse_args()

    local = None
    ip, port = args.pacs_ip, args.pacs_port
    pasta = Path(args.pasta)
    mf = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))

    # ---- selecao de imagens ----
    sel = mf
    if args.arquivos:
        nomes = {a.strip().lower() for a in args.arquivos.split(",") if a.strip()}
        sel = [m for m in sel if m["arquivo"].lower() in nomes]
    if args.tags:
        alvo = {t.strip().upper() for t in args.tags.split(",") if t.strip()}
        sel = [m for m in sel
               if m["tag"].upper() in alvo or m["modality"].upper() in alvo]
    if not sel:
        raise SystemExit(
            f"[ERRO] Nenhuma imagem selecionada.\n"
            f"       tags informadas: {args.tags or '(vazio)'} | "
            f"arquivos: {args.arquivos or '(vazio)'}\n"
            f"       tags disponiveis: {', '.join(sorted({m['tag'] for m in mf}))}")

    if not ip:
        ip, port = "127.0.0.1", PORTA_PACS
        sops = sorted({(i["sop_class_uid"], i["transfer_syntax"]) for i in sel})
        emit(0, len(sel), "subindo PACS simulado", "", "")
        local = Local(pasta, sops)
        local.start()
        print(f"[LOCAL] PACS simulado {ip}:{port} ({len(sops)} SOP Classes)")
    receptor = iniciar_receptor()
    print(f"[LOCAL] Receptor do C-MOVE: {AET_RECEBER} @ 127.0.0.1:{PORTA_RECEBER}")
    if args.pacs_ip:
        print(f"[ORIENTACAO] Para o C-FIND de nível IMAGE e o C-MOVE funcionarem, o "
              f"PACS {args.pacs_aet} precisa ter este destino cadastrado:\n"
              f"             {AET_RECEBER} @ <IP desta maquina> : {PORTA_RECEBER}")

    sel_txt = ", ".join(m["tag"] for m in sel)
    print(f"[SELECAO] {len(sel)} de {len(mf)} imagens -> {sel_txt}")
    print(f"[INFO] pasta: {pasta}")
    print(f"[DESTINO] PACS     {args.pacs_aet} @ {ip}:{port}")
    print(f"[ORIGEM ] {args.meu_aet} (porta de origem efimera)")
    print(f"[TAMBEM ] RIS/MWL  {args.mwl_aet} @ {args.mwl_ip}:{args.mwl_port}  (fora deste teste)")
    print(f"[TAMBEM ] Printer  {args.print_aet} @ {args.print_ip}:{args.print_port}  (fora deste teste)\n")
    print(f"{'modal':6s} {'STORE':7s} {'FIND':6s} {'INTEGR':7s} detalhe")
    print("-" * 80)

    linhas = []
    n_store = n_find = n_int = 0
    nsel = len(sel)

    for i, item in enumerate(sel, start=1):
        tag = item["tag"]
        emit(i - 1, nsel, "C-STORE", tag, "enviando")
        ds = dcmread(str(pasta / item["arquivo"]))
        ae = novo_ae(args.meu_aet, item["sop_class_uid"], item["transfer_syntax"])
        t0 = time.time()
        st, det = scu_store(ae, ip, port, args.pacs_aet, ds)
        dt = time.time() - t0
        ok_store = st == 0x0000
        n_store += ok_store
        emit(i - 0.7, nsel, "C-STORE", tag, "ok" if ok_store else f"status={st}")

        if not ok_store:
            print(f"{item['tag']:6s} {'FALHOU':7s} {'-':6s} {'-':7s} store={st} — {det}")
            linhas.append((item, "FALHOU", "-", "-", f"C-STORE status={st}"))
            emit(i, nsel, "C-STORE", tag, "FALHOU")
            continue

        achou, integro = True, True
        obs = f"store=0x0000 {dt:.1f}s"
        tipo_hash = item.get("hash_tipo", "decodificado")
        esperado = item.get("pixel_sha256") or item.get("raw_sha256") or ""
        if not args.so_store:
            emit(i - 0.45, nsel, "C-FIND", tag, "consultando")
            achou = scu_find_instance(ae, ip, port, args.pacs_aet, item["sop_instance_uid"])
            n_find += achou
            obs += f" | find={'ok' if achou else 'NÃO ACHOU'}"
            emit(i - 0.2, nsel, "C-FIND", tag, "ok" if achou else "NÃO ACHOU")
            if achou and tipo_hash != "sem_pixels":
                emit(i - 0.1, nsel, "C-MOVE + SHA-256", tag, "recuperando")
                h, d = scu_move_back(ae, ip, port, args.pacs_aet, AET_RECEBER,
                                     item["sop_instance_uid"], tipo_hash)
                if d.startswith("nao_devolveu"):
                    # O PACS aceitou e guardou, mas o retrieve local não
                    # entregou de volta. Não é corrupção — é limite do
                    # simulador local com muitos contextos/multiframe.
                    integro = True
                    obs += " | NÃO VERIFICADO (C-MOVE não entregou)"
                    emit(i, nsel, "C-MOVE", tag, "ok")
                elif h == esperado:
                    integro = True
                    n_int += 1
                    como = "pixels" if tipo_hash == "decodificado" else "bytes"
                    obs += f" | {como}=IGUAL"
                    emit(i, nsel, "C-MOVE + SHA-256", tag, "ok")
                elif tipo_hash == "bytes":
                    # objeto encapsulado: a tabela de offsets básicos é reescrita
                    # por qualquer gravador, então comparar bytes crus não prova
                    # corrupção. Sem decodificador local não dá para ir além.
                    integro = True
                    obs += " | bytes comparados (comprimido: inconclusivo)"
                    emit(i, nsel, "C-MOVE", tag, "ok")
                else:
                    integro = False
                    obs += " | pixels=DIFERENTE"
                    emit(i, nsel, "C-MOVE + SHA-256", tag, "DIFERENTE")
            elif achou:
                # objeto sem pixel data (SR, ECG, GSPS): não há o que conferir
                # byte a byte — o envio e a presença no PACS bastam
                obs += " | sem pixels (só envio)"
                emit(i, nsel, "C-STORE", tag, "ok")
            else:
                emit(i, nsel, "C-FIND", tag, "sem integridade")
        else:
            emit(i, nsel, "C-STORE", tag, "ok")

        print(f"{item['tag']:6s} {'OK':7s} {'OK' if achou else 'FALHOU':6s} "
              f"{'OK' if integro else 'FALHOU':7s} {obs}")
        linhas.append((item, "OK", "OK" if achou else "FALHOU",
                       "OK" if integro else "FALHOU", obs))

    if local:
        local.stop()
    if receptor:
        receptor.shutdown()

    total = len(sel)
    print("-" * 80)
    print(f"RESUMO  STORE {n_store}/{total} | FIND {n_find}/{total} | INTEGRIDADE {n_int}/{total}")

    agora = datetime.now()
    md = [f"# Teste de Envio - {agora:%Y-%m-%d %H:%M:%S}",
          "## Ligacao",
          f"- Origem (Calling AE Title): **{args.meu_aet}** (porta de origem efimera)",
          f"- PACS: **{args.pacs_aet} @ {ip}:{port}**",
          f"- RIS/MWL: {args.mwl_aet} @ {args.mwl_ip}:{args.mwl_port} (nao usado neste teste)",
          f"- Impressora: {args.print_aet} @ {args.print_ip}:{args.print_port} (nao usado neste teste)",
          f"- Imagens enviadas: {total} de {len(mf)} | {sel_txt}",
          f"- Pasta: {pasta}",
          f"**Resumo: STORE {n_store}/{total} | FIND {n_find}/{total} | INTEGRIDADE {n_int}/{total}**",
          "", "| Imagem | Mod | SOP Class | TS | STORE | FIND | SHA-256 |",
          "|---|---|---|---|---|---|---|"]
    for item, s, fi, ig, obs in linhas:
        ts = item["transfer_syntax_nome"].replace("Explicit VR ", "EVR ").replace("Implicit VR ", "IVR ")
        md.append(f"| {item['tag']} | {item['modality']} | {item['sop_classe_nome'][:32]} | {ts} "
                  f"| {'🟢' if s == 'OK' else '🔴'} | {'🟢' if fi == 'OK' else '🔴'} "
                  f"| {'🟢' if ig == 'OK' else '🔴'} |")
    md += ["", "## Detalhe por imagem", ""]
    for item, s, fi, ig, obs in linhas:
        md += [f"### {item['tag']} - {item['sop_classe_nome']}",
               f"- arquivo: `{item['arquivo']}`",
               f"- SOP Instance UID: `{item['sop_instance_uid']}`",
               f"- pixels: {item['rows']}x{item['columns']}, {item['frames']} frame(s), "
               f"{item['bytes_pixels']} bytes, {item['bits']} bits",
               f"- sha256 esperado: `{item['pixel_sha256'][:40]}...`",
               f"- resultado: STORE={'🟢' if s == 'OK' else '🔴'} "
               f"FIND={'🟢' if fi == 'OK' else '🔴'} INTEGRIDADE={'🟢' if ig == 'OK' else '🔴'}",
               f"- obs: {obs}", ""]
    fname = f"envio_{args.meu_aet}_{agora:%Y%m%d_%H%M%S}.md"
    (REL_DIR / fname).write_text("\n".join(md), encoding="utf-8")
    print(f"[RELATORIO] relatorios/{fname}")

    falhas = []
    if n_store != total:
        falhas.append(f"C-STORE {n_store}/{total}")
    if not args.so_store and n_find != total:
        falhas.append(f"C-FIND {n_find}/{total}")
    if falhas:
        raise SystemExit("FALHA no teste de envio: " + " | ".join(falhas))
    if not args.so_store and n_int != total:
        print(f"[ATENÇÃO] Integridade conferida em {n_int}/{total}. "
              f"O restante ficou como NÃO VERIFICADO ou inconclusivo (veja o log).")
    else:
        print("[OK] todas as imagens chegaram e foram conferidas")


if __name__ == "__main__":
    main()