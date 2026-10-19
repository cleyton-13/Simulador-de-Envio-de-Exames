"""Início: estado do destino e cenários prontos de um clique."""
from datetime import datetime

import streamlit as st

from dicomsim import cenarios, profiles
from dicomsim.cenarios import PRECISA_EQUIPAMENTO

import ui_comum as C


def _mostrar_resultado(r, visao):
    if r["tipo"] == "diagnostico":
        (st.success if r["ok"] else st.error)(
            "A conexão com o PACS está funcionando." if r["ok"] else "A conexão com o PACS NÃO está funcionando.")
        C.mostrar_passos(r["passos"])
    elif r["tipo"] == "frota":
        res = r["resultados"]
        (st.success if r["ok"] else st.error)(
            f"{sum(x.ok for x in res)} de {len(res)} exames concluídos sem falha.")
        st.dataframe([{"equipamento": x.equipamento, "resultado": "🟢" if x.ok else "🔴",
                       "imagens": x.imagens} for x in res], hide_index=True, width="stretch")
    else:
        C.semaforo(r["emissor"], visao)


def pg_inicio():
    d = C.dados()
    visao = C.modo()
    chave, dest = C.destino_ativo()
    eqs = profiles.equipamentos(d)
    st.title("Início")

    # ---- estado do destino
    aet = st.session_state.get("aet_diag") or eqs[0].aet
    cx = C.status_conexao(chave, dest, aet)
    a, b = st.columns([4, 2])
    with a:
        st.markdown(f"### {'🟢' if cx['ok'] else '🔴'} {chave}")
        st.caption(f"PACS {dest.pacs}" + (f" · RIS {dest.ris}" if dest.ris else "")
                   + f" · testado com o AE Title {aet} · {cx['msg']}")
    if b.button("Testar agora", width="stretch"):
        C.status_conexao(chave, dest, aet, forcar=True)
        st.rerun()
    if not cx["ok"]:
        st.warning("Sem conexão com este destino. Abra o **Diagnóstico** para ver o motivo.")

    # ---- cenários
    st.subheader("O que você quer fazer?")
    st.caption("Escolha uma receita pronta. Para personalizar tudo, use **Enviar exame**.")
    lista = cenarios.lista(d)
    cols = st.columns(3)
    for i, c in enumerate(lista):
        with cols[i % 3].container(border=True):
            st.markdown(f"**{c.get('icone', '▶')} {c['nome']}**")
            st.caption(c.get("descricao", ""))
            eq = None
            if c["tipo"] in PRECISA_EQUIPAMENTO:
                nomes = [e.nome for e in eqs]
                padrao = next((e.nome for e in eqs if e.modalidade == c.get("modalidade")), nomes[0])
                nome = st.selectbox("Equipamento", nomes, index=nomes.index(padrao), key=f"cen_eq_{c['id']}",
                                    format_func=lambda n: C.rotulo_equipamento(next(e for e in eqs if e.nome == n)))
                eq = next(e for e in eqs if e.nome == nome)
            if st.button("Executar", key=f"cen_{c['id']}", type="primary", width="stretch"):
                with st.spinner(f"Executando: {c['nome']}..."):
                    r = cenarios.executar(c, d, eq, dest)
                st.session_state["cenario_res"] = {"nome": c["nome"], "r": r}
                if r["tipo"] in ("exame", "agenda", "reenviar"):
                    C.salvar_hist({"quando": datetime.now().isoformat(timespec="seconds"),
                                   "equipamento": eq.nome, "destino": str(dest.pacs), "ok": r["ok"],
                                   "imagens": r["resultado"].imagens, "paciente": "",
                                   "etapas": r["emissor"].resumo()["etapas"]})
    if "cenario_res" in st.session_state:
        st.divider()
        st.subheader(st.session_state["cenario_res"]["nome"])
        _mostrar_resultado(st.session_state["cenario_res"]["r"], visao)

    # ---- últimos resultados
    h = C.ler_hist(5)
    if h:
        st.subheader("Últimos envios")
        st.dataframe([{"quando": x["quando"], "equipamento": x["equipamento"], "destino": x["destino"],
                       "resultado": "🟢" if x["ok"] else "🔴", "imagens": x["imagens"]} for x in h],
                     hide_index=True, width="stretch")
