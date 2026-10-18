"""Tela de Testes DICOM — em português do Brasil.

Páginas:
  1. Visão geral  — indicadores, estado da ligação e últimos resultados
  2. Modalidades  — cadastro da origem (AE Title, setor, IP do equipamento)
  3. Equipamentos — criar e simular equipamentos médicos (PACS, RIS, impressora, modalidade)
  4. Destinos     — AE Title, host e porta + checklist
  5. Testes       — escolher e executar casos avulsos ou a bateria
  6. Imagens      — jogo de imagens de teste e o que voltou do PACS
  7. Diagnóstico  — simuladores, arquivos recebidos, logs e relatórios

Para iniciar: streamlit run app_tela_testes.py
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dicom_runtime import run_progresso

BASE = Path(__file__).parent
PY = sys.executable
MOD_FILE = BASE / "modalidades.json"
EQ_FILE = BASE / "equipamentos.json"
PASTA_ENVIO = BASE / "Teste de Envio"
PASTA_IMG = PASTA_ENVIO / "imagens"
PASTA_ESPECIAIS = PASTA_ENVIO / "casos_especiais"
REL_DIR = BASE / "relatorios"
REL_DIR.mkdir(exist_ok=True)

TESTES = [
    ("echo", "C-ECHO", "Conectividade", "Verificação (1.2.840.10008.1.1)"),
    ("store", "C-STORE", "Envio simples", "Uma imagem de teste ao PACS"),
    ("envio", "ENVIO", "Envio do jogo", "Imagens + validação de chegada"),
    ("find", "C-FIND", "Consulta", "Estudos no Study Root"),
    ("mwl", "MWL", "Worklist", "C-FIND de worklist no RIS"),
    ("print", "PRINT", "Impressão", "Filme e N-ACTION na impressora"),
]

TIPOS_EQ = {
    "PACS": {"papel": "pacs", "rotulo": "PACS (armazena imagens)",
             "script": "01_scp_pacs.py", "servidor": True,
             "sops": "Todos os SOP Classes de armazenamento"},
    "RIS": {"papel": "ris", "rotulo": "RIS / Worklist",
            "script": "05_mwl_scp.py", "servidor": True,
            "sops": "Modality Worklist (1.2.840.10008.5.1.4.31)"},
    "IMPRESSORA": {"papel": "prn", "rotulo": "Impressora DICOM",
                   "script": "06_print_scp.py", "servidor": True,
                   "sops": "Basic Grayscale Print Management"},
    "MODALIDADE": {"papel": None, "rotulo": "Modalidade (equipamento que faz exames)",
                   "script": "12_simulador_modalidade.py", "servidor": False,
                   "sops": "Consulta worklist, envia imagem e imprime"},
}

MODALIDADES_MEDICAS = ["CT", "MR", "CR", "DX", "US", "XA", "MG", "RF", "PT", "OT"]

st.set_page_config(page_title="Testes DICOM", layout="wide",
                   initial_sidebar_state="expanded")

# ----------------------------------------------------------------------------
# Design (tokens da especificação de frontend)
# ----------------------------------------------------------------------------
CSS = """
<style>
:root{
  --pri:#3b82f6; --pri-h:#2563eb;
  --surf:var(--background-color,#f8fafc); --card:var(--secondary-background-color,#fff);
  --txt:var(--text-color,#0f172a); --txt2:#64748b; --txt3:#94a3b8;
  --bord:#e2e8f0; --forte:#cbd5e1;
  --ok-bg:#ecfdf5; --ok-fg:#047857; --ok-bd:#a7f3d0;
  --er-bg:#fef2f2; --er-fg:#b91c1c; --er-bd:#fecaca;
  --av-bg:#fffbeb; --av-fg:#b45309; --av-bd:#fde68a;
}
.block-container{padding:1.5rem 2rem!important;max-width:1400px!important}
h1{font-size:1.5rem!important;font-weight:700!important;letter-spacing:-.01em}
h2{font-size:1.125rem!important;font-weight:600!important;margin:.25rem 0 .75rem!important}
h3{font-size:.875rem!important;font-weight:600!important}
.card{background:var(--card);border:1px solid var(--bord);border-radius:.75rem;
  padding:1.25rem;margin-bottom:1rem;transition:box-shadow .2s}
.card:hover{box-shadow:0 4px 12px rgba(15,23,42,.08)}
.card-t{font-size:.875rem;font-weight:600;color:var(--txt);margin-bottom:.35rem;
  display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
.card-s{font-size:.75rem;color:var(--txt2);margin-bottom:.9rem;line-height:1.5}
.kv{font-size:.8rem;color:var(--txt2);line-height:1.9}
.kv b{color:var(--txt);font-weight:600}
.pill{display:inline-block;padding:.15rem .6rem;border-radius:9999px;font-size:.7rem;
  font-weight:600;letter-spacing:.02em;border:1px solid transparent;white-space:nowrap}
.p-ok{background:var(--ok-bg);color:var(--ok-fg);border-color:var(--ok-bd)}
.p-er{background:var(--er-bg);color:var(--er-fg);border-color:var(--er-bd)}
.p-av{background:var(--av-bg);color:var(--av-fg);border-color:var(--av-bd)}
.p-neu{background:#f1f5f9;color:#475569;border-color:var(--bord)}
[data-testid="stMetric"]{background:var(--card);border:1px solid var(--bord);
  border-radius:.75rem;padding:1rem 1.25rem}
[data-testid="stMetricLabel"]{font-size:.7rem!important;font-weight:600!important;
  text-transform:uppercase;letter-spacing:.06em;color:var(--txt3)!important}
[data-testid="stMetricValue"]{font-size:1.75rem!important;font-weight:700!important}
[data-testid="stMetricDelta"]{font-size:.7rem!important}
.stButton>button{width:100%;border-radius:.5rem!important;font-size:.82rem!important;
  font-weight:500!important;padding:.5rem .9rem!important;transition:all .15s;
  border:1px solid var(--forte)!important;background:var(--card)!important;color:var(--txt)!important}
.stButton>button:hover{border-color:var(--pri)!important;background:var(--pri)!important;color:#fff!important}
.stButton>button[kind="primary"]{background:var(--pri)!important;border-color:var(--pri)!important;color:#fff!important}
.stButton>button[kind="primary"]:hover{background:var(--pri-h)!important;border-color:var(--pri-h)!important}
.stDownloadButton>button{width:auto;border-radius:.5rem!important;font-size:.82rem!important;
  font-weight:500!important;padding:.5rem .9rem!important;border:1px solid var(--pri)!important;
  background:var(--pri)!important;color:#fff!important}
[data-baseweb="input"]>div,input,textarea{border-radius:.5rem!important;
  border-color:var(--forte)!important;font-size:.85rem!important}
[data-testid="stWidgetLabel"] p{font-size:.72rem!important;font-weight:600!important;
  color:var(--txt2)!important;margin-bottom:.1rem!important;letter-spacing:.02em}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:.75rem!important}
[data-testid="stDataFrame"]{border:1px solid var(--bord);border-radius:.5rem;overflow:hidden}
table{border-collapse:collapse}
th{font-size:.68rem!important;font-weight:600!important;text-transform:uppercase;
  letter-spacing:.06em;color:var(--txt2)!important}
[data-testid="stCaptionContainer"] p{font-size:.72rem!important;color:var(--txt3)!important}
[data-testid="stSidebar"]{border-right:1px solid var(--bord)}
hr{margin:1rem 0!important;border-color:var(--bord)!important}
pre{background:#0f172a!important;color:#e2e8f0!important;border-radius:.5rem;
  font-size:.72rem!important;padding:.85rem!important;line-height:1.55!important;border:1px solid #1e293b}
::-webkit-scrollbar{width:7px;height:7px}
::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:4px}
::-webkit-scrollbar-track{background:transparent}
.dots::after{content:'';animation:dots 1.4s steps(4,end) infinite}
@keyframes dots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

CSS_ESCURO = """
<style>
:root{
  --background-color:#0f172a; --secondary-background-color:#1e293b;
  --text-color:#f8fafc; --primary-color:#60a5fa; --link-color:#60a5fa;
  --border-color:#334155; --secondary-border-color:#475569; --code-background-color:#0b1220;
  --txt2:#94a3b8; --txt3:#64748b; --bord:#334155; --forte:#475569;
}
html,body,[data-testid="stAppViewContainer"],[data-testid="stHeader"],
[data-testid="stToolbar"]{background:#0f172a;color:#f8fafc}
[data-testid="stSidebar"]{background:#0f172a;border-right:1px solid #334155}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:#e2e8f0}
[data-testid="stVerticalBlockBorderWrapper"]{background:#1e293b;border-color:#334155}
[data-testid="stMetric"]{background:#1e293b;border-color:#334155}
[data-testid="stWidgetLabel"] p{color:#94a3b8!important}
[data-baseweb="input"]>div,input,textarea,[data-baseweb="select"]>div{
  background:#1e293b;border-color:#475569;color:#f8fafc}
[data-baseweb="base-input"]::placeholder{color:#64748b}
[data-testid="stDataFrame"]{border-color:#334155;background:#1e293b}
[data-testid="stExpander"] details{border-color:#334155}
.p-neu{background:#1e293b;color:#94a3b8;border-color:#334155}
.card:hover{box-shadow:0 4px 12px rgba(0,0,0,.45)}
.stButton>button{background:#1e293b!important;border-color:#475569!important;color:#e2e8f0!important}
.stButton>button:hover{background:#334155!important;color:#fff!important}
hr{border-color:#334155!important}
label,[data-testid="stCheckbox"] label span,[data-testid="stRadio"] label span{color:#e2e8f0}
</style>
"""


def aplicar_tema():
    if st.session_state.get("tema") == "escuro":
        st.markdown(CSS_ESCURO, unsafe_allow_html=True)


def pill(txt, tipo="neu"):
    st.markdown(f'<span class="pill p-{tipo}">{txt}</span>', unsafe_allow_html=True)


def card(titulo, subtitulo="", corpo=""):
    sub = f'<div class="card-s">{subtitulo}</div>' if subtitulo else ""
    st.markdown(f'<div class="card"><div class="card-t">{titulo}</div>{sub}{corpo}</div>',
                unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Persistência
# ----------------------------------------------------------------------------
CONFIG_FILE = BASE / "config.json"


def load_cfg():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def salvar_cfg(campos: dict):
    dados = load_cfg()
    dados.update(campos)
    CONFIG_FILE.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    st.session_state["cfg"] = dados
    return datetime.now().strftime("%H:%M:%S")


def load_mods():
    mods = None
    if MOD_FILE.exists():
        try:
            mods = json.loads(MOD_FILE.read_text(encoding="utf-8"))
        except Exception:
            mods = None
    if not mods:
        mods = [{"nome": "CT-SALA-1", "aet": "CT_SALA1", "desc": "Tomógrafo sala 1",
                 "setor": "Imagem - Sala 1", "ip_equip": "192.168.1.50"},
                {"nome": "RX-EMERG", "aet": "RX_EMERG", "desc": "Raio-X emergência",
                 "setor": "Emergência", "ip_equip": "192.168.1.51"}]
    mudou = False
    for m in mods:
        for k, v in (("setor", ""), ("ip_equip", "")):
            if k not in m:
                m[k] = v
                mudou = True
    if mudou and MOD_FILE.exists():
        save_mods(mods)
    return mods


def save_mods(mods):
    MOD_FILE.write_text(json.dumps(mods, ensure_ascii=False, indent=2), encoding="utf-8")


def load_equips():
    if EQ_FILE.exists():
        try:
            return json.loads(EQ_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return [{"nome": "PACS do laboratory", "aet": "PACS_TESTE", "ip": "127.0.0.1",
             "porta": 11112, "tipo": "PACS", "modalidade": "", "desc": "PACS simulado local"},
            {"nome": "RIS do laboratory", "aet": "RIS_TESTE", "ip": "127.0.0.1",
             "porta": 11114, "tipo": "RIS", "modalidade": "", "desc": "Worklist simulado"},
            {"nome": "Impressora do laboratory", "aet": "PRINTER_TESTE", "ip": "127.0.0.1",
             "porta": 11115, "tipo": "IMPRESSORA", "modalidade": "",
             "desc": "Impressora simulada"}]


def save_equips(eqs):
    EQ_FILE.write_text(json.dumps(eqs, ensure_ascii=False, indent=2), encoding="utf-8")


def campos_destinos(d):
    return {"pacs_aet": d["pacs"]["aet"], "pacs_ip": d["pacs"]["ip"],
            "pacs_port": int(d["pacs"]["port"]),
            "mwl_aet": d["ris"]["aet"], "mwl_ip": d["ris"]["ip"],
            "mwl_port": int(d["ris"]["port"]),
            "printer_aet": d["prn"]["aet"], "printer_ip": d["prn"]["ip"],
            "printer_port": int(d["prn"]["port"])}


def init_state():
    ss = st.session_state
    c = load_cfg()
    ss["cfg"] = c
    for k, v in (("tema", c.get("tema", "claro")),
                 ("mods", load_mods()), ("mod_sel", 0),
                 ("equips", load_equips()), ("eq_sel", 0),
                 ("results", {}), ("procs", {}), ("last_rel", None),
                 ("teste_conexao", None), ("sel_tags", []), ("sel_arquivos", []),
                 ("testes_sel", [t[0] for t in TESTES]), ("destinos_sel", ["pacs"]),
                 ("salvo_quando", None)):
        ss.setdefault(k, v)
    if not ss["mods"]:
        ss["mods"] = load_mods()
    ss["mod_sel"] = min(ss["mod_sel"], max(len(ss["mods"]) - 1, 0))


init_state()
aplicar_tema()


def mod_atual():
    mods = st.session_state["mods"]
    i = st.session_state["mod_sel"]
    return mods[i] if mods else {"nome": "-", "aet": "SIMULADOR", "desc": "", "setor": "",
                                "ip_equip": ""}


def dests():
    """Fonte da verdade = config.json (garante que o salvo vale em todas as páginas)."""
    c = load_cfg()
    ip_base = c.get("pacs_ip", "127.0.0.1")
    return {"pacs": {"aet": c.get("pacs_aet", "PACS_TESTE"),
                     "ip": c.get("pacs_ip", "127.0.0.1"),
                     "port": int(c.get("pacs_port", 11112))},
            "ris": {"aet": c.get("mwl_aet", "RIS_TESTE"), "ip": c.get("mwl_ip", ip_base),
                    "port": int(c.get("mwl_port", 11114))},
            "prn": {"aet": c.get("printer_aet", "PRINTER_TESTE"),
                    "ip": c.get("printer_ip", ip_base),
                    "port": int(c.get("printer_port", 11115))}}


def extra():
    s = st.session_state
    return {"arquivo": s.get("x_arquivo", "teste_CT.dcm"),
            "patient": s.get("x_patient", "*"),
            "modality": s.get("x_modality", ""),
            "date": s.get("x_date", ""),
            "station": s.get("x_station", mod_atual()["aet"]),
            "pacs_real": s.get("x_pacs_real", False),
            "tags": s.get("sel_tags", []),
            "arquivos": s.get("sel_arquivos", [])}


# ----------------------------------------------------------------------------
# Execução
# ----------------------------------------------------------------------------
def run_cli(args, timeout=180):
    t0 = time.time()
    try:
        p = subprocess.run([PY] + args, cwd=str(BASE), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out = (p.stdout or "") + (("\n[ERRO]\n" + p.stderr) if p.stderr else "")
        ok = p.returncode == 0
        for marca in ("FALHOU", "FALHA", "Traceback", "[ERRO]"):
            if marca in out:
                ok = False
        return ok, time.time() - t0, out
    except subprocess.TimeoutExpired:
        return False, timeout, f"TIMEOUT após {timeout}s"
    except Exception as e:
        return False, time.time() - t0, f"ERRO: {e}"


def build_cmd(tid, mod_aet, d, x):
    if tid == "echo":
        return ["02_scu_teste.py", "--teste", "echo", "--ip", d["pacs"]["ip"],
                "--port", str(d["pacs"]["port"]), "--aet", d["pacs"]["aet"],
                "--meu-aet", mod_aet]
    if tid == "store":
        return ["02_scu_teste.py", "--teste", "store", "--ip", d["pacs"]["ip"],
                "--port", str(d["pacs"]["port"]), "--aet", d["pacs"]["aet"],
                "--meu-aet", mod_aet, "--arquivo", x["arquivo"]]
    if tid == "find":
        return ["02_scu_teste.py", "--teste", "find", "--ip", d["pacs"]["ip"],
                "--port", str(d["pacs"]["port"]), "--aet", d["pacs"]["aet"],
                "--meu-aet", mod_aet, "--patient-name", x["patient"]]
    if tid == "mwl":
        return ["02_scu_teste.py", "--teste", "mwl", "--ip", d["ris"]["ip"],
                "--mwl-port", str(d["ris"]["port"]), "--mwl-aet", d["ris"]["aet"],
                "--meu-aet", mod_aet, "--modality", x["modality"],
                "--patient-name", x["patient"]]
    if tid == "print":
        return ["02_scu_teste.py", "--teste", "print", "--ip", d["prn"]["ip"],
                "--print-port", str(d["prn"]["port"]), "--print-aet", d["prn"]["aet"],
                "--meu-aet", mod_aet]
    if tid == "envio":
        cmd = ["10_envio_validacao.py", "--meu-aet", mod_aet, "--pasta", str(PASTA_ENVIO)]
        if x.get("tags"):
            cmd += ["--tags", ",".join(x["tags"])]
        if x.get("arquivos"):
            cmd += ["--arquivos", ",".join(x["arquivos"])]
        if x["pacs_real"]:
            cmd += ["--pacs-ip", d["pacs"]["ip"], "--pacs-port", str(d["pacs"]["port"]),
                    "--pacs-aet", d["pacs"]["aet"]]
        return cmd
    return []


def desc_envio(tid, mod_aet, d, x):
    """Texto do que será enviado — sempre com AE Title, host e PORTA."""
    origem = f'<b>Origem</b> {mod_aet}'
    if tid == "echo":
        return (f"{origem} &nbsp;&rarr;&nbsp; <b>PACS</b> {d['pacs']['aet']} @ "
                f"{d['pacs']['ip']}:<b>{d['pacs']['port']}</b><br>"
                f"Um C-ECHO — o outro lado responde <code>0x0000</code>.")
    if tid == "store":
        return (f"{origem} &nbsp;&rarr;&nbsp; <b>PACS</b> {d['pacs']['aet']} @ "
                f"{d['pacs']['ip']}:<b>{d['pacs']['port']}</b><br>"
                f"Um C-STORE de <code>{x['arquivo']}</code>.")
    if tid == "envio":
        local = "" if x["pacs_real"] else " (simulador local)"
        sel = (", ".join(x["arquivos"]) if x.get("arquivos")
               else (", ".join(x["tags"]) if x.get("tags") else "todas as imagens"))
        return (f"{origem} &nbsp;&rarr;&nbsp; <b>PACS</b> {d['pacs']['aet']} @ "
                f"{d['pacs']['ip']}:<b>{d['pacs']['port']}</b>{local}<br>"
                f"Seleção: <b>{sel}</b><br>"
                f"Por imagem: C-STORE &rarr; C-FIND (chegou?) &rarr; "
                f"C-MOVE (bytes) + SHA-256 dos pixels.")
    if tid == "find":
        return (f"{origem} &nbsp;&rarr;&nbsp; <b>PACS</b> {d['pacs']['aet']} @ "
                f"{d['pacs']['ip']}:<b>{d['pacs']['port']}</b><br>"
                f"C-FIND Study Root, filtro PatientName = <code>{x['patient']}</code>.")
    if tid == "mwl":
        return (f"{origem} &nbsp;&rarr;&nbsp; <b>RIS</b> {d['ris']['aet']} @ "
                f"{d['ris']['ip']}:<b>{d['ris']['port']}</b><br>"
                f"C-FIND MWL — Modalidade <code>{x['modality'] or '*'}</code>, "
                f"Paciente <code>{x['patient'] or '*'}</code>, "
                f"Data <code>{x['date'] or '*'}</code>.")
    return (f"{origem} &nbsp;&rarr;&nbsp; <b>Impressora</b> {d['prn']['aet']} @ "
            f"{d['prn']['ip']}:<b>{d['prn']['port']}</b><br>"
            f"N-CREATE FilmSession &rarr; FilmBox &rarr; N-SET pixels &rarr; "
            f"N-ACTION imprimir.")


def marcar(tid, titulo, ok, dt, log, mod_aet):
    st.session_state["results"][tid] = {"ok": ok, "dt": dt, "log": log,
                                        "quando": datetime.now().strftime("%H:%M:%S"),
                                        "titulo": titulo, "mod": mod_aet}


def total_estimado(tid):
    x = extra()
    if tid != "envio":
        return None
    if x.get("arquivos"):
        return len(x["arquivos"])
    tags = st.session_state.get("sel_tags", [])
    return len(tags) if tags else len(list(PASTA_IMG.glob("*.dcm")))


def rodar(tid, titulo=None, console=None, barra=True, timeout=900):
    mod = mod_atual()
    titulo = titulo or next((ti for t, ti, _, _ in TESTES if t == tid), tid)
    ok, dt, log = run_progresso(build_cmd(tid, mod["aet"], dests(), extra()),
                                cwd=str(BASE), rotulo=titulo,
                                total=total_estimado(tid), timeout=timeout,
                                barra=barra, console=console)
    marcar(tid, titulo, ok, dt, log, mod["aet"])
    return ok, dt, log


def resumo_md(mod, d, linhas, npass, total):
    agora = datetime.now()
    r = [f"# Relatório DICOM — {agora:%Y-%m-%d %H:%M:%S}",
         "## Origem (modalidade)", f"- Nome: **{mod['nome']}**",
         f"- Calling AE Title: **{mod['aet']}**",
         f"- Setor/Leito: {mod.get('setor') or '—'}",
         f"- IP do equipamento: {mod.get('ip_equip') or '—'}", "",
         "## Destinos (portas usadas)", "",
         "| Papel | AE Title | Host | Porta |", "|---|---|---|---|"]
    for nome, k in (("PACS", "pacs"), ("RIS / MWL", "ris"), ("Impressora", "prn")):
        r.append(f"| {nome} | {d[k]['aet']} | {d[k]['ip']} | **{d[k]['port']}** |")
    r += ["", f"**Resultado: {'🟢' if npass == total else '🔴'} {npass}/{total} PASS**", "",
          "| Teste | Status | Tempo |", "|---|---|---|"]
    for tid, titulo, ok, dt in linhas:
        r.append(f"| {titulo} | {'🟢 PASS' if ok else '🔴 FAIL'} | {dt:.1f}s |")
    r.append("")
    for tid, titulo, ok, dt, log in linhas:
        r += [f"## {'🟢' if ok else '🔴'} {titulo} — {'PASS' if ok else 'FAIL'} ({dt:.1f}s)",
              desc_envio(tid, mod["aet"], d, extra()), "", "```", log[-2000:], "```", ""]
    return "\n".join(r)


# ----------------------------------------------------------------------------
# Páginas
# ----------------------------------------------------------------------------
def pg_visao():
    mod = mod_atual()
    d = dests()
    st.title("Visão geral")
    st.caption("Estado da ligação e resultado da última bateria de testes.")

    res = st.session_state["results"]
    feitos = [t for t, _, _, _ in TESTES if t in res]
    passaram = [t for t in feitos if res[t]["ok"]]
    falharam = [t for t in feitos if not res[t]["ok"]]
    ultimo = max((res[t]["quando"] for t in feitos), default="—")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Testes executados", f"{len(feitos)}/{len(TESTES)}")
    k2.metric("Passaram", len(passaram))
    k3.metric("Falharam", len(falharam))
    k4.metric("Última execução", ultimo)

    st.subheader("Origem da ligação")
    card(f"{mod['nome']}", mod.get("desc") or "",
         f'<div class="kv"><b>Calling AE Title:</b> {mod["aet"]} &nbsp;·&nbsp; '
         f'<b>Setor/Leito:</b> {mod.get("setor") or "—"}<br>'
         f'<b>IP do equipamento:</b> {mod.get("ip_equip") or "—"} &nbsp;·&nbsp; '
         f'<b>Porta de origem:</b> efêmera (escolhida pelo Windows)</div>')

    st.subheader("Destinos e portas")
    cols = st.columns(3)
    for col, (rot, k, uso) in zip(cols, (("PACS", "pacs", "C-ECHO, C-STORE, C-FIND, ENVIO"),
                                        ("RIS / MWL", "ris", "C-FIND de worklist"),
                                        ("Impressora", "prn", "N-CREATE / N-SET / N-ACTION"))):
        v = d[k]
        with col:
            card(rot, uso,
                 f'<div class="kv"><b>AE Title:</b> {v["aet"]}<br><b>Host:</b> {v["ip"]}<br>'
                 f'<b>Porta:</b> <b>{v["port"]}</b><br>'
                 f'<span style="font-size:.7rem;color:#94a3b8">{v["aet"]} @ {v["ip"]}:{v["port"]}'
                 f'</span></div>')

    st.subheader("Últimos resultados")
    if not feitos:
        card("Nenhum teste executado ainda",
             "Vá até <b>Testes</b> e escolha um caso ou rode a bateria completa.")
    else:
        for tid, titulo, _, _ in TESTES:
            r = res.get(tid)
            if not r:
                continue
            p_ = "ok" if r["ok"] else "er"
            st.markdown(
                f'<div class="card" style="padding:.85rem 1.1rem"><div class="card-t">{titulo} '
                f'<span class="pill p-{p_}">{"PASS" if r["ok"] else "FAIL"}</span>'
                f'<span style="font-size:.7rem;color:#94a3b8;margin-left:auto">'
                f'{r["dt"]:.1f}s · {r["quando"]} · {r["mod"]}</span></div></div>',
                unsafe_allow_html=True)

    if st.session_state["last_rel"]:
        fname, txt = st.session_state["last_rel"]
        st.download_button("Baixar último relatório", txt, file_name=fname, key="dl_visao")


def pg_modalidades():
    st.title("Modalidades (origem)")
    st.caption("Quem envia. O Calling AE Title é o nome que o PACS, o RIS e a "
               "impressora veem no log — é assim que se sabe qual teste mandou o quê.")
    mods = st.session_state["mods"]

    if mods:
        i = st.selectbox("Modalidade ativa", range(len(mods)),
                         format_func=lambda x: f"{mods[x]['nome']}  ({mods[x]['aet']})",
                         key="mod_sel")
        st.session_state["mod_sel"] = i
    mod = mod_atual()

    c1, c2 = st.columns([2, 1])
    with c1:
        card(mod["nome"], mod.get("desc") or "sem descrição",
             f'<div class="kv"><b>Calling AE Title:</b> {mod["aet"]}<br>'
             f'<b>Setor / Leito:</b> {mod.get("setor") or "—"}<br>'
             f'<b>IP do equipamento:</b> {mod.get("ip_equip") or "—"}</div>')
    with c2:
        if mod.get("ip_equip"):
            if st.button("Apontar destinos para este IP", use_container_width=True):
                salvar_cfg({"pacs_ip": mod["ip_equip"], "mwl_ip": mod["ip_equip"],
                            "printer_ip": mod["ip_equip"]})
                st.toast(f"IP {mod['ip_equip']} aplicado aos 3 destinos")
                st.rerun()
            st.caption(f"Um clique preenche PACS, RIS e Impressora com "
                       f"{mod['ip_equip']}. Ajuste AE Title e porta em Destinos.")

    st.subheader("Cadastrar")
    a, b = st.columns(2)
    nome = a.text_input("Nome", placeholder="ex.: CT-SALA-1")
    aet = b.text_input("Calling AE Title", placeholder="ex.: CT_SALA1 (máx. 16)")
    desc = st.text_input("Descrição", placeholder="ex.: Tomógrafo da sala 1")
    e, f = st.columns(2)
    setor = e.text_input("Setor / Leito", placeholder="ex.: Imagem - Sala 1")
    ip_eq = f.text_input("IP real do equipamento", placeholder="ex.: 192.168.1.50")
    g, h = st.columns(2)
    if g.button("Adicionar modalidade", type="primary"):
        if not nome or not aet:
            st.error("Preencha nome e Calling AE Title.")
        elif any(m["nome"] == nome for m in mods):
            st.error("Já existe modalidade com esse nome.")
        else:
            mods.append({"nome": nome.strip(), "aet": aet.strip().upper()[:16],
                         "desc": desc, "setor": setor, "ip_equip": ip_eq})
            save_mods(mods)
            st.session_state["mods"] = mods
            st.rerun()
    if h.button("Salvar setor / IP da ativa"):
        for m in mods:
            if m["nome"] == mod["nome"]:
                m["setor"] = setor or m.get("setor", "")
                m["ip_equip"] = ip_eq or m.get("ip_equip", "")
                if aet:
                    m["aet"] = aet.strip().upper()[:16]
        save_mods(mods)
        st.session_state["mods"] = mods
        st.rerun()

    st.subheader("Modalidades cadastradas")
    st.dataframe([{"Nome": m["nome"], "Calling AET": m["aet"], "Setor": m.get("setor", ""),
                   "IP equipamento": m.get("ip_equip", ""), "Descrição": m.get("desc", "")}
                  for m in mods], use_container_width=True, hide_index=True)
    j, k = st.columns([3, 1])
    if k.button("Remover a ativa"):
        mods = [m for m in mods if m["nome"] != mod["nome"]]
        save_mods(mods)
        st.session_state["mods"] = mods
        st.session_state["mod_sel"] = 0
        st.rerun()


def eq_rodando(chave):
    p = st.session_state["procs"].get(chave)
    return p is not None and p.poll() is None


def subir_equip(eq):
    info = TIPOS_EQ.get(eq["tipo"])
    if not info or not info["servidor"]:
        return False, "Não é um equipamento servidor"
    chave = f'eq_{eq["aet"]}'
    if eq_rodando(chave):
        return False, "Já está em execução"
    cmd = [PY, info["script"], "--aet", eq["aet"], "--port", str(eq["porta"])]
    p = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    st.session_state["procs"][chave] = p
    time.sleep(1.2)
    return True, f"Subiu com o PID {p.pid}"


def derrubar_equip(eq):
    chave = f'eq_{eq["aet"]}'
    p = st.session_state["procs"].pop(chave, None)
    if p:
        p.terminate()
        return True, "Encerrado"
    return False, "Não estava em execução"


def apontar_equip(eq):
    papel = TIPOS_EQ[eq["tipo"]]["papel"]
    if not papel:
        return False, "Modalidade não é destino — use a aba Testes"
    c = load_cfg()
    if papel == "pacs":
        campos = {"pacs_aet": eq["aet"], "pacs_ip": eq["ip"], "pacs_port": int(eq["porta"])}
        rot = "PACS"
    elif papel == "ris":
        campos = {"mwl_aet": eq["aet"], "mwl_ip": eq["ip"], "mwl_port": int(eq["porta"])}
        rot = "RIS"
    else:
        campos = {"printer_aet": eq["aet"], "printer_ip": eq["ip"],
                  "printer_port": int(eq["porta"])}
        rot = "Impressora"
    salvar_cfg(campos)
    return True, f"{rot} agora é {eq['aet']} @ {eq['ip']}:{eq['porta']}"


def pg_equipamentos():
    st.title("Equipamentos médicos")
    st.caption("Crie e simule equipamentos: PACS, RIS/worklist, impressora e "
               "modalidades. Tudo fica salvo em equipamentos.json para reutilizar.")
    eqs = st.session_state["equips"]

    st.subheader("Criar equipamento")
    with st.form("form_eq", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        nome = c1.text_input("Nome do equipamento", placeholder="ex.: PACS do Hospital A")
        aet = c2.text_input("AE Title", placeholder="ex.: PACM")
        ip = c3.text_input("IP / Host", value="127.0.0.1")
        d1, d2, d3 = st.columns(3)
        porta = d1.number_input("Porta", 1, 65535, 11112, step=1)
        tipo = d2.selectbox("Tipo", list(TIPOS_EQ.keys()),
                            format_func=lambda t: TIPOS_EQ[t]["rotulo"])
        modalidade = d3.selectbox("Modalidade (se for equipamento de exames)",
                                  [""] + MODALIDADES_MEDICAS)
        desc = st.text_input("Descrição", placeholder="ex.: PACS de produção, sala 3")
        if st.form_submit_button("Salvar equipamento", type="primary"):
            if not nome or not aet:
                st.error("Preencha nome e AE Title.")
            elif any(e["aet"].upper() == aet.strip().upper() for e in eqs):
                st.error("Já existe um equipamento com esse AE Title.")
            else:
                eqs.append({"nome": nome.strip(), "aet": aet.strip().upper()[:16],
                            "ip": ip.strip(), "porta": int(porta), "tipo": tipo,
                            "modalidade": modalidade, "desc": desc})
                save_equips(eqs)
                st.session_state["equips"] = eqs
                st.success(f"Equipamento {nome} salvo.")
                st.rerun()

    st.subheader("Equipamentos salvos")
    if not eqs:
        st.caption("Nenhum equipamento cadastrado ainda.")
        return

    for eq in eqs:
        info = TIPOS_EQ[eq["tipo"]]
        chave = f'eq_{eq["aet"]}'
        rodando = eq_rodando(chave)
        titulo = (f"{eq['nome']} <span class=\"pill p-neu\">{eq['tipo']}</span>"
                  + (f' <span class="pill p-ok">em execução</span>' if rodando else
                     ' <span class="pill p-neu">parado</span>'))
        card(titulo, eq.get("desc") or info["sops"],
             f'<div class="kv"><b>AE Title:</b> {eq["aet"]}<br>'
             f'<b>Endereço:</b> {eq["aet"]} @ {eq["ip"]}:<b>{eq["porta"]}</b><br>'
             f'<b>Serviços:</b> {info["sops"]}'
             + (f'<br><b>Modalidade:</b> {eq["modalidade"]}' if eq.get("modalidade") else "")
             + '</div>')

        a1, a2, a3, a4, a5 = st.columns(5)
        pode_subir = info["servidor"]
        if a1.button("Subir", key=f"up_{chave}", use_container_width=True,
                     disabled=not pode_subir or rodando):
            ok, msg = subir_equip(eq)
            (st.success if ok else st.warning)(msg)
            st.rerun()
        if a2.button("Derrubar", key=f"dn_{chave}", use_container_width=True,
                     disabled=not rodando):
            ok, msg = derrubar_equip(eq)
            (st.success if ok else st.warning)(msg)
            st.rerun()
        if a3.button("Testar (C-ECHO)", key=f"te_{chave}", use_container_width=True,
                     disabled=not pode_subir):
            with st.container():
                run_progresso(["02_scu_teste.py", "--teste", "echo", "--ip", eq["ip"],
                               "--port", str(eq["porta"]), "--aet", eq["aet"],
                               "--meu-aet", mod_atual()["aet"]],
                              cwd=str(BASE), rotulo=f"C-ECHO {eq['aet']}", timeout=45)
            st.rerun()
        if a4.button("Apontar como destino", key=f"ap_{chave}", use_container_width=True,
                     disabled=not info["papel"]):
            ok, msg = apontar_equip(eq)
            (st.success if ok else st.warning)(msg)
            st.rerun()
        if a5.button("Remover", key="rm_" + chave, use_container_width=True):
            derrubar_equip(eq)
            eqs = [e for e in eqs if e["aet"] != eq["aet"]]
            save_equips(eqs)
            st.session_state["equips"] = eqs
            st.rerun()

    st.subheader("Simular uma modalidade (equipamento que faz exames)")
    st.caption("O simulador consulta a worklist no RIS, envia a imagem de cada "
               "exame ao PACS e manda o filme para a impressora.")
    s1, s2, s3 = st.columns(3)
    aet_mod = s1.text_input("AE Title da modalidade", "CT_SALA1", key="sim_aet")
    mod_escolhida = s2.selectbox("Modalidade", MODALIDADES_MEDICAS, key="sim_mod")
    ciclos = s3.number_input("Quantidade de exames", 1, 50, 3, step=1, key="sim_ciclos")
    usar_wl = st.checkbox("Consultar a worklist antes (desmarque para simular sem RIS)",
                         value=True, key="sim_wl")
    usar_print = st.checkbox("Imprimir cada exame", value=True, key="sim_print")
    d = dests()
    st.markdown(
        f'<div class="card"><div class="kv">'
        f'<b>PACS</b> {d["pacs"]["aet"]} @ {d["pacs"]["ip"]}:<b>{d["pacs"]["port"]}</b> · '
        f'<b>RIS</b> {d["ris"]["aet"]} @ {d["ris"]["ip"]}:<b>{d["ris"]["port"]}</b> · '
        f'<b>Impressora</b> {d["prn"]["aet"]} @ {d["prn"]["ip"]}:<b>{d["prn"]["port"]}</b>'
        f'</div></div>', unsafe_allow_html=True)
    if st.button("Iniciar simulação da modalidade", type="primary"):
        cmd = ["12_simulador_modalidade.py", "--aet", aet_mod.strip().upper()[:16],
               "--modalidade", mod_escolhida, "--ciclos", str(int(ciclos)),
               "--pacs-aet", d["pacs"]["aet"], "--pacs-ip", d["pacs"]["ip"],
               "--pacs-port", str(d["pacs"]["port"]),
               "--ris-aet", d["ris"]["aet"], "--ris-ip", d["ris"]["ip"],
               "--ris-port", str(d["ris"]["port"]),
               "--print-aet", d["prn"]["aet"], "--print-ip", d["prn"]["ip"],
               "--print-port", str(d["prn"]["port"])]
        if not usar_wl:
            cmd.append("--sem-worklist")
        if not usar_print:
            cmd.append("--sem-print")
        with st.container():
            run_progresso(cmd, cwd=str(BASE), rotulo=f"Simulação {mod_escolhida}",
                          total=int(ciclos), timeout=600)


def draft_atual():
    s = st.session_state
    try:
        return {"pacs": {"aet": s["pacs_aet"], "ip": s["pacs_ip"], "port": s["pacs_port"]},
                "ris": {"aet": s["ris_aet"], "ip": s["ris_ip"], "port": s["ris_port"]},
                "prn": {"aet": s["prn_aet"], "ip": s["prn_ip"], "port": s["prn_port"]}}
    except KeyError:
        return dests()


def pg_destinos():
    st.title("Destinos")
    st.caption("Quem recebe. AE Title, host e porta são os três dados que o outro "
               "lado usa para aceitar a conexão.")
    s = st.session_state
    salvo = dests()

    st.subheader("Testar a conexão (escolha quais)")
    escolhidos = st.multiselect("Destinos para testar", ["pacs", "ris", "prn"],
                               default=["pacs"], key="destinos_sel",
                               format_func=lambda k: {"pacs": "PACS", "ris": "RIS / MWL",
                                                     "prn": "Impressora"}[k])
    d = dests()
    if st.button("Testar os selecionados (C-ECHO)", use_container_width=True,
                 disabled=not escolhidos):
        ph = st.progress(0.0, text="Testando conexões...")
        console = st.empty()
        res = []
        for i, k in enumerate(escolhidos):
            rot = {"pacs": "PACS", "ris": "RIS", "prn": "Impressora"}[k]
            v = d[k]
            ph.progress(i / len(escolhidos),
                        text=f"[{i + 1}/{len(escolhidos)}] {rot} {v['aet']} @ {v['ip']}:{v['port']}")
            ok, dt, _ = run_progresso(
                ["02_scu_teste.py", "--teste", "echo", "--ip", v["ip"],
                 "--port", str(v["port"]), "--aet", v["aet"], "--meu-aet", mod_atual()["aet"]],
                cwd=str(BASE), rotulo=rot, timeout=45, barra=False, console=console)
            res.append((rot, v, ok, dt))
        ph.progress(1.0, text="Fim dos testes de conexão")
        s["teste_conexao"] = res
        st.rerun()

    st.divider()
    b1, b2, b3 = st.columns([1.2, 1.2, 2])
    if b1.button("Salvar destinos e aplicar", type="primary", use_container_width=True,
                 key="btn_salvar"):
        s["salvo_quando"] = salvar_cfg(campos_destinos(draft_atual()))
        st.toast(f"Destinos salvos e aplicados às {s['salvo_quando']}")
        st.rerun()
    b3.caption(f"Salvo em config.json · última gravação: **{s.get('salvo_quando') or '—'}**")

    def bloco(col, rot, uso, pref):
        with col:
            card(rot, uso)
            st.text_input("AE Title", value=salvo[pref]["aet"], key=f"{pref}_aet")
            a, b = st.columns(2)
            a.text_input("Host / IP", value=salvo[pref]["ip"], key=f"{pref}_ip")
            b.number_input("Porta", 1, 65535, int(salvo[pref]["port"]),
                           key=f"{pref}_port", step=1)

    c1, c2, c3 = st.columns(3)
    bloco(c1, "PACS", "C-ECHO, C-STORE, C-FIND e ENVIO", "pacs")
    bloco(c2, "RIS / MWL", "C-FIND de worklist", "ris")
    bloco(c3, "Impressora", "Impressão de filme", "prn")

    if campos_destinos(draft_atual()) != campos_destinos(salvo):
        s["salvo_quando"] = salvar_cfg(campos_destinos(draft_atual()))
        st.toast("Alterações salvas automaticamente")
        st.rerun()

    st.divider()
    d = dests()
    st.subheader("Ligação que será usada nos testes")
    st.markdown(
        f'<div class="card"><div class="kv">'
        f'<b>Origem</b> {mod_atual()["aet"]} &nbsp;&rarr;&nbsp; PACS {d["pacs"]["aet"]} @ '
        f'{d["pacs"]["ip"]}:<b>{d["pacs"]["port"]}</b><br>'
        f'<b>Origem</b> {mod_atual()["aet"]} &nbsp;&rarr;&nbsp; RIS {d["ris"]["aet"]} @ '
        f'{d["ris"]["ip"]}:<b>{d["ris"]["port"]}</b><br>'
        f'<b>Origem</b> {mod_atual()["aet"]} &nbsp;&rarr;&nbsp; Impressora {d["prn"]["aet"]} @ '
        f'{d["prn"]["ip"]}:<b>{d["prn"]["port"]}</b></div></div>', unsafe_allow_html=True)

    tc = s.get("teste_conexao")
    if tc:
        st.subheader("Resultado do teste de conexão")
        for rot, v, ok, dt in tc:
            p_ = "ok" if ok else "er"
            st.markdown(
                f'<div class="card" style="padding:.7rem 1rem"><div class="card-t">{rot} '
                f'<span class="pill p-{p_}">{"RESPONDEU" if ok else "SEM RESPOSTA"}</span>'
                f'<span style="font-size:.7rem;color:#94a3b8;margin-left:auto">'
                f'{v["aet"]} @ {v["ip"]}:{v["port"]} · {dt:.1f}s</span></div></div>',
                unsafe_allow_html=True)

    st.subheader("Checklist antes de validar no PACS real")
    mod = mod_atual()
    for it in [
        f"Calling AE Title <b>{mod['aet']}</b> cadastrado no PACS (a maioria recusa AET desconhecido)",
        "Called AE Title, host e porta conferidos com o administrador do PACS (padrão 104 ou 11112)",
        "Rede alcançável: porta liberada no firewall",
        "Arquivo com o mesmo SOP da modalidade (ex.: MR para ressonância) — pasta Teste de Envio",
        "Ordem: C-ECHO → C-STORE → C-FIND. Se o C-ECHO falhar, a associação não passou.",
    ]:
        st.markdown(f"- [ ] {it}")


def pg_testes():
    st.title("Testes")
    mod = mod_atual()
    d = dests()
    st.caption(f"Origem: {mod['nome']} ({mod['aet']}) · PACS "
               f"{d['pacs']['aet']} @ {d['pacs']['ip']}:{d['pacs']['port']}")

    with st.expander("Filtros dos testes"):
        f1, f2, f3, f4 = st.columns(4)
        f1.text_input("Arquivo (C-STORE)", "teste_CT.dcm", key="x_arquivo")
        f2.text_input("Paciente (C-FIND / MWL)", "*", key="x_patient")
        f3.text_input("Modalidade (MWL)", "", key="x_modality")
        f4.text_input("Data (MWL)", "", key="x_date")
        g1, g2 = st.columns(2)
        g1.text_input("Station AE Title (MWL)", mod["aet"], key="x_station")
        g2.checkbox("ENVIO: usar o PACS real em vez do simulador local", key="x_pacs_real")
        mf_envio = PASTA_ENVIO / "manifesto.json"
        tags = []
        if mf_envio.exists():
            tags = sorted({m["tag"] for m in json.loads(mf_envio.read_text(encoding="utf-8"))})
        if tags:
            st.caption("Imagens do ENVIO (vazio = todas). A escolha vale também para a bateria.")
            st.multiselect("Imagens do ENVIO (por grupo)", tags, key="sel_tags")
    x = extra()

    st.subheader("Escolher os testes")
    opcoes = [(t, f"{ti} — {sub}") for t, ti, sub, _ in TESTES]
    sel = st.multiselect("Testes da bateria", [t for t, _ in opcoes],
                         default=[t for t, _, _, _ in TESTES], key="testes_sel",
                         format_func=lambda t: dict((a, b) for a, b in opcoes)[t])
    st.caption(f"Serão executados: **{len(sel)} de {len(TESTES)}** testes.")

    st.subheader("Executar um caso avulso")
    cols = st.columns(2)
    for i, (tid, titulo, sub, desc) in enumerate(TESTES):
        with cols[i % 2]:
            r = st.session_state["results"].get(tid)
            if r:
                cab = (f"{titulo} <span class=\"pill p-{'ok' if r['ok'] else 'er'}\">"
                       f"{'PASS' if r['ok'] else 'FAIL'} {r['dt']:.1f}s</span>")
            else:
                cab = f"{titulo} <span class=\"pill p-neu\">não testado</span>"
            card(cab, desc,
                 f'<div class="kv" style="font-size:.76rem">'
                 f'{desc_envio(tid, mod["aet"], d, x)}</div>')
            if st.button(f"Rodar {titulo}", key=f"b_{tid}", use_container_width=True):
                with st.container():
                    rodar(tid, titulo)
                st.rerun()

    st.subheader("Logs")
    for tid, titulo, _, _ in TESTES:
        r = st.session_state["results"].get(tid)
        if not r:
            continue
        with st.expander(f"{titulo} — {'PASS' if r['ok'] else 'FAIL'} "
                         f"({r['dt']:.1f}s, {r['quando']})"):
            st.code(r["log"][-4000:], language="text")

    st.subheader("Bateria de testes")
    if st.button(f"Rodar bateria ({len(sel)} testes) e gerar relatório", type="primary",
                 disabled=not sel):
        ph = st.progress(0.0, text="Iniciando bateria...")
        console = st.empty()
        linhas = []
        for i, tid in enumerate(sel):
            titulo = next((ti for t, ti, _, _ in TESTES if t == tid), tid)
            ph.progress(i / len(sel), text=f"[{i + 1}/{len(sel)}] {titulo} — executando")
            ok, dt, log = rodar(tid, titulo, console=console, barra=False)
            linhas.append((tid, titulo, ok, dt, log))
        np = sum(1 for l in linhas if l[2])
        ph.progress(1.0, text=f"Concluído: {np}/{len(linhas)} PASS")
        txt = resumo_md(mod, d, [(a, b, c, dd) for a, b, c, dd, _ in linhas], np, len(linhas))
        fname = f"relatorio_{mod['aet']}_{datetime.now():%Y%m%d_%H%M%S}.md"
        (REL_DIR / fname).write_text(txt, encoding="utf-8")
        st.session_state["last_rel"] = (fname, txt)
        st.rerun()

    if st.session_state["last_rel"]:
        fname, txt = st.session_state["last_rel"]
        st.success(f"Relatório salvo em relatorios/{fname}")
        st.download_button("Baixar relatório", txt, file_name=fname, key="dl_testes")


def pg_imagens():
    st.title("Imagens de teste (envio)")
    st.caption("Jogo de imagens DICOM válidas que o ENVIO envia ao PACS como se a "
               "nossa fosse a modalidade.")
    d = dests()
    st.markdown(
        f'<div class="card"><div class="kv">'
        f'ENVIO de <b>{len(list(PASTA_IMG.glob("*.dcm")))}</b> imagens reais &nbsp;&rarr;&nbsp; '
        f'PACS {d["pacs"]["aet"]} @ {d["pacs"]["ip"]}:<b>{d["pacs"]["port"]}</b><br>'
        f'Cada imagem: C-STORE &rarr; C-FIND &rarr; C-MOVE + SHA-256 do array de pixels.'
        f'</div></div>', unsafe_allow_html=True)

    mf = PASTA_ENVIO / "manifesto.json"
    if not mf.exists():
        st.warning('Sem manifesto.json — rode: python "Teste de Envio\\gerar_imagens_teste.py"')
        return
    dados = json.loads(mf.read_text(encoding="utf-8"))
    tags = sorted({m["tag"] for m in dados})
    sel_atual = st.session_state.get("sel_tags", [])

    st.dataframe([{
        "enviar": (m["tag"] in sel_atual or not sel_atual), "imagem": m["tag"],
        "modalidade": m["modality"], "SOP Class": m["sop_classe_nome"][:34],
        "Transfer Syntax": m["transfer_syntax_nome"].replace("Explicit VR ", "EVR ")
                                                   .replace("Implicit VR ", "IVR "),
        "pixels": f'{m["rows"]}x{m["columns"]}x{m["frames"]}f',
        "KB": round(m["bytes_pixels"] / 1024),
        "sha256": m["pixel_sha256"][:12] + "…",
    } for m in dados], use_container_width=True, hide_index=True)

    st.subheader("Selecionar imagens para enviar")
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("Todas", use_container_width=True, key="sel_all"):
        st.session_state["sel_tags"] = tags
        st.rerun()
    if b2.button("Somente CT", use_container_width=True, key="sel_ct"):
        st.session_state["sel_tags"] = ["CT"]
        st.rerun()
    if b3.button("Somente MR", use_container_width=True, key="sel_mr"):
        st.session_state["sel_tags"] = ["MR"]
        st.rerun()
    if b4.button("Limpar seleção (todas)", use_container_width=True, key="sel_none"):
        st.session_state["sel_tags"] = []
        st.rerun()

    escolhidas = st.multiselect("Grupos de imagens (vazio = todas)", tags, key="sel_tags_img")
    if escolhidas != sel_atual:
        st.session_state["sel_tags"] = escolhidas
        st.rerun()
    st.caption(f"Serão enviadas: **{len(tags) if not escolhidas else len(escolhidas)}** "
               f"imagem(ns). A seleção vale também para a página Testes.")

    f1, f2, f3 = st.columns(3)
    if f1.button("Gerar exemplos sintéticos", use_container_width=True,
                 help="Imagens artificiais em Teste de Envio/sinteticas — "
                      "não entram no jogo de envio"):
        run_progresso(["Teste de Envio/gerar_imagens_teste.py"], cwd=str(BASE),
                      rotulo="Gerando exemplos sintéticos", total=12, timeout=180)
        st.rerun()
    if f2.button("Rodar ENVIO só com a seleção", type="primary", use_container_width=True):
        with st.container():
            rodar("envio", "ENVIO (seleção)")
        st.rerun()
    if f3.button("Abrir pasta", use_container_width=True):
        os.startfile(str(PASTA_ENVIO))

    rec = sorted((BASE / "recuperado").glob("*.dcm"))
    st.subheader("Voltaram do PACS (conferência por C-MOVE)")
    if rec:
        st.caption(f"{len(rec)} instância(s) recuperada(s) e conferida(s) por SHA-256.")
        st.dataframe([{"arquivo": f.name[:56], "KB": round(f.stat().st_size / 1024)}
                      for f in rec], use_container_width=True, hide_index=True)
    else:
        st.caption("Nada recuperado ainda. Rode o ENVIO com C-FIND e C-MOVE habilitados.")

    esp = sorted(PASTA_ESPECIAIS.glob("*.dcm")) if PASTA_ESPECIAIS.exists() else []
    st.subheader("Casos de borda (teste negativo)")
    st.caption("Arquivos com anomalia proposital — o PACS deveria recusar ou aceitar "
               "com aviso. Ficam fora do jogo de envio. Veja CREDITAOS.md.")
    if esp:
        st.dataframe([{"arquivo": f.name[:52], "KB": round(f.stat().st_size / 1024, 1)}
                      for f in esp], use_container_width=True, hide_index=True)
        st.caption("Para testar um deles contra o PACS, use o teste C-STORE com "
                   "o campo “Arquivo” apontando para este caminho.")
    else:
        st.caption("Nenhum caso de borda baixado.")


def _linhas_worklist(log):
    """Extrai as linhas @@W do script de atendimento."""
    itens = []
    for ln in str(log or "").splitlines():
        ln = ln.strip()
        if ln.startswith("@@W "):
            try:
                itens.append(json.loads(ln[4:]))
            except Exception:
                pass
    return itens


def pg_atendimento():
    st.title("Atendimento da modalidade")
    st.caption("Fluxo de um equipamento real: consultar a worklist no RIS, escolher o "
               "exame da fila e enviar a imagem para dentro daquele estudo.")
    mod = mod_atual()
    d = dests()

    st.markdown(
        f'<div class="card"><div class="kv">'
        f'<b>Equipamento:</b> {mod["nome"]} — AE Title <b>{mod["aet"]}</b><br>'
        f'<b>RIS (worklist):</b> {d["ris"]["aet"]} @ {d["ris"]["ip"]}:'
        f'<b>{d["ris"]["port"]}</b><br>'
        f'<b>PACS (destino):</b> {d["pacs"]["aet"]} @ {d["pacs"]["ip"]}:'
        f'<b>{d["pacs"]["port"]}</b><br>'
        f'<b>Impressora:</b> {d["prn"]["aet"]} @ {d["prn"]["ip"]}:'
        f'<b>{d["prn"]["port"]}</b></div></div>', unsafe_allow_html=True)

    # ---------------- etapa 1: consultar a worklist ----------------
    st.subheader("1 · Consultar a worklist no servidor (RIS)")
    f1, f2, f3, f4 = st.columns(4)
    fl_mod = f1.selectbox("Modalidade", [""] + MODALIDADES_MEDICAS, index=0,
                          key="at_mod", format_func=lambda v: v or "Todas")
    fl_data = f2.text_input("Data (AAAAMMDD)", "", key="at_data")
    fl_pac = f3.text_input("Paciente", "", key="at_pac",
                           help="Aceita parte do nome, ex.: SILVA")
    fl_est = f4.text_input("Station AE Title", "", key="at_est")
    st.caption("Deixe em branco para não filtrar. O filtro de paciente também aceita "
               "apenas um trecho do nome.")

    if st.button("Consultar worklist", type="primary"):
        cmd = ["13_atendimento.py", "--consultar", "--aet", mod["aet"],
               "--ris-aet", d["ris"]["aet"], "--ris-ip", d["ris"]["ip"],
               "--ris-port", str(d["ris"]["port"])]
        if fl_mod:
            cmd += ["--modalidade", fl_mod]
        if fl_data:
            cmd += ["--data", fl_data]
        if fl_pac:
            cmd += ["--paciente", fl_pac]
        if fl_est:
            cmd += ["--estacao", fl_est]
        with st.container():
            ok, dt, log = run_progresso(cmd, cwd=str(BASE), rotulo="Consultando worklist",
                                        timeout=60)
        st.session_state["at_fila"] = _linhas_worklist(log)
        st.session_state["at_log_consulta"] = log
        st.session_state["at_dt"] = dt
        if st.session_state["at_fila"]:
            st.success(f"{len(st.session_state['at_fila'])} exame(s) na fila.")
        else:
            st.warning("Nenhum exame na fila. Confira os filtros e se o RIS responde.")
        with st.expander("Log da consulta"):
            st.code(log[-3000:], language="text")
        st.rerun()

    fila = st.session_state.get("at_fila", [])
    if not fila:
        st.info("Consulte a worklist para ver os exames agendados.")
        return

    # ---------------- etapa 2: escolher o exame ----------------
    st.subheader(f"2 · Escolher o exame da fila ({len(fila)} item(ns))")
    st.dataframe([{
        "paciente": w["paciente"], "id": w["id"], "modalidade": w["modalidade"],
        "acesso": w["acesso"], "procedimento": w["procedimento"],
        "data": w["data"], "hora": w["hora"], "estacao": w["estacao"],
        "study_uid": w["estudo_uid"][:28] + "…",
    } for w in fila], use_container_width=True, hide_index=True)

    rotulos = {w["chave"]: f'{w["paciente"]} · {w["modalidade"]} · {w["acesso"]} · '
                         f'{w["procedimento"]}' for w in fila}
    escolhidos = st.multiselect("Exames a realizar", list(rotulos.keys()),
                                key="at_sel", format_func=lambda k: rotulos[k])
    st.caption(f"Selecionados: **{len(escolhidos)}** exame(s).")

    # ---------------- etapa 3: imagens e opções ----------------
    st.subheader("3 · Imagens do exame")
    mf = PASTA_ENVIO / "manifesto.json"
    tags = []
    if mf.exists():
        tags = sorted({m["tag"] for m in json.loads(mf.read_text(encoding="utf-8"))})
    g1, g2, g3 = st.columns(3)
    imgs = g1.multiselect("Imagens para enviar no estudo", tags or ["CT"],
                          default=["CT"], key="at_imgs",
                          help="Todas as imagens escolhidas entram no MESMO estudo, "
                               "cada uma em sua série.")
    usar_print = g2.checkbox("Imprimir cada exame", value=False, key="at_print")
    verificar = g3.checkbox("Conferir no PACS depois (C-FIND do estudo)", value=True,
                            key="at_verif")
    if tags and "GERAR" not in tags:
        imgs = list(imgs) + ["GERAR"] if st.session_state.get("at_gerar") else imgs
    if st.checkbox("Gerar imagem nova na hora (sem usar a biblioteca)", key="at_gerar"):
        if "GERAR" not in imgs:
            imgs.append("GERAR")

    if not escolhidos:
        st.info("Escolha um ou mais exames da fila para continuar.")
        return

    st.markdown(
        f'<div class="card"><div class="kv">'
        f'<b>O que será enviado:</b> para {len(escolhidos)} exame(s), '
        f'{len(imgs)} imagem(ns) cada — {", ".join(imgs) or "nenhuma"}.<br>'
        f'Cada imagem assume o <b>StudyInstanceUID, AccessionNumber, PatientName e '
        f'PatientID do exame agendado</b>, e vai para '
        f'{d["pacs"]["aet"]} @ {d["pacs"]["ip"]}:{d["pacs"]["port"]}.'
        f'</div></div>', unsafe_allow_html=True)

    # ---------------- etapa 4: executar ----------------
    st.subheader("4 · Executar")
    if st.button(f"Atender {len(escolhidos)} exame(s)", type="primary"):
        cmd = ["13_atendimento.py", "--enviar", "--aet", mod["aet"],
               "--chaves", ";".join(escolhidos),
               "--imagens", ",".join(i for i in imgs if i != "GERAR") or "CT",
               "--pacs-aet", d["pacs"]["aet"], "--pacs-ip", d["pacs"]["ip"],
               "--pacs-port", str(d["pacs"]["port"]),
               "--ris-aet", d["ris"]["aet"], "--ris-ip", d["ris"]["ip"],
               "--ris-port", str(d["ris"]["port"]),
               "--print-aet", d["prn"]["aet"], "--print-ip", d["prn"]["ip"],
               "--print-port", str(d["prn"]["port"])]
        if "GERAR" in imgs:
            cmd += ["--imagens", ",".join([i for i in imgs if i != "GERAR"] + ["CT"])]
        if usar_print:
            cmd.append("--imprimir")
        if verificar:
            cmd.append("--verificar")
        total = len(escolhidos) * (len(imgs) + 1 + (1 if usar_print else 0)
                                  + (1 if verificar else 0))
        with st.container():
            ok, dt, log = run_progresso(cmd, cwd=str(BASE), rotulo="Atendimento",
                                        total=total, timeout=900)
        st.session_state["at_log_envio"] = log
        st.session_state["at_ok"] = ok
        (st.success if ok else st.error)(
            f"Atendimento finalizado em {dt:.1f}s — "
            f"{'tudo enviado' if ok else 'houve falhas (veja o log)'}")
        st.rerun()

    if st.session_state.get("at_log_envio"):
        with st.expander("Log do atendimento", expanded=True):
            st.code(st.session_state["at_log_envio"][-4000:], language="text")


def pg_diag():
    st.title("Diagnóstico")
    st.caption("Simuladores locais, o que chegou no outro lado e histórico de relatórios.")

    st.subheader("Simuladores locais (padrão)")
    p = st.session_state["procs"]
    d = dests()
    sims = {"PACS": ("01_scp_pacs.py", d["pacs"]["port"]),
            "RIS": ("05_mwl_scp.py", d["ris"]["port"]),
            "Impressora": ("06_print_scp.py", d["prn"]["port"])}
    cols = st.columns(3)
    for col, (rot, (script, porta)) in zip(cols, sims.items()):
        chave = f'sim_{rot}'
        rodando = chave in p and p[chave].poll() is None
        with col:
            card(f"{rot}", f"porta {porta}",
                 f'<div class="kv"><span class="pill p-{"ok" if rodando else "neu"}">'
                 f'{"em execução PID " + str(p[chave].pid) if rodando else "parado"}'
                 f'</span></div>')
            if rodando:
                if st.button("Derrubar", key=f"d_{chave}", use_container_width=True):
                    p[chave].terminate()
                    p.pop(chave)
                    st.rerun()
            elif st.button("Subir", key=f"u_{chave}", use_container_width=True):
                p[chave] = subprocess.Popen(
                    [PY, script, "--port", str(porta)], cwd=str(BASE),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                time.sleep(1.2)
                st.rerun()

    st.subheader("Arquivos recebidos (PACS)")
    fs = sorted((BASE / "received").glob("*.dcm"))
    fs2 = sorted((BASE / "received_envio").glob("*.dcm"))
    st.caption(f"received/: {len(fs)} · received_envio/: {len(fs2)}")
    if fs or fs2:
        st.dataframe([{"pasta": f.parent.name, "arquivo": f.name[:56],
                       "KB": round(f.stat().st_size / 1024)}
                      for f in (fs + fs2)[-25:]], use_container_width=True, hide_index=True)

    st.subheader("Impressora")
    logf = BASE / "printed" / "print_jobs.log"
    st.code(logf.read_text(encoding="utf-8")[-2500:] if logf.exists()
            else "(nenhuma impressão ainda)", language="text")

    st.subheader("Worklist do RIS")
    wlf = BASE / "worklist.json"
    txt = st.text_area("worklist.json", wlf.read_text(encoding="utf-8") if wlf.exists() else "[]",
                       height=200, label_visibility="collapsed")
    if st.button("Salvar worklist.json"):
        try:
            json.loads(txt)
            wlf.write_text(txt, encoding="utf-8")
            st.success("Worklist salva.")
        except Exception as e:
            st.error(f"JSON inválido: {e}")

    st.subheader("Relatórios")
    rels = sorted(REL_DIR.glob("*.md"), key=lambda f: f.name, reverse=True)
    if rels:
        for f in rels[:12]:
            col1, col2 = st.columns([5, 1])
            col1.write(f"`{f.name}`")
            if col2.button("Abrir", key=f"o_{f.name}", use_container_width=True):
                os.startfile(str(f))
    else:
        st.caption("Nenhum relatório ainda.")


# ----------------------------------------------------------------------------
nav = st.navigation([
    st.Page(pg_visao, title="Visão geral", icon="📊", default=True),
    st.Page(pg_modalidades, title="Modalidades", icon="🏥"),
    st.Page(pg_equipamentos, title="Equipamentos", icon="🛠"),
    st.Page(pg_atendimento, title="Atendimento", icon="🩻"),
    st.Page(pg_destinos, title="Destinos", icon="🎯"),
    st.Page(pg_testes, title="Testes", icon="🧪"),
    st.Page(pg_imagens, title="Imagens", icon="🖼"),
    st.Page(pg_diag, title="Diagnóstico", icon="📋"),
])
with st.sidebar:
    st.markdown("### Testes DICOM")
    st.caption("Simulador de modalidade contra PACS, RIS e impressora.")
    st.caption(f"**Origem ativa:** {mod_atual()['aet']}")
    st.divider()
    tema_atual = st.session_state.get("tema", "claro")
    escolha = st.radio("Aparência", ["Claro", "Escuro"],
                       index=0 if tema_atual == "claro" else 1, horizontal=True,
                       key="tema_radio", label_visibility="collapsed")
    novo = "claro" if escolha == "Claro" else "escuro"
    if novo != tema_atual:
        salvar_cfg({"tema": novo})
        st.session_state["tema"] = novo
        st.rerun()
    st.caption(f"Tema: **{'Claro' if tema_atual == 'claro' else 'Escuro'}**")
    st.divider()
    d = dests()
    st.caption("Ligação ativa")
    st.markdown(
        f'<div style="font-size:.72rem;line-height:1.8;color:#94a3b8">'
        f'<b style="color:var(--text-color,#0f172a)">{mod_atual()["aet"]}</b><br>'
        f'PACS {d["pacs"]["aet"]}:{d["pacs"]["port"]}<br>'
        f'RIS {d["ris"]["aet"]}:{d["ris"]["port"]}<br>'
        f'Impressora {d["prn"]["aet"]}:{d["prn"]["port"]}</div>',
        unsafe_allow_html=True)
nav.run()