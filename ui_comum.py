"""Peças compartilhadas pelas telas: dados, histórico, ajuda, destino ativo, resultados."""
import json
import time
from dataclasses import replace
from pathlib import Path

import streamlit as st

from dicomsim import diagnostico, profiles
from dicomsim.events import Emissor

BASE = Path(__file__).parent
HIST = BASE / "relatorios" / "historico.jsonl"
HIST.parent.mkdir(exist_ok=True)

# Termo técnico -> explicação curta (aparece no "?" ao lado dos campos).
AJUDA = {
    "ae": "AE Title é o 'nome' do equipamento na rede DICOM. O PACS só aceita nomes cadastrados "
          "nele, e maiúsculas e minúsculas importam.",
    "mpps": "MPPS: o equipamento avisa o servidor quando o exame começa e quando termina. "
            "Nem todo PACS usa; se não suportar, o simulador ignora e segue.",
    "commitment": "Storage Commitment: depois de enviar, o equipamento pergunta ao servidor se as "
                  "imagens foram gravadas de verdade e recebe a confirmação.",
    "worklist": "Worklist: lista de exames agendados no RIS. O equipamento consulta e escolhe um "
                "exame; as imagens entram nesse exame. Em geral só aparecem os de hoje, do AE "
                "Title de quem pergunta.",
    "novo": "Cada envio usa identificadores (UIDs) inéditos: o PACS sempre recebe imagem nova.",
    "sobrepor": "Reenvia as mesmas imagens com os mesmos identificadores do último envio: testa "
                "como o PACS trata duplicata ou substituição.",
    "anomala": "Arquivos de borda (sem cabeçalho, truncados, formatos antigos). O PACS recusar é "
               "esperado: serve para testar a robustez.",
}

ROTULO = {"worklist": "Buscar exame na agenda (worklist)",
          "mpps-inicio": "Avisar início do exame (MPPS)",
          "store": "Enviar imagens ao PACS",
          "aquisicao": "Preparar as imagens",
          "mpps-fim": "Avisar fim do exame (MPPS)",
          "commitment": "Confirmação de gravação (Storage Commitment)",
          "print": "Imprimir filme", "fim": "Resultado final", "inicio": "Início"}

DICAS = {
    "associação recusada": "O destino não aceitou a conexão. Confira AE Title (maiúsculas e "
                           "minúsculas), IP e porta, firewall, e se o PACS cadastrou este "
                           "equipamento. O Diagnóstico mostra qual é o problema.",
    "0xA7": "O PACS recusou a imagem por falta de espaço/recursos. Verifique o disco do PACS.",
    "0xC": "O PACS não aceitou o cabeçalho da imagem (dados inválidos ou duplicados).",
    "0x0112": "O PACS não conhece este exame (MPPS). O início precisa vir antes do fim.",
    "sem N-EVENT-REPORT": "O PACS aceitou o pedido mas não respondeu. Cadastre no PACS o AE Title "
                          "e a porta de retorno deste equipamento.",
}


@st.cache_resource
def servidor_virtual():
    return {"srv": None}


def dados():
    return profiles.carregar()


def modo():
    return st.session_state.get("modo", "Suporte")


