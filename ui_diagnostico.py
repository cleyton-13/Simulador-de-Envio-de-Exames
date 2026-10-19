"""Diagnóstico guiado: por que não conecta?"""
from datetime import datetime

import streamlit as st

from dicomsim import diagnostico, profiles

import ui_comum as C


def pg_diagnostico():
    d = C.dados()
    visao = C.modo()
    chave, dest = C.destino_ativo()
    eqs = profiles.equipamentos(d)
    st.title("Diagnóstico de conexão")
    st.caption(f"Responde, passo a passo, por que um equipamento não consegue falar com **{chave}** "
               f"({dest.pacs}). Para trocar de destino, use a lista na barra lateral.")

    c1, c2 = st.columns(2)
    nome = c1.selectbox("Equipamento a testar", [e.nome for e in eqs], key="dg_eq",
                        format_func=lambda n: C.rotulo_equipamento(next(e for e in eqs if e.nome == n)))
    eq = next(e for e in eqs if e.nome == nome)
    aet = eq.aet
    if visao == "Técnico":
        aet = c2.text_input("AE Title de origem", eq.aet, max_chars=16, key="dg_aet")
    else:
        c2.markdown(f"AE Title de origem: **{eq.aet}**")
    envio = st.checkbox("Incluir um envio de teste (grava 1 imagem pequena 'DIAGNOSTICO^SIMULADOR' no PACS)",
                        False, key="dg_envio")

    if st.button("▶ Executar diagnóstico", type="primary", width="stretch"):
        with st.spinner("Testando..."):
            passos = diagnostico.diagnosticar(aet, dest, eq.modalidade, testar_envio=envio)
        st.session_state["diag"] = {"passos": passos, "aet": aet, "eq": eq.nome, "chave": chave}
        C.salvar_hist({"quando": datetime.now().isoformat(timespec="seconds"), "equipamento": eq.nome,
                       "destino": str(dest.pacs), "ok": diagnostico.conexao_ok(passos), "imagens": 0,
                       "paciente": "(diagnóstico)",
                       "etapas": [{"etapa": p.id, "status": p.status, "detalhe": p.detalhe} for p in passos]})

    res = st.session_state.get("diag")
    if not res:
        return
    passos = res["passos"]
    st.divider()
    if diagnostico.conexao_ok(passos):
        st.success("A conexão com o PACS está funcionando.")
    else:
        st.error("A conexão com o PACS NÃO está funcionando. Veja o primeiro passo em vermelho.")
    C.mostrar_passos(passos)
    texto = diagnostico.relatorio_texto(passos, res["aet"], dest, res["eq"])
    st.markdown("**Resumo para copiar e enviar** (chamado, e-mail ou mensagem)")
    st.code(texto, language="text")
    st.download_button("Baixar resumo (.txt)", texto, file_name=f"diagnostico_{res['aet']}.txt")
