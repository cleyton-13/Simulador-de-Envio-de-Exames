"""Fluxo ponta a ponta contra o ServidorVirtual (sem equipamento real)."""
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dicomsim import profiles, steps
from dicomsim.events import Emissor
from dicomsim.exam import executar_exame
from dicomsim.fleet import rodar_frota
from dicomsim.identidade import Registro
from dicomsim.netutil import Alvo
from dicomsim.servers import ServidorVirtual


def porta():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


@pytest.fixture()
def srv(tmp_path):
    s = ServidorVirtual("PACS_TESTE", porta(), tmp_path).iniciar()
    yield s
    s.parar()


def destino(s):
    return profiles.Destino(s.alvo, s.alvo, s.alvo)


@pytest.fixture(autouse=True)
def registro_isolado(tmp_path, monkeypatch):
    """Nenhum teste grava em estado/envios.json de verdade."""
    import dicomsim.identidade as idt
    monkeypatch.setattr(idt, "ARQUIVO", tmp_path / "envios.json")
    monkeypatch.setattr(idt.Registro.__init__, "__defaults__", (tmp_path / "envios.json",))


def eq(**kw):
    base = dict(nome="CT T", aet="CT_T", modalidade="CT", fabricante="GE",
                series=[{"descricao": "A", "imagens": 2}])
    base.update(kw)
    return profiles.Equipamento(**base)


def test_echo_e_worklist(srv):
    em = Emissor(imprimir=False)
    itens = steps.consultar_worklist(em, "CT_T", srv.alvo, modalidade="CT")
    assert itens and all(i["modalidade"] == "CT" for i in itens)


def test_exame_completo_com_mpps_e_commitment(srv):
    e = eq(commitment=True, imprimir=True)
    em = Emissor(nome=e.nome, imprimir=False)
    r = executar_exame(e, destino(srv), em=em)
    assert r.ok, em.resumo()
    assert r.imagens == 2 and len(srv.instancias) == 2
    assert [m["status"] for m in srv.mpps.values()] == ["COMPLETED"]
    assert len(srv.filmes) == 1
    etapas = {x["etapa"]: x["status"] for x in em.resumo()["etapas"]}
    assert etapas["commitment"] == "ok" and etapas["print"] == "ok"


def test_estudo_da_worklist_e_usado(srv):
    r = executar_exame(eq(), destino(srv), em=Emissor(imprimir=False))
    esperados = {w["StudyInstanceUID"] for w in srv.worklist}
    assert r.estudo_uid in esperados


def test_commitment_detecta_imagem_ausente(srv):
    srv.falhar_commitment = True
    em = Emissor(imprimir=False)
    r = executar_exame(eq(commitment=True), destino(srv), em=em)
    assert not r.ok
    assert any(f.etapa == "commitment" for f in em.falhas())


def test_pacs_fora_do_ar_falha_sem_travar():
    d = profiles.Destino(Alvo("NADA", "127.0.0.1", porta()))
    em = Emissor(imprimir=False)
    r = executar_exame(eq(), d, item={"nome": "X^Y", "id": "1"}, em=em)
    assert not r.ok and r.imagens == 0


def test_frota_paralela(srv):
    eqs = [eq(nome=f"EQ{i}", aet=f"EQ_{i}", series=[{"descricao": "S", "imagens": 1}])
           for i in range(4)]
    res = rodar_frota(eqs, destino(srv), exames_cada=2)
    assert len(res) == 8 and all(r.ok for r in res)
    assert len(srv.instancias) == 8


def test_perfis_json_valido():
    dados = profiles.carregar()
    for e in profiles.equipamentos(dados):
        profiles.destino(dados, e.destino)


def test_envio_novo_gera_uids_inéditos(srv):
    e = eq(series=[{"descricao": "S", "imagens": 2}], identidade="novo")
    executar_exame(e, destino(srv), em=Emissor(imprimir=False))
    executar_exame(e, destino(srv), em=Emissor(imprimir=False))
    assert len(srv.instancias) == 4          # nada foi sobreposto


def test_envio_sobrepor_reusa_uids(srv):
    e = eq(series=[{"descricao": "S", "imagens": 2}], identidade="sobrepor")
    executar_exame(e, destino(srv), em=Emissor(imprimir=False))
    primeiros = set(srv.instancias)
    executar_exame(e, destino(srv), em=Emissor(imprimir=False))
    assert len(srv.instancias) == 2 and set(srv.instancias) == primeiros


