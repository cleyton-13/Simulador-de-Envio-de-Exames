"""Simulador de Modalidades DICOM.

Três perfis de uso (barra lateral):
  Cliente  — Enviar exame (1 botão) e Histórico
  Suporte  — Início (cenários prontos), Enviar exame (3 passos), Diagnóstico, Cadastros, Histórico
  Técnico  — tudo do Suporte + controle total no envio, Vários equipamentos e Servidor virtual

Iniciar:  streamlit run app_simulador.py
"""
import sys
from pathlib import Path

import streamlit as st

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))


@st.cache_resource
def _marca_do_codigo():
    return {"marca": 0.0}


def _recarregar_se_mudou():
    """O Streamlit mantém os módulos importados na memória: sem isto, editar o código exige
    fechar e abrir o programa. Aqui, se algum .py mudou, os módulos são importados de novo."""
    arquivos = list(BASE.glob("*.py")) + list((BASE / "dicomsim").glob("*.py"))
    marca = max(a.stat().st_mtime for a in arquivos)
    estado = _marca_do_codigo()
    if marca != estado["marca"]:
        for nome in [n for n in sys.modules if n == "dicomsim" or n.startswith("dicomsim.") or n.startswith("ui_")]:
            del sys.modules[nome]
        estado["marca"] = marca


st.set_page_config(page_title="Simulador de Modalidades DICOM", page_icon="🩻", layout="wide")
_recarregar_se_mudou()

import ui_comum as C                                   # noqa: E402
from ui_avancado import pg_cadastros, pg_frota, pg_resultados, pg_servidor   # noqa: E402
from ui_diagnostico import pg_diagnostico              # noqa: E402
from ui_enviar import pg_enviar                        # noqa: E402
from ui_inicio import pg_inicio                        # noqa: E402

# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.markdown("### 🩻 Simulador DICOM")
    st.radio("Perfil de uso", ["Cliente", "Suporte", "Técnico"], index=1, horizontal=True, key="modo",
             help="Cliente: só enviar um exame · Suporte: guiado, com diagnóstico · Técnico: controle total")
    d = C.dados()
    if st.session_state.get("destino_ativo") not in d["destinos"]:
        st.session_state["destino_ativo"] = next((k for k in d["destinos"] if k != "local"),
                                                 next(iter(d["destinos"])))
    st.selectbox("Destino (para onde enviar)", list(d["destinos"]), key="destino_ativo",
                 help="PACS que vai receber os exames. Cadastre novos em Cadastros → Destinos.")
    chave, dest = C.destino_ativo()
    aet = st.session_state.get("aet_diag") or d["equipamentos"][0]["aet"]
    cx = C.status_conexao(chave, dest, aet)
    st.markdown(f"{'🟢' if cx['ok'] else '🔴'} {dest.pacs}  \n<small>{cx['msg']}</small>", unsafe_allow_html=True)
    if st.button("Testar conexão", width="stretch"):
        C.status_conexao(chave, dest, aet, forcar=True)
        st.rerun()

# ------------------------------------------------------------------ navegação (no topo)
visao = C.modo()
inicio = st.Page(pg_inicio, title="Início", icon="🏠", url_path="inicio", default=(visao != "Cliente"))
enviar = st.Page(pg_enviar, title="Enviar exame", icon="🩻", url_path="enviar", default=(visao == "Cliente"))
diag = st.Page(pg_diagnostico, title="Diagnóstico", icon="🔎", url_path="diagnostico")
cad = st.Page(pg_cadastros, title="Cadastros", icon="⚙", url_path="cadastros")
hist = st.Page(pg_resultados, title="Histórico", icon="📋", url_path="historico")
frota = st.Page(pg_frota, title="Vários equipamentos", icon="🚑", url_path="frota")
srv = st.Page(pg_servidor, title="Servidor virtual", icon="🖥", url_path="servidor")

if visao == "Cliente":
    paginas = [enviar, hist]
elif visao == "Suporte":
    paginas = [inicio, enviar, diag, cad, hist]
else:
    paginas = {"": [inicio, enviar, diag, cad, hist], "Avançado": [frota, srv]}
st.navigation(paginas, position="top").run()