# ------------------------------------------------------------------ histórico
def salvar_hist(reg):
    with open(HIST, "a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False, default=str) + "\n")


def ler_hist(n=50):
    if not HIST.exists():
        return []
    linhas = HIST.read_text(encoding="utf-8").strip().splitlines()[-n:]
    return [json.loads(x) for x in reversed(linhas)]


# ------------------------------------------------------------------ destino ativo
def destino_ativo():
    """(chave, Destino) do destino escolhido na barra lateral."""
    d = dados()
    chave = st.session_state.get("destino_ativo")
    if chave not in d["destinos"]:
        chave = next((k for k in d["destinos"] if k != "local"), next(iter(d["destinos"])))
        st.session_state["destino_ativo"] = chave
    return chave, profiles.destino(d, chave)


def equipamento_padrao_aet(d):
    return st.session_state.get("aet_diag") or d["equipamentos"][0]["aet"]


def status_conexao(chave, dest, aet, forcar=False, validade=60):
    """Semáforo de conexão (rede + AE Title + C-ECHO), guardado por 60 s."""
    cache = st.session_state.setdefault("_conn", {})
    c = cache.get((chave, aet))
    if forcar or c is None or time.time() - c["quando"] > validade:
        passos = diagnostico.diagnosticar(aet, dest)
        ok = diagnostico.conexao_ok(passos)
        falha = next((p for p in passos if p.status == "falha"), None)
        c = {"ok": ok, "quando": time.time(), "passos": passos,
             "msg": "conectado" if ok else (falha.detalhe if falha else "sem conexão")}
        cache[(chave, aet)] = c
    return c


# ------------------------------------------------------------------ apresentação
def mostrar_passos(passos, titulo_dica=True):
    icone = {"ok": "🟢", "falha": "🔴", "aviso": "🟡", "pulado": "⚪"}
    for p in passos:
        st.markdown(f"{icone[p.status]} **{p.titulo}**  \n{p.detalhe}")
        if p.dica and p.status in ("falha", "aviso"):
            st.caption(f"💡 {p.dica}")


def dica_para(ev):
    for chave, txt in DICAS.items():
        if chave in ev.detalhe:
            return txt
    return ""


def semaforo(em: Emissor, visao):
    """Resultado de um exame, de acordo com a visão."""
    if em.ok:
        st.success("Exame concluído: tudo foi entregue.")
    else:
        st.error("O exame teve falhas. Veja abaixo o que falhou.")
    eventos = em.eventos
    if visao != "Técnico":      # junta as imagens de uma etapa numa linha só
        agrupados = []
        for ev in eventos:
            if (agrupados and agrupados[-1].etapa == ev.etapa == "store"
                    and agrupados[-1].status == ev.status):
                agrupados[-1] = replace(agrupados[-1], detalhe="várias imagens")
                continue
            agrupados.append(ev)
        eventos = agrupados
    for ev in eventos:
        if ev.status == "info" and visao != "Técnico":
            continue
        icone = {"ok": "🟢", "falha": "🔴", "aviso": "🟡", "pulado": "⚪", "info": "🔹"}[ev.status]
        nome = ROTULO.get(ev.etapa, ev.etapa) if visao != "Técnico" else f"{ev.etapa}"
        txt = f"{icone} **{nome}**"
        if visao != "Cliente" or ev.status == "falha":
            txt += f" — {ev.detalhe}"
        st.markdown(txt)
        if ev.status == "falha" and visao != "Técnico":
            d = dica_para(ev)
            if d:
                st.caption(f"💡 {d}")
    if visao == "Técnico":
        with st.expander("Eventos brutos (JSON)"):
            st.json([{"etapa": e.etapa, "status": e.status, "detalhe": e.detalhe,
                      "dados": e.dados} for e in em.eventos])


def escolher_paciente(d, modalidade, automatico=False, chave="pac_exame"):
    """Seleciona um paciente cadastrado e devolve o 'item' do exame (ou None = automático)."""
    pac = d.get("pacientes", [])
    if not pac:
        st.info("Nenhum paciente cadastrado. Cadastre em **Cadastros → Pacientes**.")
        return None
    rot = [f"{p.get('nome','')} {p.get('sobrenome','')} · ID {p['id']}".strip() for p in pac]
    auto = "Automático (paciente de teste)"
    opcoes = ([auto] if automatico else []) + rot
    escolha = st.selectbox("Paciente", opcoes, key=chave)
    if escolha == auto:
        return None
    return profiles.item_de_paciente(pac[rot.index(escolha)], modalidade)


def rotulo_equipamento(e):
    return f"{e.nome}  ·  {e.modalidade}"