def test_imagens_reais_rotacionam():
    from dicomsim import library
    uids = {str(library.obter_imagem("CT", i, "real").SOPInstanceUID) for i in range(4)}
    assert len(uids) > 1


def test_anomalas_nao_derrubam_o_exame(srv):
    e = eq(origem_imagens="anomala", mpps=False,
           series=[{"descricao": "X", "imagens": 6}])
    em = Emissor(imprimir=False)
    r = executar_exame(e, destino(srv), em=em)
    assert r.ok, em.resumo()          # recusas viram aviso, não falha
    assert any(ev.status == "aviso" for ev in em.eventos) or r.imagens > 0


def test_todas_as_imagens_reais_sao_aceitas(srv):
    """Cada arquivo real do manifesto (incl. JPEG2000, JPEG-LS, RLE, big endian)."""
    from dicomsim import library
    for mod in ("CT", "MR", "NM", "US", "CR", "OT", "SR"):
        n = len(library.listar_reais(mod))
        if not n:
            continue
        e = eq(modalidade=mod, series=[{"descricao": "T", "imagens": n}], mpps=False)
        em = Emissor(imprimir=False)
        r = executar_exame(e, destino(srv), em=em)
        assert r.ok and r.imagens == n, (mod, em.resumo())


def test_destino_sem_mpps_nao_derruba_o_exame(srv, monkeypatch):
    """PACS que aceita a conexão mas não suporta MPPS: aviso, e o C-STORE segue."""
    from pynetdicom.sop_class import ModalityPerformedProcedureStep
    srv.parar()
    from pynetdicom import AE, evt
    from pynetdicom.presentation import StoragePresentationContexts
    ae = AE(ae_title="SEM_MPPS")
    ae.add_supported_context("1.2.840.10008.1.1")
    for u in ("1.2.840.10008.5.1.4.1.1.2", "1.2.840.10008.5.1.4.1.1.7"):   # sem MPPS
        ae.add_supported_context(u)
    p = porta()
    s2 = ae.start_server(("127.0.0.1", p), block=False,
                         evt_handlers=[(evt.EVT_C_STORE, lambda e: 0x0000)])
    try:
        d = profiles.Destino(Alvo("SEM_MPPS", "127.0.0.1", p))
        em = Emissor(imprimir=False)
        r = executar_exame(eq(mpps=True), d, item={"nome": "A^B", "id": "1"}, em=em)
        etapas = {e.etapa: e.status for e in em.eventos if e.status != "info"}
        assert etapas["mpps-inicio"] == "aviso"
        assert r.ok and r.imagens == 2
    finally:
        s2.shutdown()


def test_um_equipamento_por_modalidade():
    dados = profiles.carregar()
    mods = {e["modalidade"] for e in dados["equipamentos"]}
    assert set(profiles.MODALIDADES) <= mods


def test_todos_os_equipamentos_rodam(srv):
    for e in profiles.equipamentos(profiles.carregar()):
        e.destino = "local"
        em = Emissor(imprimir=False)
        r = executar_exame(e, destino(srv), em=em)
        assert r.ok, (e.nome, em.resumo())


def test_cadastro_de_destinos():
    import copy
    d = copy.deepcopy(profiles.carregar())
    novo = profiles.destino_para_dict(profiles.MODELOS_DESTINO["Orthanc (padrão)"])
    profiles.salvar_destino(d, "Meu Orthanc", novo)
    with pytest.raises(ValueError):                      # nome duplicado
        profiles.salvar_destino(d, "Meu Orthanc", novo)
    with pytest.raises(ValueError):                      # AET > 16
        profiles.salvar_destino(d, "X", {"pacs": {"aet": "A" * 17, "ip": "1.1.1.1", "porta": 1}})
    profiles.salvar_destino(d, "Orthanc Clinica", novo, chave_antiga="Meu Orthanc")
    assert "Meu Orthanc" not in d["destinos"]
    profiles.excluir_destino(d, "Orthanc Clinica")
    with pytest.raises(ValueError):                      # em uso por equipamentos
        profiles.excluir_destino(d, "local")


def test_cadastro_de_equipamento():
    import copy
    d = copy.deepcopy(profiles.carregar())
    eqd = {"nome": "Novo", "aet": "NOVO_1", "modalidade": "DX", "destino": "local",
           "series": [{"descricao": "A", "imagens": 1}]}
    profiles.salvar_equipamento(d, dict(eqd))
    with pytest.raises(ValueError):
        profiles.salvar_equipamento(d, dict(eqd))
    profiles.excluir_equipamento(d, "Novo")
    assert all(e["nome"] != "Novo" for e in d["equipamentos"])
