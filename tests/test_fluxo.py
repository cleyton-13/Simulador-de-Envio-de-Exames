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
    for mod in ("CT", "MR", "CR", "DX", "US", "XA", "MG", "RF", "PT", "NM", "OT", "SR"):
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


def test_controle_total_arquivos_filtros_e_mpps(srv):
    from dicomsim import library
    arqs = library.listar_reais("MR")[:2]
    em = Emissor(imprimir=False)
    r = executar_exame(eq(modalidade="MR"), destino(srv), em=em, arquivos=arqs,
                       filtros_wl={"modalidade": "MR"}, status_mpps="DISCONTINUED")
    assert r.ok and r.imagens == 2
    assert [m["status"] for m in srv.mpps.values()] == ["DISCONTINUED"]


def test_timeouts_ajustaveis():
    from dicomsim import netutil
    antigo = dict(netutil.TIMEOUTS)
    try:
        netutil.TIMEOUTS.update(acse=3, dimse=7)
        ae = netutil.nova_ae("X")
        assert ae.acse_timeout == 3 and ae.dimse_timeout == 7
    finally:
        netutil.TIMEOUTS.update(antigo)


def test_nome_legivel():
    from dicomsim.util import nome_legivel
    assert nome_legivel("Acassio^Clayton Bartalini") == "Clayton Bartalini Acassio"
    assert nome_legivel("SILVA^JOAO^PEDRO") == "JOAO PEDRO SILVA"
    assert nome_legivel("Souza") == "Souza"
    assert nome_legivel("") == "(sem nome)"
    assert nome_legivel("Doe^Jane^^Dra^") == "Dra Jane Doe"


def test_cadastro_e_envio_de_paciente_com_acento(srv):
    import copy
    from pydicom import dcmread
    d = copy.deepcopy(profiles.carregar())
    p = {"nome": "João Ação", "sobrenome": "Conceição", "id": "PRONT123",
         "nascimento": "19900131", "sexo": "M"}
    profiles.salvar_paciente(d, p)
    with pytest.raises(ValueError):                       # ID repetido
        profiles.salvar_paciente(d, dict(p))
    with pytest.raises(ValueError):                       # separador DICOM no nome
        profiles.salvar_paciente(d, {**p, "id": "X", "nome": "A^B"})
    item = profiles.item_de_paciente(p, "CT")
    assert item["nome"] == "Conceição^João Ação"
    em = Emissor(imprimir=False)
    r = executar_exame(eq(series=[{"descricao": "S", "imagens": 1}], mpps=False),
                       destino(srv), item=item, em=em)
    assert r.ok
    arq = next(srv.pasta.glob("*.dcm"))
    ds = dcmread(arq)
    assert str(ds.PatientName) == "Conceição^João Ação"
    assert str(ds.PatientID) == "PRONT123" and ds.PatientBirthDate == "19900131"
    assert ds.SpecificCharacterSet in ("ISO_IR 100", "ISO_IR 192")


# ------------------------------------------------------------ diagnóstico e cenários
def test_diagnostico_servidor_ok(srv):
    from dicomsim import diagnostico
    passos = diagnostico.diagnosticar("CT_T", destino(srv), "CT")
    por = {p.id: p for p in passos}
    assert diagnostico.conexao_ok(passos)
    assert por["servicos"].status == "ok" and "MPPS" in por["servicos"].detalhe
    assert por["worklist"].status == "ok"
    txt = diagnostico.relatorio_texto(passos, "CT_T", destino(srv), "CT Teste")
    assert "está funcionando" in txt


def test_diagnostico_porta_fechada():
    from dicomsim import diagnostico
    d = profiles.Destino(Alvo("X", "127.0.0.1", porta()))
    passos = diagnostico.diagnosticar("CT_T", d)
    assert passos[0].status == "falha" and "firewall" in passos[0].dica
    assert all(p.status == "pulado" for p in passos[1:])
    assert not diagnostico.conexao_ok(passos)


def test_diagnostico_porta_aberta_sem_dicom():
    """Porta aberta de um serviço que não é DICOM (ex.: HTTP)."""
    import threading
    from dicomsim import diagnostico
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); sk.listen(5)
    p = sk.getsockname()[1]

    def aceita():
        try:
            c, _ = sk.accept(); c.recv(10); c.close()
        except OSError:
            pass
    threading.Thread(target=aceita, daemon=True).start()
    try:
        passos = diagnostico.diagnosticar("CT_T", profiles.Destino(Alvo("X", "127.0.0.1", p)))
        por = {x.id: x for x in passos}
        assert por["rede"].status == "ok" and por["aet"].status == "falha"
    finally:
        sk.close()


def test_diagnostico_aet_recusado(srv):
    """Servidor que só aceita um AE Title: o diagnóstico explica a recusa."""
    from pynetdicom import AE, evt
    from dicomsim import diagnostico
    ae = AE(ae_title="SO_ESTE")
    ae.add_supported_context("1.2.840.10008.1.1")
    ae.require_calling_aet = ["PERMITIDO"]
    p = porta()
    s2 = ae.start_server(("127.0.0.1", p), block=False)
    try:
        passos = diagnostico.diagnosticar("INTRUSO", profiles.Destino(Alvo("SO_ESTE", "127.0.0.1", p)))
        por = {x.id: x for x in passos}
        assert por["aet"].status == "falha" and "cadastrado" in por["aet"].dica
    finally:
        s2.shutdown()


def test_cenarios(srv):
    from dicomsim import cenarios
    dados = profiles.carregar()
    e = eq(commitment=False)
    ids = {c["id"] for c in cenarios.lista(dados)}
    assert {"conexao", "exame", "agenda", "reenviar", "carga"} <= ids
    por = {c["id"]: c for c in cenarios.lista(dados)}
    assert cenarios.executar(por["conexao"], dados, e, destino(srv))["ok"]
    assert cenarios.executar(por["exame"], dados, e, destino(srv))["ok"]
    antes = len(srv.instancias)
    assert cenarios.executar(por["reenviar"], dados, e, destino(srv))["ok"]
    assert cenarios.executar(por["reenviar"], dados, e, destino(srv))["ok"]
    assert len(srv.instancias) == antes          # reenviar = mesmas instâncias do último exame
    r = cenarios.executar({"tipo": "frota", "exames": 1}, dados, e, destino(srv))
    falhas = [(x.equipamento, [(e.etapa, e.detalhe) for e in x.eventos if e.status == "falha"])
              for x in r["resultados"] if not x.ok]
    assert r["ok"] and len(r["resultados"]) == len(dados["equipamentos"]), falhas
