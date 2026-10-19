"""Diagnóstico guiado: "por que não conecta?".

Cada passo responde uma pergunta simples e, se falhar, diz a causa provável e o
que fazer. Os passos de conexão param no primeiro erro (não adianta testar o
resto sem rede); os de serviços e worklist são independentes.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass

from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.sop_class import (
    BasicGrayscalePrintManagementMeta, ModalityPerformedProcedureStep,
    ModalityWorklistInformationFind, StorageCommitmentPushModel, Verification,
)

from . import library, steps
from .events import Emissor
from .netutil import Alvo, nova_ae, status_ok
from .profiles import Destino

OK, FALHA, AVISO, PULADO = "ok", "falha", "aviso", "pulado"


@dataclass
class Passo:
    id: str
    titulo: str
    status: str = PULADO
    detalhe: str = ""
    dica: str = ""


def _tcp(alvo: Alvo, timeout=3.0):
    try:
        with socket.create_connection((alvo.ip, alvo.porta), timeout=timeout):
            return True, ""
    except socket.timeout:
        return False, "sem resposta (tempo esgotado)"
    except socket.gaierror:
        return False, "nome/IP não encontrado"
    except OSError as e:
        return False, f"{e.strerror or e}"


def _passo_rede(alvo):
    p = Passo("rede", f"O servidor responde em {alvo.ip}:{alvo.porta}?")
    ok, motivo = _tcp(alvo)
    if ok:
        p.status, p.detalhe = OK, "a porta está aberta"
    else:
        p.status, p.detalhe = FALHA, motivo
        p.dica = ("Confira o IP e a porta, se o cabo/Wi-Fi/VPN está conectado e se um firewall "
                  "bloqueia a porta. A porta mudou? Pergunte ao responsável pelo PACS.")
    return p


def _passo_aet(aet, alvo):
    p = Passo("aet", f"O PACS aceita o AE Title '{aet}'?")
    ae = nova_ae(aet, verification=True)
    a = ae.associate(alvo.ip, alvo.porta, ae_title=alvo.aet)
    if a.is_established:
        a.release()
        p.status, p.detalhe = OK, f"associação aceita por '{alvo.aet}'"
        return p, True
    p.status = FALHA
    if a.is_rejected:
        p.detalhe = "associação RECUSADA pelo servidor"
        p.dica = (f"O PACS só aceita equipamentos cadastrados. Peça para cadastrar o AE Title "
                  f"'{aet}' (ou use um já cadastrado) e confira se o AE Title do PACS é mesmo "
                  f"'{alvo.aet}' (maiúsculas e minúsculas importam).")
    elif a.is_aborted:
        p.detalhe = "o servidor encerrou a conexão"
        p.dica = "Essa porta pode ser de outro serviço (ex.: HTTP) e não de DICOM."
    else:
        p.detalhe = "sem resposta DICOM"
        p.dica = "A porta abre, mas não é um serviço DICOM. Confira a porta."
    return p, False


def _passo_echo(aet, alvo):
    p = Passo("echo", "O servidor responde ao C-ECHO (ping DICOM)?")
    ae = nova_ae(aet, verification=True)
    a = ae.associate(alvo.ip, alvo.porta, ae_title=alvo.aet)
    if not a.is_established:
        p.status, p.detalhe = FALHA, "sem associação"
        return p
    st = a.send_c_echo()
    a.release()
    if status_ok(st):
        p.status, p.detalhe = OK, "respondeu 0x0000"
    else:
        p.status, p.detalhe = FALHA, "respondeu com erro"
        p.dica = "O servidor está no ar mas recusa verificação; veja o log do PACS."
    return p


SERVICOS = [
    ("Receber imagens (C-STORE)", "1.2.840.10008.5.1.4.1.1.7"),
    ("Aviso de início/fim do exame (MPPS)", ModalityPerformedProcedureStep),
    ("Confirmação de gravação (Storage Commitment)", StorageCommitmentPushModel),
    ("Lista de trabalho (Worklist)", ModalityWorklistInformationFind),
    ("Impressão de filme (Print)", BasicGrayscalePrintManagementMeta),
]


def _passo_servicos(aet, alvo):
    p = Passo("servicos", "Quais serviços o servidor oferece?")
    linhas, aceitos = [], 0
    for nome, sop in SERVICOS:
        ae = nova_ae(aet, [sop], verification=False)
        a = ae.associate(alvo.ip, alvo.porta, ae_title=alvo.aet)
        ok = a.is_established and len(a.accepted_contexts) > 0
        if a.is_established:
            a.release()
        aceitos += ok
        linhas.append(f"{'✅' if ok else '➖'} {nome}")
    p.status = OK if aceitos else AVISO
    p.detalhe = " · ".join(linhas)
    p.dica = ("➖ não é erro: significa que este servidor não usa o serviço (ex.: um PACS sem "
              "MPPS). O simulador ignora o que não for suportado e segue.")
    return p


def _passo_worklist(aet, dest: Destino, modalidade):
    p = Passo("worklist", "A worklist devolve exames para este AE Title?")
    if dest.ris is None:
        p.status, p.detalhe = PULADO, "este destino não tem RIS configurado"
        return p
    em = Emissor(imprimir=False)
    lista = steps.consultar_worklist(em, aet, dest.ris, modalidade=modalidade)
    if lista is None:
        p.status, p.detalhe = FALHA, "o RIS não respondeu"
        p.dica = "Confira AE Title, IP e porta do RIS no destino."
        return p
    if lista:
        p.status = OK
        p.detalhe = f"{len(lista)} exame(s) agendado(s)" + (f" de {modalidade}" if modalidade else "")
        return p
    outras = steps.consultar_worklist(Emissor(imprimir=False), aet, dest.ris, modalidade="") or []
    p.status = AVISO
    if outras and modalidade:
        p.detalhe = (f"nenhum exame de {modalidade}, mas há {len(outras)} de outra modalidade: "
                     + ", ".join(sorted({o['modalidade'] for o in outras})))
        p.dica = "Escolha um equipamento da modalidade certa, ou mostre todas as modalidades."
    else:
        p.detalhe = "a agenda está vazia para este AE Title"
        p.dica = ("A maioria dos RIS só devolve exames de HOJE e só do AE Title de quem pergunta. "
                  "Confira a data e o AE Title do equipamento no agendamento.")
    return p


def _passo_envio(aet, dest: Destino, modalidade):
    p = Passo("envio", "Uma imagem de teste chega ao PACS?")
    ds = library.imagem_sintetica(modalidade or "OT", 0, lado=64)
    paciente = {"nome": "DIAGNOSTICO^SIMULADOR", "id": "DIAG" + ds.SOPInstanceUID[-8:],
                "acesso": "DIAG" + ds.SOPInstanceUID[-6:], "procedimento": "Teste de conexão"}
    from pydicom.uid import generate_uid
    ds = library.carimbar(ds, paciente, generate_uid(), generate_uid(), 1, 1, estacao=aet)
    em = Emissor(imprimir=False)
    res = steps.armazenar(em, aet, dest.pacs, [ds])
    if res and res[0]["ok"]:
        p.status, p.detalhe = OK, f"imagem aceita ({res[0]['status']})"
    else:
        p.status = FALHA
        p.detalhe = res[0]["status"] if res else "sem resposta"
        p.dica = "A conexão funciona, mas o PACS recusou a imagem. Veja o log do PACS."
    return p


def diagnosticar(aet, dest: Destino, modalidade="", testar_envio=False):
    """Roda o diagnóstico. Devolve a lista de Passo (na ordem)."""
    passos = [_passo_rede(dest.pacs)]
    if passos[0].status != OK:
        for pid, tit in (("aet", f"O PACS aceita o AE Title '{aet}'?"),
                         ("echo", "O servidor responde ao C-ECHO (ping DICOM)?")):
            passos.append(Passo(pid, tit, PULADO, "não testado: sem conexão de rede"))
        return passos
    p_aet, aceito = _passo_aet(aet, dest.pacs)
    passos.append(p_aet)
    if not aceito:
        passos.append(Passo("echo", "O servidor responde ao C-ECHO (ping DICOM)?", PULADO,
                            "não testado: a associação foi recusada"))
        return passos
    passos.append(_passo_echo(aet, dest.pacs))
    passos.append(_passo_servicos(aet, dest.pacs))
    passos.append(_passo_worklist(aet, dest, modalidade))
    if testar_envio:
        passos.append(_passo_envio(aet, dest, modalidade))
    return passos


def conexao_ok(passos):
    por = {p.id: p for p in passos}
    return all(por.get(i) and por[i].status == OK for i in ("rede", "aet", "echo"))


def relatorio_texto(passos, aet, dest: Destino, equipamento=""):
    """Texto pronto para copiar e colar num chamado ou mensagem."""
    from datetime import datetime
    icone = {OK: "✅", FALHA: "❌", AVISO: "⚠️", PULADO: "⏭"}
    linhas = [f"Diagnóstico de conexão DICOM — {datetime.now():%d/%m/%Y %H:%M}",
              f"Equipamento: {equipamento or '-'} · AE Title de origem: {aet}",
              f"Destino: {dest.pacs}" + (f" · RIS: {dest.ris}" if dest.ris else ""), ""]
    for p in passos:
        linhas.append(f"{icone[p.status]} {p.titulo} — {p.detalhe}")
        if p.dica and p.status in (FALHA, AVISO):
            linhas.append(f"    → {p.dica}")
    linhas.append("")
    linhas.append("Conclusão: " + ("a conexão com o PACS está funcionando."
                                   if conexao_ok(passos) else "a conexão com o PACS NÃO está funcionando."))
    return "\n".join(linhas)
