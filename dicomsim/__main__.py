"""CLI:  python -m dicomsim <comando>

  exame   --equipamento "CT Sala 1"            roda um exame completo
  frota   [--exames 2]                         todos os equipamentos em paralelo
  servidor --port 11112                        PACS+RIS+MPPS+Commitment+Print virtual
  listar                                       equipamentos e destinos do perfis.json
"""
import argparse
import json
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from . import profiles
from .events import Emissor
from .exam import executar_exame
from .fleet import rodar_frota


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dicomsim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exame")
    e.add_argument("--equipamento", required=True)
    e.add_argument("--destino", help="sobrepõe o destino do equipamento")
    e.add_argument("--sem-worklist", action="store_true")
    f = sub.add_parser("frota")
    f.add_argument("--exames", type=int, default=1)
    f.add_argument("--destino", default=None)
    sub.add_parser("listar")
    s = sub.add_parser("servidor")
    s.add_argument("--aet", default="PACS_TESTE")
    s.add_argument("--port", type=int, default=11112)
    a, resto = ap.parse_known_args(argv)

    if a.cmd == "servidor":
        from .servers import main as srv_main
        sys.argv = ["servidor", "--aet", a.aet, "--port", str(a.port)] + resto
        return srv_main()

    dados = profiles.carregar()
    if a.cmd == "listar":
        for eq in profiles.equipamentos(dados):
            print(f"{eq.nome:20} {eq.aet:12} {eq.modalidade:3} {eq.fabricante:10} -> {eq.destino}")
        return 0
    if a.cmd == "exame":
        eq = profiles.equipamento(dados, a.equipamento)
        dest = profiles.destino(dados, a.destino or eq.destino)
        em = Emissor(nome=eq.nome)
        r = executar_exame(eq, dest, em=em, usar_worklist=not a.sem_worklist)
        print(json.dumps(em.resumo(), ensure_ascii=False))
        return 0 if r.ok else 1
    if a.cmd == "frota":
        eqs = profiles.equipamentos(dados)
        dest = profiles.destino(dados, a.destino or eqs[0].destino)
        res = rodar_frota(eqs, dest, a.exames)
        for r in res:
            print(f"{'OK ' if r.ok else 'FALHA'} {r.equipamento}: {r.imagens} imagem(ns)")
        return 0 if all(r.ok for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
