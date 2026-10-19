"""Simulador de Modalidades DICOM — tela nova (usa o núcleo dicomsim).

Três visões, escolhidas na barra lateral:
  Cliente  — um botão por fluxo, resultado em semáforo, sem jargão
  Suporte  — guiado: escolhe exame da worklist, vê o que fazer quando falha
  Técnico  — tudo: eventos brutos, UIDs, séries, JSON dos perfis

Iniciar:  streamlit run app_simulador.py
"""
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import streamlit as st

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from dicomsim import profiles, steps                      # noqa: E402
from dicomsim.events import Emissor                       # noqa: E402
from dicomsim.exam import executar_exame                  # noqa: E402
from dicomsim.fleet import rodar_frota                    # noqa: E402
from dicomsim.netutil import Alvo                         # noqa: E402
from dicomsim.servers import ServidorVirtual              # noqa: E402

HIST = BASE / "relatorios" / "historico.jsonl"
HIST.parent.mkdir(exist_ok=True)

ROTULO = {"worklist": "Buscar exame na agenda (worklist)",
          "mpps-inicio": "Avisar início do exame (MPPS)",
          "store": "Enviar imagens ao PACS",
          "mpps-fim": "Avisar fim do exame (MPPS)",
          "commitment": "Confirmação de gravação (Storage Commitment)",
          "print": "Imprimir filme", "fim": "Resultado final", "inicio": "Início"}

DICAS = {
    "associação recusada": "O destino não aceitou a conexão. Confira AE Title (maiúsculas/"
                           "minúsculas), IP e porta, firewall, e se o PACS cadastrou este "
                           "equipamento (AET de origem).",
    "0xA7": "O PACS recusou a imagem por falta de espaço/recursos. Verifique o disco do PACS.",
    "0xC": "O PACS não aceitou o cabeçalho da imagem (dados inválidos/duplicados).",
    "0x0112": "O PACS não conhece este exame (MPPS). Rode o início antes do fim.",
    "sem N-EVENT-REPORT": "O PACS aceitou o pedido mas não conseguiu responder. Cadastre no PACS "
                          "o AET e a porta de retorno deste equipamento.",
}

st.set_page_config(page_title="Simulador de Modalidades DICOM", page_icon="🩻", layout="wide")


# ------------------------------------------------------------------ estado
@st.cache_resource
def servidor_virtual():
    return {"srv": None}


def dados():
    return profiles.carregar()


