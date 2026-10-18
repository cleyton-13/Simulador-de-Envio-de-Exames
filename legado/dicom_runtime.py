"""Execucao de processos com barra de progresso ao vivo (Streamlit).

Os scripts da pasta emitem linhas de progresso no formato:
    @P {"n": 3, "total": 12, "etapa": "C-FIND", "item": "CT", "status": "ok"}
O runner le essas linhas enquanto o processo roda e atualiza a barra, o rotulo
e o console, sem travar a interface.

Se o script nao emitir nada, a barra fica indeterminada (com contador de tempo).
"""

import html
import json
import subprocess
import sys
import time

import streamlit as st

PREFIX = "@P "


def _flags():
    if sys.platform.startswith("win"):
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def emitir(n, total, etapa="", item="", status=""):
    """Usado pelos scripts CLI para reportar progresso."""
    print(PREFIX + json.dumps({"n": n, "total": total, "etapa": etapa,
                               "item": item, "status": status}), flush=True)


def _pintar(ph, box, rotulo, estado, linhas, dt, total, barra):
    if box is not None:
        txt = "\n".join(linhas[-200:])
        box.markdown(f'<pre style="max-height:340px;overflow:auto">{html.escape(txt)}</pre>',
                     unsafe_allow_html=True)
    if not barra or ph is None:
        return
    t = estado["total"] or total or 0
    ped = f'{rotulo} · {dt:.1f}s'
    if estado["etapa"]:
        ped += f' · {estado["etapa"]}'
    if estado["item"]:
        ped += f' {estado["item"]}'
    if estado["status"]:
        ped += f' — {estado["status"]}'
    if t:
        frac = max(0.0, min(1.0, estado["n"] / t))
        ph.progress(frac, text=f"{int(estado['n'])}/{int(t)} · {ped}")
    else:
        ph.markdown(
            f'<div class="card" style="padding:.7rem 1rem"><b>{rotulo}</b> '
            f'<span class="dots"></span> {dt:.1f}s</div>', unsafe_allow_html=True)


def run_progresso(args, *, cwd, rotulo="", total=None, timeout=900, barra=True,
                  console=None, python=None, log_linhas=250):
    """Roda `args` (lista) mostrando progresso. Retorna (ok, segundos, saída)."""
    py = python or sys.executable
    cmd = [py] + list(args)
    ph = st.empty()
    box = console if console is not None else st.empty()

    estado = {"n": 0.0, "total": float(total or 0), "etapa": "", "item": "", "status": ""}
    linhas, saida = [], []
    ok = True
    t0 = time.time()
    ultimo_pintar = 0.0

    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=_flags(),
    )

    for linha in proc.stdout:
        linha = linha.rstrip("\r\n")
        saida.append(linha)
        linhas.append(linha)
        if len(linhas) > log_linhas:
            linhas.pop(0)

        if linha.startswith(PREFIX):
            try:
                d = json.loads(linha[len(PREFIX):])
            except Exception:
                d = {}
            if d.get("n") is not None:
                estado["n"] = float(d["n"])
            if d.get("total"):
                estado["total"] = float(d["total"])
            estado["etapa"] = d.get("etapa", "") or estado["etapa"]
            estado["item"] = d.get("item", "") or ""
            estado["status"] = d.get("status", "") or ""
            if estado["status"] in ("erro", "falha", "FALHOU", "DIFERENTE"):
                ok = False

        agora = time.time()
        if agora - ultimo_pintar > 0.2:
            ultimo_pintar = agora
            _pintar(ph, box, rotulo, estado, linhas, agora - t0, total, barra)
            if agora - t0 > timeout:
                proc.kill()
                ok = False
                linhas.append(f"[TIMEOUT apos {timeout}s — processo encerrado]")
                break

    proc.wait()
    dt = time.time() - t0
    texto = "\n".join(saida)

    for marca in ("FALHOU", "FALHA:", "Traceback", "[ERRO]", "TIMEOUT"):
        if marca in texto:
            ok = False

    if estado["total"] == 0 and not estado["etapa"]:
        estado["n"] = 1
        estado["total"] = 1
        estado["status"] = "concluido" if ok else "falhou"
    else:
        estado["n"] = estado["total"] or 1
    _pintar(ph, box, rotulo, estado, linhas, dt, total, barra)
    return ok, dt, texto