"""Várias modalidades ao mesmo tempo (carga / estresse)."""
from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor

from .events import Emissor
from .exam import executar_exame
from .profiles import Destino, Equipamento


def rodar_frota(equipamentos: list[Equipamento], dest: Destino, exames_cada=1,
                intervalo=(0.0, 0.0), usar_worklist=True, callback=None):
    """Cada equipamento roda `exames_cada` exames em sua própria thread.
    Devolve lista de ResultadoExame."""
    def trabalho(eq):
        out = []
        for n in range(exames_cada):
            if n and intervalo[1] > 0:
                time.sleep(random.uniform(*intervalo))
            em = Emissor(nome=eq.nome, imprimir=False, callback=callback)
            out.append(executar_exame(eq, dest, em=em, usar_worklist=usar_worklist))
        return out

    with ThreadPoolExecutor(max_workers=max(1, len(equipamentos))) as ex:
        futs = [ex.submit(trabalho, eq) for eq in equipamentos]
        return [r for f in futs for r in f.result()]
