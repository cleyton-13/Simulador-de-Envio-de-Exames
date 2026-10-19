"""Enviar exame.

  Cliente  — 1 tela, 1 botão: escolhe equipamento (e paciente) e envia
  Suporte  — assistente em 3 passos: onde enviar → o que enviar → imagens
  Técnico  — o mesmo + "Controle total" (conexão, destino, worklist, arquivos, MPPS...)
"""
import json
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st

from dicomsim import library, profiles, steps
from dicomsim.events import Emissor
from dicomsim.exam import executar_exame
from dicomsim.netutil import TIMEOUTS, Alvo
from dicomsim.util import nome_legivel

import ui_comum as C


def _executar(eq, dest, item, usar_wl, extra, visao):
    vezes = extra.pop("vezes", 1)
    ultimo = None
    for n in range(vezes):
        em = Emissor(nome=eq.nome, imprimir=False)
        with st.spinner(f"Enviando exame {n + 1}/{vezes}..."):
            r = executar_exame(eq, dest, item=item if n == 0 or not item else item,
                               em=em, usar_worklist=usar_wl, **extra)
        ultimo = em
        C.salvar_hist({"quando": datetime.now().isoformat(timespec="seconds"),
                       "equipamento": eq.nome, "destino": str(dest.pacs), "ok": r.ok,
                       "imagens": r.imagens, "paciente": nome_legivel(r.paciente),
                       "etapas": em.resumo()["etapas"]})
    st.session_state["ultimo"] = ultimo


# ----------------------------------------------------------------------------- Cliente
def _tela_cliente(d, chave, dest):
    st.title("Enviar exame de teste")
    st.caption(f"Destino: **{dest.pacs}**. Escolha o equipamento e clique em enviar.")
    eqs = profiles.equipamentos(d)
    c1, c2 = st.columns(2)
    nome = c1.selectbox("Equipamento", [e.nome for e in eqs], key="ex_eq",
                        format_func=lambda n: C.rotulo_equipamento(next(e for e in eqs if e.nome == n)))
    eq = next(e for e in eqs if e.nome == nome)
    with c2:
        item = C.escolher_paciente(d, eq.modalidade, automatico=True)
    if st.button("▶ Enviar exame de teste", type="primary", width="stretch"):
        _executar(eq, dest, item, False, {}, "Cliente")
    if "ultimo" in st.session_state:
        C.semaforo(st.session_state["ultimo"], "Cliente")


# ----------------------------------------------------------------------------- Suporte
def _passo(num, titulo):
    st.markdown(f"#### {num} · {titulo}")


def _agenda(eq, dest, visao):
    """Consulta e escolha do exame da worklist. Devolve o item escolhido (ou None)."""
    if dest.ris is None:
        st.warning("Este destino não tem RIS (worklist) configurado. Configure em "
                   "**Cadastros → Destinos** ou escolha outro paciente.")
        return None
    qualquer = st.checkbox("Mostrar todas as modalidades da agenda deste AE Title", False, key="ex_qualquer",
                           help=C.AJUDA["worklist"])
    if st.button("Ver agenda", key="ex_ver_agenda"):
        lista = steps.consultar_worklist(Emissor(imprimir=False), eq.aet, dest.ris,
                                         modalidade="" if qualquer else eq.modalidade)
        outras = []
        if lista == [] and not qualquer:
            outras = steps.consultar_worklist(Emissor(imprimir=False), eq.aet, dest.ris, modalidade="") or []
        st.session_state.update(agenda=lista or [], agenda_outras=outras,
                                agenda_falha=lista is None, agenda_de=(eq.aet, eq.modalidade))
    if "agenda" not in st.session_state:
        st.info("Clique em **Ver agenda** para listar os exames agendados.")
        return None
    ag = st.session_state["agenda"]
    outras = st.session_state.get("agenda_outras", [])
    if st.session_state.get("agenda_falha"):
        st.error(f"Não foi possível consultar o RIS {dest.ris}. Rode o **Diagnóstico** para ver "
                 f"se o problema é rede, AE Title ou porta.")
    elif not ag and outras:
        st.warning(f"Não há exame de **{eq.modalidade}** para **{eq.aet}**, mas há {len(outras)} de outra "
                   f"modalidade: " + "; ".join(f"{o['acesso']} ({o['modalidade']}, {o['data']})" for o in outras)
                   + ". Marque \"Mostrar todas as modalidades\" ou escolha o equipamento certo.")
    elif not ag:
        st.warning(f"Nenhum exame agendado para **{eq.aet}**. A maioria dos RIS só mostra os exames de "
                   f"**hoje** do AE Title de quem pergunta.")
    if not ag:
        return None
    idx = st.selectbox("Exame da agenda", range(len(ag)), key="ex_agenda_idx",
                       format_func=lambda i: f"{nome_legivel(ag[i]['nome'])} · {ag[i]['acesso']} · "
                                             f"{ag[i]['procedimento']}"
                       + (f"  [DICOM: {ag[i]['nome']}]" if visao == "Técnico" else ""))
    return ag[idx]


