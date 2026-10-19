"""Cenários: receitas prontas de um clique (definidas em perfis.json["cenarios"]).

tipo: diagnostico  -> diagnóstico de conexão
      exame        -> exame completo com paciente de teste (usa o equipamento escolhido)
      agenda       -> atende o próximo exame da worklist do equipamento
      reenviar     -> repete o último exame deste equipamento SOBREPONDO os mesmos UIDs
      frota        -> todos os equipamentos ao mesmo tempo
"""
from __future__ import annotations

from dataclasses import replace

from . import diagnostico, profiles
from .events import Emissor
from .exam import executar_exame
from .fleet import rodar_frota

PADRAO = [
    {"id": "conexao", "nome": "Teste rápido de conexão", "tipo": "diagnostico", "icone": "🔌",
     "descricao": "Verifica rede, AE Title, C-ECHO e serviços do servidor. Não grava nada."},
    {"id": "exame", "nome": "Enviar um exame completo", "tipo": "exame", "icone": "🩻",
     "descricao": "Paciente de teste, imagens reais, com os avisos de início/fim do exame."},
    {"id": "agenda", "nome": "Atender o próximo exame da agenda", "tipo": "agenda", "icone": "📋",
     "descricao": "Busca a worklist deste equipamento e envia as imagens no exame agendado."},
    {"id": "reenviar", "nome": "Reenviar o último exame (sobrepor)", "tipo": "reenviar", "icone": "🔁",
     "descricao": "Manda de novo as mesmas imagens, com os mesmos identificadores: testa duplicata."},
    {"id": "carga", "nome": "Carga: todos os equipamentos juntos", "tipo": "frota", "icone": "🚑",
     "exames": 2, "descricao": "Cada equipamento envia 2 exames ao mesmo tempo."},
]

PRECISA_EQUIPAMENTO = {"diagnostico", "exame", "agenda", "reenviar"}


def lista(dados):
    return dados.get("cenarios") or PADRAO


def executar(cenario, dados, eq: profiles.Equipamento | None, dest: profiles.Destino,
             registro=None, callback=None):
    """Executa e devolve {'tipo', 'ok', 'passos'|'emissor'|'resultados'}."""
    tipo = cenario["tipo"]
    if tipo == "diagnostico":
        passos = diagnostico.diagnosticar(eq.aet, dest, eq.modalidade)
        return {"tipo": tipo, "ok": diagnostico.conexao_ok(passos), "passos": passos}
    if tipo in ("exame", "agenda", "reenviar"):
        em = Emissor(nome=eq.nome, imprimir=False, callback=callback)
        e = replace(eq, identidade="sobrepor" if tipo == "reenviar" else "novo")
        r = executar_exame(e, dest, em=em, usar_worklist=(tipo == "agenda"), registro=registro)
        return {"tipo": tipo, "ok": r.ok, "emissor": em, "resultado": r}
    if tipo == "frota":
        eqs = profiles.equipamentos(dados)
        res = rodar_frota(eqs, dest, int(cenario.get("exames", 1)), callback=callback)
        return {"tipo": tipo, "ok": all(r.ok for r in res), "resultados": res}
    raise ValueError(f"tipo de cenário desconhecido: {tipo}")
