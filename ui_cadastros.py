"""Telas de cadastro: destinos (PACS/RIS/impressora) e equipamentos, sem editar JSON."""
import streamlit as st

from dicomsim import profiles

NOVO = "➕ Novo..."


def _bloco_alvo(rotulo, atual, chave, padrao_aet="", obrigatorio=True):
    c1, c2, c3 = st.columns([2, 2, 1])
    aet = c1.text_input(f"{rotulo} — AE Title", (atual or {}).get("aet", padrao_aet), key=f"{chave}_aet")
    ip = c2.text_input(f"{rotulo} — IP ou nome", (atual or {}).get("ip", ""), key=f"{chave}_ip")
    porta = c3.number_input(f"{rotulo} — Porta", 1, 65535, int((atual or {}).get("porta", 104)),
                            key=f"{chave}_porta")
    return {"aet": aet, "ip": ip, "porta": int(porta)}


def _opcional(rotulo, atual, pacs, chave):
    """RIS / impressora: mesmo servidor do PACS, outro servidor ou nenhum."""
    if atual is None:
        padrao = 2
    elif atual == pacs:
        padrao = 0
    else:
        padrao = 1
    modo = st.radio(rotulo, ["Mesmo servidor do PACS", "Outro servidor", "Não usar"],
                    index=padrao, horizontal=True, key=f"{chave}_modo")
    if modo.startswith("Mesmo"):
        return dict(pacs)
    if modo.startswith("Outro"):
        return _bloco_alvo(rotulo, atual if atual != pacs else None, chave)
    return None