def salvar_hist(reg):
    with open(HIST, "a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False, default=str) + "\n")


def ler_hist(n=50):
    if not HIST.exists():
        return []
    linhas = HIST.read_text(encoding="utf-8").strip().splitlines()[-n:]
    return [json.loads(x) for x in reversed(linhas)]


def dica_para(ev):
    for chave, txt in DICAS.items():
        if chave in ev.detalhe:
            return txt
    return ""


def semaforo(em: Emissor, modo):
    """Mostra o resultado do exame de acordo com a visão."""
    if em.ok:
        st.success("Exame concluído: tudo foi entregue.")
    else:
        st.error("O exame teve falhas.")
    eventos = em.eventos
    if modo != "Técnico":   # junta as imagens de uma etapa numa linha só
        agrupados = []
        for ev in eventos:
            if agrupados and agrupados[-1].etapa == ev.etapa == "store" and                     agrupados[-1].status == ev.status:
                agrupados[-1] = replace(agrupados[-1], detalhe="várias imagens")
                continue
            agrupados.append(ev)
        eventos = agrupados
    for ev in eventos:
        if ev.status == "info" and modo != "Técnico":
            continue
        icone = {"ok": "🟢", "falha": "🔴", "aviso": "🟡", "pulado": "⚪", "info": "🔹"}[ev.status]
        nome = ROTULO.get(ev.etapa, ev.etapa) if modo != "Técnico" else f"{ev.etapa}"
        txt = f"{icone} **{nome}**"
        if modo != "Cliente" or ev.status == "falha":
            txt += f" — {ev.detalhe}"
        st.markdown(txt)
        if ev.status == "falha" and modo != "Técnico":
            d = dica_para(ev)
            if d:
                st.caption(f"💡 {d}")
    if modo == "Técnico":
        with st.expander("Eventos brutos (JSON)"):
            st.json([{"etapa": e.etapa, "status": e.status, "detalhe": e.detalhe,
                      "dados": e.dados} for e in em.eventos])


# ------------------------------------------------------------------ páginas
def pg_exame():
    modo = st.session_state["modo"]
    d = dados()
    eqs = profiles.equipamentos(d)
    st.title("Fazer um exame")
    st.caption("O equipamento virtual faz o que uma modalidade real faz: busca o exame na "
               "agenda, avisa o início, envia as imagens, avisa o fim e confirma a gravação.")
    nomes = [e.nome for e in eqs]
    c1, c2 = st.columns(2)
    nome = c1.selectbox("Equipamento", nomes, format_func=lambda n: f"{n}  ·  {next(e.modalidade for e in eqs if e.nome == n)}")
    eq = profiles.equipamento(d, nome)
    chave_dest = c2.selectbox("Destino (PACS)", list(d["destinos"].keys()),
                              index=list(d["destinos"].keys()).index(eq.destino)
                              if eq.destino in d["destinos"] else 0)
    dest = profiles.destino(d, chave_dest)
    st.caption(f"{eq.modalidade} · {eq.fabricante} {eq.modelo} · AE Title **{eq.aet}** → "
               f"PACS **{dest.pacs}**")

    usar_wl, item = True, None
    if modo in ("Suporte", "Técnico"):
        a, b, c = st.columns(3)
        eq.mpps = a.checkbox("MPPS", eq.mpps)
        eq.commitment = b.checkbox("Storage Commitment", eq.commitment)
        eq.imprimir = c.checkbox("Imprimir filme", eq.imprimir)
        d1, d2 = st.columns(2)
        eq.identidade = d1.radio(
            "Identificadores das imagens", ["novo", "sobrepor"], horizontal=True,
            format_func=lambda v: {"novo": "Enviar como NOVO (UIDs inéditos)",
                                   "sobrepor": "SOBREPOR o último envio (mesmos UIDs)"}[v],
            help="Novo: o PACS sempre recebe imagem nova. Sobrepor: reenvia a mesma "
                 "instância do último exame deste equipamento (testa duplicata/substituição).")
        eq.origem_imagens = d2.radio(
            "Imagens", ["real", "anomala", "sintetica"], horizontal=True,
            format_func=lambda v: {"real": "Reais anonimizadas", "anomala": "Anômalas (teste negativo)",
                                   "sintetica": "Sintéticas"}[v])
        usar_wl = st.checkbox("Buscar exame na worklist (RIS)", True and dest.ris is not None,
                              disabled=dest.ris is None)
        if usar_wl and dest.ris is not None:
            qualquer = st.checkbox("Mostrar todas as modalidades da agenda deste AE Title", False)
            if st.button("Ver agenda"):
                em0 = Emissor(imprimir=False)
                st.session_state["agenda"] = steps.consultar_worklist(
                    em0, eq.aet, dest.ris, modalidade="" if qualquer else eq.modalidade) or []
            ag = st.session_state.get("agenda", [])
            if "agenda" in st.session_state and not ag:
                st.warning(f"Nenhum exame agendado para o AE Title **{eq.aet}** e modalidade "
                           f"**{eq.modalidade}**. A maioria dos RIS só devolve a agenda do AE "
                           f"Title que pergunta: confira se o equipamento no RIS tem este mesmo AE Title.")
            if ag:
                idx = st.selectbox("Exame da agenda", range(len(ag)),
                                   format_func=lambda i: f"{ag[i]['nome']} · {ag[i]['acesso']} · "
                                                         f"{ag[i]['procedimento']}")
                item = ag[idx]
    extra = {}
    if modo == "Técnico":
        sj = st.text_area("Séries (JSON)", json.dumps(eq.series, ensure_ascii=False), height=90)
        try:
            eq.series = json.loads(sj)
        except Exception:
            st.warning("JSON de séries inválido; usando o do perfil.")
        with st.expander("🔧 Controle total (Técnico)", expanded=False):
            from dicomsim import library
            from dicomsim.netutil import Alvo, TIMEOUTS
            st.markdown("**Conexão**")
            t1, t2, t3, t4 = st.columns(4)
            eq.aet = t1.text_input("AE Title de origem", eq.aet, max_chars=16,
                                   help="Muda só neste exame. Para gravar, use Equipamentos e destinos.")
            TIMEOUTS["acse"] = t2.number_input("Timeout associação (s)", 1, 300, TIMEOUTS["acse"])
            TIMEOUTS["dimse"] = t3.number_input("Timeout DIMSE (s)", 1, 600, TIMEOUTS["dimse"])
            eq.porta_escuta = t4.number_input("Porta de retorno do commitment", 0, 65535,
                                              eq.porta_escuta, help="0 = automática por AE Title")
            st.markdown("**Destino deste exame** (altere à vontade; só grava se você pedir)")
            novos = {}
            for rot, chave, alvo in (("PACS", "pacs", dest.pacs), ("RIS", "ris", dest.ris),
                                     ("Impressora", "impressora", dest.impressora)):
                alvo = alvo or Alvo("", "", 104)
                q1, q2, q3 = st.columns([2, 2, 1])
                novos[chave] = {"aet": q1.text_input(f"{rot} · AE Title", alvo.aet, key=f"x_{chave}_a"),
                                "ip": q2.text_input(f"{rot} · IP", alvo.ip, key=f"x_{chave}_i"),
                                "porta": int(q3.number_input(f"{rot} · Porta", 1, 65535, alvo.porta,
                                                              key=f"x_{chave}_p"))}
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
            extra["filtros_wl"] = {
                "modalidade": w1.text_input("Modalidade", eq.modalidade),
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
                import tempfile
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
                m1.selectbox("Status final do MPPS", ["Automático", "Forçar COMPLETED",
                                                      "Forçar DISCONTINUED"])]
            if m2.checkbox("Informar paciente manualmente"):
                p1, p2, p3, p4 = st.columns(4)
                item = {"nome": p1.text_input("Nome (SOBRENOME^NOME)", "TESTE^MANUAL"),
                        "id": p2.text_input("ID do paciente", "MAN0001"),
                        "acesso": p3.text_input("Accession", "MANACC1"),
                        "estudo_uid": p4.text_input("Study UID (vazio = novo)", ""),
                        "modalidade": eq.modalidade, "procedimento": "Exame manual",
                        "nascimento": "", "sexo": "O", "passo": "SPS1", "proc_id": "REQ1", "data": ""}
                usar_wl = False
            vezes = st.number_input("Repetir o exame N vezes", 1, 200, 1)
            extra["vezes"] = int(vezes)

    if st.button("▶ Realizar exame", type="primary", use_container_width=True):
        vezes = extra.pop("vezes", 1)
        for n in range(vezes):
            em = Emissor(nome=eq.nome, imprimir=False)
            with st.spinner(f"Realizando exame {n + 1}/{vezes}..."):
                r = executar_exame(eq, dest, item=item, em=em, usar_worklist=usar_wl, **extra)
            st.session_state["ultimo"] = em
            salvar_hist({"quando": datetime.now().isoformat(timespec="seconds"),
                         "equipamento": eq.nome, "destino": str(dest.pacs), "ok": r.ok,
                         "imagens": r.imagens, "paciente": r.paciente,
                         "etapas": em.resumo()["etapas"]})
    if "ultimo" in st.session_state:
        semaforo(st.session_state["ultimo"], modo)


def pg_frota():
    d = dados()
    eqs = profiles.equipamentos(d)
    st.title("Vários equipamentos ao mesmo tempo")
    st.caption("Cada equipamento roda em paralelo, com o seu próprio AE Title — ótimo para "
               "teste de carga e para ver como o PACS lida com fontes simultâneas.")
    sel = st.multiselect("Equipamentos", [e.nome for e in eqs], default=[e.nome for e in eqs])
    c1, c2 = st.columns(2)
    n = c1.number_input("Exames por equipamento", 1, 50, 2)
    chave = c2.selectbox("Destino", list(d["destinos"].keys()))
    if st.button("▶ Iniciar frota", type="primary", disabled=not sel):
        escolhidos = [e for e in eqs if e.nome in sel]
        dest = profiles.destino(d, chave)
        barra = st.progress(0.0, text="Rodando...")
        feitos = {"n": 0}
        total = len(escolhidos) * int(n)

        def cb(ev):
            if ev.etapa == "fim":
                feitos["n"] += 1
                barra.progress(min(1.0, feitos["n"] / total), text=f"{feitos['n']}/{total} exames")

        res = rodar_frota(escolhidos, dest, int(n), callback=cb)
        barra.progress(1.0, text="Concluído")
        st.dataframe([{"equipamento": r.equipamento, "ok": "🟢" if r.ok else "🔴",
                       "imagens": r.imagens, "paciente": r.paciente} for r in res],
                     hide_index=True, use_container_width=True)
        salvar_hist({"quando": datetime.now().isoformat(timespec="seconds"),
                     "equipamento": f"FROTA ({len(escolhidos)}x{n})", "destino": str(dest.pacs),
                     "ok": all(r.ok for r in res), "imagens": sum(r.imagens for r in res),
                     "paciente": "", "etapas": []})


def pg_servidor():
    st.title("Servidor virtual")
    st.caption("PACS + RIS + MPPS + Commitment + Impressora numa só porta, para testar sem "
               "equipamento real. As imagens ficam na pasta indicada.")
    cache = servidor_virtual()
    srv = cache["srv"]
    if srv is None:
        c1, c2 = st.columns(2)
        aet = c1.text_input("AE Title", "PACS_TESTE")
        porta = c2.number_input("Porta", 1024, 65535, 11112)
        if st.button("Iniciar servidor", type="primary"):
            try:
                cache["srv"] = ServidorVirtual(aet, int(porta), BASE / "received").iniciar()
                st.rerun()
            except OSError as e:
                st.error(f"Não foi possível abrir a porta: {e}")
    else:
        st.success(f"Rodando: {srv.aet} @ 127.0.0.1:{srv.porta}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Imagens recebidas", len(srv.instancias))
        c2.metric("Exames (MPPS)", len(srv.mpps))
        c3.metric("Filmes impressos", len(srv.filmes))
        if st.session_state["modo"] == "Técnico":
            st.code("\n".join(srv.log[-40:]) or "(sem eventos)")
        if st.button("Parar servidor"):
            srv.parar()
            cache["srv"] = None
            st.rerun()
        st.button("Atualizar")


def pg_config():
    from ui_cadastros import tela_destinos, tela_equipamentos
    st.title("Equipamentos e destinos")
    st.caption("Cadastre os aparelhos que serão simulados e os servidores (PACS, RIS, impressora) "
               "para onde eles enviam.")
    aba_eq, aba_dest = st.tabs(["Equipamentos", "Destinos"])
    with aba_eq:
        tela_equipamentos()
    with aba_dest:
        tela_destinos()
    if st.session_state["modo"] == "Técnico":
        with st.expander("Editar perfis.json (avançado)"):
            txt = st.text_area("perfis.json", json.dumps(dados(), indent=2, ensure_ascii=False),
                               height=420)
            if st.button("Salvar JSON"):
                try:
                    profiles.salvar(json.loads(txt))
                    st.success("Salvo.")
                except Exception as e:
                    st.error(f"JSON inválido: {e}")


def pg_resultados():
    st.title("Resultados")
    h = ler_hist()
    if not h:
        st.info("Nenhum exame feito ainda.")
        return
    ok = sum(1 for x in h if x["ok"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Execuções", len(h))
    c2.metric("Com sucesso", ok)
    c3.metric("Com falha", len(h) - ok)
    st.dataframe([{"quando": x["quando"], "equipamento": x["equipamento"],
                   "destino": x["destino"], "resultado": "🟢" if x["ok"] else "🔴",
                   "imagens": x["imagens"]} for x in h], hide_index=True,
                 use_container_width=True)
    if st.session_state["modo"] == "Técnico":
        with st.expander("Histórico bruto"):
            st.json(h)


# ------------------------------------------------------------------ navegação
with st.sidebar:
    st.markdown("### 🩻 Simulador DICOM")
    st.session_state["modo"] = st.radio(
        "Visão", ["Cliente", "Suporte", "Técnico"], index=1, horizontal=True,
        help="Cliente: simples · Suporte: guiado · Técnico: completo")

paginas = [st.Page(pg_exame, title="Fazer um exame", icon="🩻", default=True)]
if st.session_state["modo"] != "Cliente":
    paginas += [st.Page(pg_frota, title="Vários equipamentos", icon="🚑"),
                st.Page(pg_servidor, title="Servidor virtual", icon="🖥")]
paginas += [st.Page(pg_config, title="Equipamentos e destinos", icon="⚙"),
            st.Page(pg_resultados, title="Resultados", icon="📋")]
st.navigation(paginas).run()