def _tela_suporte(d, chave, dest, visao):
    st.title("Enviar exame")
    eqs = profiles.equipamentos(d)

    # ---- passo 1: onde enviar
    _passo(1, "Onde enviar")
    cx = C.status_conexao(chave, dest, st.session_state.get("aet_diag") or eqs[0].aet)
    a, b = st.columns([4, 1])
    a.markdown(f"{'🟢' if cx['ok'] else '🔴'} **{chave}** — {dest.pacs} · {cx['msg']}")
    a.caption("Para trocar de destino, use a lista **Destino** na barra lateral.")
    if b.button("Testar de novo", key="ex_testar"):
        C.status_conexao(chave, dest, st.session_state.get("aet_diag") or eqs[0].aet, forcar=True)
        st.rerun()
    if not cx["ok"]:
        st.warning("A conexão com este destino não está funcionando. Veja o motivo na página "
                   "**Diagnóstico** antes de enviar.")

    # ---- passo 2: o que enviar
    _passo(2, "O que enviar")
    c1, c2 = st.columns(2)
    nome = c1.selectbox("Equipamento (de qual aparelho vem o exame)", [e.nome for e in eqs], key="ex_eq",
                        format_func=lambda n: C.rotulo_equipamento(next(e for e in eqs if e.nome == n)),
                        help=C.AJUDA["ae"])
    eq = next(e for e in eqs if e.nome == nome)
    st.session_state["aet_diag"] = eq.aet
    opcoes = (["agenda"] if dest.ris is not None else []) + ["cadastrado", "automatico"]
    fonte = c2.radio("Paciente do exame", opcoes, key="ex_fonte",
                     format_func=lambda v: {"agenda": "Da agenda (worklist)", "cadastrado": "Paciente cadastrado",
                                            "automatico": "Paciente de teste automático"}[v])
    item, usar_wl = None, False
    if fonte == "agenda":
        usar_wl = True
        item = _agenda(eq, dest, visao)
    elif fonte == "cadastrado":
        item = C.escolher_paciente(d, eq.modalidade)

    # ---- passo 3: imagens
    _passo(3, "Imagens")
    i1, i2 = st.columns(2)
    eq.origem_imagens = i1.radio(
        "Que imagens enviar?", ["real", "anomala", "sintetica"], key="ex_origem", horizontal=False,
        format_func=lambda v: {"real": "Reais e anonimizadas", "anomala": "Anômalas (teste de robustez)",
                               "sintetica": "Sintéticas"}[v], help=C.AJUDA["anomala"])
    eq.identidade = i2.radio(
        "Como identificar as imagens?", ["novo", "sobrepor"], key="ex_ident",
        format_func=lambda v: {"novo": "Como NOVAS (sempre imagem nova no PACS)",
                               "sobrepor": "SOBREPOR o último envio (mesmos identificadores)"}[v],
        help=C.AJUDA["novo"] + "\n\n" + C.AJUDA["sobrepor"])
    resumo = " + ".join(f"{s['descricao']} ({s['imagens']})" for s in eq.series)
    st.caption(f"O equipamento enviará: {resumo}")

    with st.expander("Opções avançadas"):
        x1, x2, x3 = st.columns(3)
        eq.mpps = x1.checkbox("Avisar início e fim do exame (MPPS)", eq.mpps, help=C.AJUDA["mpps"], key="ex_mpps")
        eq.commitment = x2.checkbox("Pedir confirmação de gravação (Storage Commitment)", eq.commitment,
                                    help=C.AJUDA["commitment"], key="ex_comm")
        eq.imprimir = x3.checkbox("Imprimir filme", eq.imprimir, key="ex_print")

    extra = {}
    if visao == "Técnico":
        eq, dest, item, usar_wl, extra = _controle_total(d, chave, eq, dest, item, usar_wl)

    if st.button("▶ Enviar exame", type="primary", width="stretch"):
        _executar(eq, dest, item, usar_wl, extra, visao)
    if "ultimo" in st.session_state:
        st.divider()
        C.semaforo(st.session_state["ultimo"], visao)