def tela_destinos():
    d = profiles.carregar()
    nomes = list(d["destinos"].keys())
    if "_prox_dest" in st.session_state:      # só dá para trocar a seleção antes do widget existir
        st.session_state["dest_sel"] = st.session_state.pop("_prox_dest")
    escolha = st.selectbox("Destino", nomes + [NOVO], key="dest_sel")
    novo = escolha == NOVO
    k = "novo" if novo else escolha          # chave dos widgets: muda ao trocar de destino

    atual = None if novo else d["destinos"][escolha]
    if novo:
        modelo = st.selectbox("Começar a partir de um modelo", list(profiles.MODELOS_DESTINO),
                              key="dest_modelo")
        atual = profiles.destino_para_dict(profiles.MODELOS_DESTINO[modelo])
        k = f"novo_{modelo}"
    nome = st.text_input("Nome do destino", "" if novo else escolha, key=f"dn_{k}",
                         placeholder="ex.: Clínica Forge Code")
    st.markdown("**PACS** (onde as imagens são gravadas)")
    pacs = _bloco_alvo("PACS", atual["pacs"], f"dp_{k}")
    ris = _opcional("RIS / Worklist", atual.get("ris"), pacs, f"dr_{k}")
    imp = _opcional("Impressora de filme", atual.get("impressora"), pacs, f"di_{k}")

    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("Salvar", type="primary", key=f"ds_{k}"):
        try:
            dest = {"pacs": pacs}
            if ris:
                dest["ris"] = ris
            if imp:
                dest["impressora"] = imp
            profiles.salvar_destino(d, nome, dest, None if novo else escolha)
            profiles.salvar(d)
            st.session_state["_prox_dest"] = nome
            st.toast("Destino salvo.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if not novo:
        if c2.button("Excluir", key=f"dx_{k}"):
            try:
                profiles.excluir_destino(d, escolha)
                profiles.salvar(d)
                st.session_state["_prox_dest"] = list(d["destinos"])[0]
                st.toast("Destino excluído.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        usos = profiles.usos_do_destino(d, escolha)
        c3.caption(("Usado por: " + ", ".join(usos)) if usos else "Nenhum equipamento usa este destino.")

    with st.expander("Testar conexão com o PACS deste destino"):
        if st.button("Testar (C-ECHO)", key=f"dt_{k}"):
            from dicomsim.netutil import Alvo, associar, status_ok
            alvo = Alvo(pacs["aet"], pacs["ip"], pacs["porta"])
            with associar("SIMULADOR", alvo) as a_:
                if a_ is None:
                    st.error(f"Sem conexão com {alvo}. Confira AE Title, IP, porta e firewall; "
                             f"o PACS também precisa ter cadastrado o AE Title de origem.")
                else:
                    ok = status_ok(a_.send_c_echo())
                    (st.success if ok else st.error)(
                        f"{alvo} respondeu." if ok else "Respondeu com erro.")


def tela_equipamentos():
    d = profiles.carregar()
    nomes = [e["nome"] for e in d["equipamentos"]]
    mods = profiles.MODALIDADES
    if "_prox_eq" in st.session_state:
        st.session_state["eq_sel"] = st.session_state.pop("_prox_eq")
    escolha = st.selectbox(
        "Equipamento", nomes + [NOVO], key="eq_sel",
        format_func=lambda n: n if n == NOVO else
        f"{n}  ·  {next(e['modalidade'] for e in d['equipamentos'] if e['nome'] == n)}")
    novo = escolha == NOVO
    e = {"nome": "", "aet": "", "modalidade": "CT", "fabricante": "Generico", "setor": "",
         "destino": list(d["destinos"])[0], "series": [{"descricao": "SERIE 1", "imagens": 1}],
         "mpps": True, "commitment": False, "imprimir": False,
         "identidade": "novo", "origem_imagens": "real"}
    if not novo:
        e.update(next(x for x in d["equipamentos"] if x["nome"] == escolha))
    k = "novo" if novo else escolha

    c1, c2 = st.columns(2)
    nome = c1.text_input("Nome", e["nome"], key=f"en_{k}")
    aet = c2.text_input("AE Title (até 16 caracteres)", e["aet"], key=f"ea_{k}",
                        help="É o nome que o PACS vê. O PACS só aceita AE Titles cadastrados nele.")
    c3, c4, c5 = st.columns(3)
    mod = c3.selectbox("Modalidade", list(mods), index=list(mods).index(e["modalidade"])
                       if e["modalidade"] in mods else 0, format_func=lambda m: mods[m], key=f"em_{k}")
    fabs = list(d.get("fabricantes", {"Generico": {}}))
    fab = c4.selectbox("Fabricante (aproximação)", fabs,
                       index=fabs.index(e["fabricante"]) if e["fabricante"] in fabs else 0, key=f"ef_{k}")
    setor = c5.text_input("Setor", e.get("setor", ""), key=f"es_{k}")
    dests = list(d["destinos"])
    dest = st.selectbox("Envia para (destino)", dests,
                        index=dests.index(e["destino"]) if e["destino"] in dests else 0, key=f"ed_{k}")
    a, b, c = st.columns(3)
    mpps = a.checkbox("Usa MPPS", e["mpps"], key=f"e1_{k}")
    comm = b.checkbox("Usa Storage Commitment", e["commitment"], key=f"e2_{k}")
    imp = c.checkbox("Imprime filme", e["imprimir"], key=f"e3_{k}")
    st.markdown("**Séries do exame** (o que o equipamento envia a cada exame)")
    series = st.data_editor(e["series"], num_rows="dynamic", hide_index=True, key=f"et_{k}",
                            column_config={"descricao": st.column_config.TextColumn("Descrição"),
                                           "imagens": st.column_config.NumberColumn(
                                               "Imagens", min_value=1, max_value=500, step=1)})

    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("Salvar", type="primary", key=f"eb_{k}"):
        try:
            serie_ok = [{"descricao": str(s.get("descricao") or ""), "imagens": int(s.get("imagens") or 1)}
                        for s in series if s.get("descricao") or s.get("imagens")]
            novo_eq = {**e, "nome": nome, "aet": aet, "modalidade": mod, "fabricante": fab,
                       "setor": setor, "destino": dest, "mpps": mpps, "commitment": comm,
                       "imprimir": imp, "series": serie_ok}
            profiles.salvar_equipamento(d, novo_eq, None if novo else escolha)
            profiles.salvar(d)
            st.session_state["_prox_eq"] = novo_eq["nome"]
            st.toast("Equipamento salvo.")
            st.rerun()
        except ValueError as err:
            st.error(str(err))
    if not novo and b2.button("Excluir", key=f"ex_{k}"):
        profiles.excluir_equipamento(d, escolha)
        profiles.salvar(d)
        st.session_state["_prox_eq"] = (d["equipamentos"][0]["nome"] if d["equipamentos"] else NOVO)
        st.toast("Equipamento excluído.")
        st.rerun()
