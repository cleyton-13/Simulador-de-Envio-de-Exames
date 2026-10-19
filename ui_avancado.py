"""Páginas de apoio: Cadastros, Histórico e (Técnico) Vários equipamentos e Servidor virtual."""
import json
from datetime import datetime

import streamlit as st

from dicomsim import profiles
from dicomsim.fleet import rodar_frota
from dicomsim.servers import ServidorVirtual
from dicomsim.util import nome_legivel

import ui_comum as C


def pg_cadastros():
    from ui_cadastros import tela_destinos, tela_equipamentos, tela_pacientes
    st.title("Cadastros")
    st.caption("Os aparelhos que serão simulados, os servidores para onde enviam e os pacientes de teste.")
    aba_eq, aba_dest, aba_pac = st.tabs(["Equipamentos", "Destinos", "Pacientes"])
    with aba_eq:
        tela_equipamentos()
    with aba_dest:
        tela_destinos()
    with aba_pac:
        tela_pacientes()
    if C.modo() == "Técnico":
        with st.expander("Editar perfis.json (avançado)"):
            txt = st.text_area("perfis.json", json.dumps(C.dados(), indent=2, ensure_ascii=False), height=420)
            if st.button("Salvar JSON"):
                try:
                    profiles.salvar(json.loads(txt))
                    st.success("Salvo.")
                except Exception as e:
                    st.error(f"JSON inválido: {e}")


def pg_resultados():
    st.title("Histórico")
    h = C.ler_hist()
    if not h:
        st.info("Nada foi enviado ainda.")
        return
    ok = sum(1 for x in h if x["ok"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Execuções", len(h))
    c2.metric("Com sucesso", ok)
    c3.metric("Com falha", len(h) - ok)
    st.dataframe([{"quando": x["quando"], "equipamento": x["equipamento"], "destino": x["destino"],
                   "resultado": "🟢" if x["ok"] else "🔴", "imagens": x["imagens"]} for x in h],
                 hide_index=True, width="stretch")
    if C.modo() == "Técnico":
        with st.expander("Histórico bruto"):
            st.json(h)


def pg_frota():
    d = C.dados()
    chave, dest = C.destino_ativo()
    eqs = profiles.equipamentos(d)
    st.title("Vários equipamentos ao mesmo tempo")
    st.caption(f"Cada equipamento roda em paralelo, com o seu AE Title, enviando para **{chave}** ({dest.pacs}).")
    sel = st.multiselect("Equipamentos", [e.nome for e in eqs], default=[e.nome for e in eqs])
    n = st.number_input("Exames por equipamento", 1, 50, 2)
    if st.button("▶ Iniciar", type="primary", disabled=not sel):
        escolhidos = [e for e in eqs if e.nome in sel]
        barra = st.progress(0.0, text="Rodando...")
        feitos, total = {"n": 0}, len(escolhidos) * int(n)

        def cb(ev):
            if ev.etapa == "fim":
                feitos["n"] += 1
                barra.progress(min(1.0, feitos["n"] / total), text=f"{feitos['n']}/{total} exames")
        res = rodar_frota(escolhidos, dest, int(n), callback=cb)
        barra.progress(1.0, text="Concluído")
        st.dataframe([{"equipamento": r.equipamento, "ok": "🟢" if r.ok else "🔴", "imagens": r.imagens,
                       "paciente": nome_legivel(r.paciente)} for r in res],
                     hide_index=True, width="stretch")
        C.salvar_hist({"quando": datetime.now().isoformat(timespec="seconds"),
                       "equipamento": f"FROTA ({len(escolhidos)}x{n})", "destino": str(dest.pacs),
                       "ok": all(r.ok for r in res), "imagens": sum(r.imagens for r in res),
                       "paciente": "", "etapas": []})


def pg_servidor():
    st.title("Servidor virtual")
    st.caption("PACS + RIS + MPPS + Commitment + Impressora numa só porta, para testar sem equipamento real.")
    cache = C.servidor_virtual()
    srv = cache["srv"]
    if srv is None:
        c1, c2 = st.columns(2)
        aet = c1.text_input("AE Title", "PACS_TESTE")
        porta = c2.number_input("Porta", 1024, 65535, 11112)
        if st.button("Iniciar servidor", type="primary"):
            try:
                cache["srv"] = ServidorVirtual(aet, int(porta), C.BASE / "received").iniciar()
                st.rerun()
            except OSError as e:
                st.error(f"Não foi possível abrir a porta: {e}")
    else:
        st.success(f"Rodando: {srv.aet} @ 127.0.0.1:{srv.porta}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Imagens recebidas", len(srv.instancias))
        c2.metric("Exames (MPPS)", len(srv.mpps))
        c3.metric("Filmes impressos", len(srv.filmes))
        st.code("\n".join(srv.log[-40:]) or "(sem eventos)")
        if st.button("Parar servidor"):
            srv.parar()
            cache["srv"] = None
            st.rerun()
        st.button("Atualizar")