# ----------------------------------------------------------------------------- Técnico
def _controle_total(d, chave_dest, eq, dest, item, usar_wl):
    extra = {}
    with st.expander("🔧 Controle total (Técnico)"):
        sj = st.text_area("Séries (JSON)", json.dumps(eq.series, ensure_ascii=False), height=90, key="tec_series")
        try:
            eq.series = json.loads(sj)
        except Exception:
            st.warning("JSON de séries inválido; usando o do perfil.")
        st.markdown("**Conexão**")
        t1, t2, t3, t4 = st.columns(4)
        eq.aet = t1.text_input("AE Title de origem", eq.aet, max_chars=16,
                               help="Muda só neste exame. Para gravar, use Cadastros.")
        TIMEOUTS["acse"] = t2.number_input("Timeout associação (s)", 1, 300, TIMEOUTS["acse"])
        TIMEOUTS["dimse"] = t3.number_input("Timeout DIMSE (s)", 1, 600, TIMEOUTS["dimse"])
        eq.porta_escuta = t4.number_input("Porta de retorno do commitment", 0, 65535, eq.porta_escuta,
                                          help="0 = automática por AE Title")
        st.markdown("**Destino deste exame** (altere à vontade; só grava se você pedir)")
        novos = {}
        for rot, ch, alvo in (("PACS", "pacs", dest.pacs), ("RIS", "ris", dest.ris),
                              ("Impressora", "impressora", dest.impressora)):
            alvo = alvo or Alvo("", "", 104)
            q1, q2, q3 = st.columns([2, 2, 1])
            novos[ch] = {"aet": q1.text_input(f"{rot} · AE Title", alvo.aet, key=f"x_{ch}_a"),
                         "ip": q2.text_input(f"{rot} · IP", alvo.ip, key=f"x_{ch}_i"),
                         "porta": int(q3.number_input(f"{rot} · Porta", 1, 65535, alvo.porta, key=f"x_{ch}_p"))}

        def _alvo(v):
            return Alvo(v["aet"], v["ip"], v["porta"]) if v["aet"] and v["ip"] else None
        dest = profiles.Destino(_alvo(novos["pacs"]) or dest.pacs, _alvo(novos["ris"]),
                                _alvo(novos["impressora"]))
        if st.button("Salvar estes valores no destino selecionado"):
            d["destinos"][chave_dest] = {k: v for k, v in novos.items() if v["aet"] and v["ip"]}
            profiles.salvar(d)
            st.success(f"Destino '{chave_dest}' atualizado.")
        st.markdown("**Worklist** (filtros da consulta)")
        w1, w2, w3, w4 = st.columns(4)
        extra["filtros_wl"] = {"modalidade": w1.text_input("Modalidade", eq.modalidade),
                               "data": w2.text_input("Data (AAAAMMDD)", ""),
                               "paciente": w3.text_input("Paciente (aceita *)", ""),
                               "estacao": w4.text_input("Station AE Title", "")}
        st.markdown("**Imagens**")
        todas = {}
        for m in library.manifesto():
            if m.get("tag") == eq.modalidade or st.session_state.get("tec_todas"):
                todas[f"manifesto · {m['arquivo']}"] = library.PASTA_ENVIO / m["arquivo"]
        for f in library.listar_reais(eq.modalidade):
            todas.setdefault(f"{f.parent.name} · {f.name}", f)
        for f in library.listar_anomalas():
            todas[f"ANOMALA · {f.name}"] = f
        st.checkbox("Listar arquivos de todas as modalidades", key="tec_todas")
        esc = st.multiselect("Enviar estes arquivos (vazio = usar a biblioteca)", list(todas))
        up = st.file_uploader("Ou envie seus próprios .dcm", type=["dcm"], accept_multiple_files=True)
        arqs = [todas[e] for e in esc]
        if up:
            pasta = Path(tempfile.mkdtemp(prefix="dicomsim_up_"))
            for u in up:
                (pasta / u.name).write_bytes(u.getvalue())
                arqs.append(pasta / u.name)
        if arqs:
            extra["arquivos"] = arqs
        st.markdown("**Exame e paciente**")
        m1, m2 = st.columns(2)
        extra["status_mpps"] = {"Automático": None, "Forçar COMPLETED": "COMPLETED",
                                "Forçar DISCONTINUED": "DISCONTINUED"}[
            m1.selectbox("Status final do MPPS", ["Automático", "Forçar COMPLETED", "Forçar DISCONTINUED"])]
        if m2.checkbox("Informar paciente manualmente"):
            p1, p2, p3, p4 = st.columns(4)
            item = {"nome": p1.text_input("Nome (SOBRENOME^NOME)", "TESTE^MANUAL"),
                    "id": p2.text_input("ID do paciente", "MAN0001"),
                    "acesso": p3.text_input("Accession", "MANACC1"),
                    "estudo_uid": p4.text_input("Study UID (vazio = novo)", ""),
                    "modalidade": eq.modalidade, "procedimento": "Exame manual",
                    "nascimento": "", "sexo": "O", "passo": "SPS1", "proc_id": "REQ1", "data": ""}
            usar_wl = False
        extra["vezes"] = int(st.number_input("Repetir o exame N vezes", 1, 200, 1))
    return eq, dest, item, usar_wl, extra


# ----------------------------------------------------------------------------- página
def pg_enviar():
    d = C.dados()
    chave, dest = C.destino_ativo()
    visao = C.modo()
    if visao == "Cliente":
        _tela_cliente(d, chave, dest)
    else:
        _tela_suporte(d, chave, dest, visao)
