"""AE e associação num só lugar (antes copiados em 4 scripts)."""
from __future__ import annotations

import zlib
from contextlib import contextmanager
from dataclasses import dataclass

from pynetdicom import AE
from pynetdicom.service_class import StorageServiceClass
from pynetdicom.sop_class import Verification, register_uid

# SOP Classes de armazenamento RETIRADAS, mas ainda enviadas por aparelhos antigos.
# O pynetdicom não as conhece e recusaria o envio antes de sair da máquina
# (era a causa do US multiframe falhar com "status=None").
RETIRADAS = {
    "1.2.840.10008.5.1.4.1.1.3": "UltrasoundMultiframeImageStorageRetired",
    "1.2.840.10008.5.1.4.1.1.3.1": "UltrasoundMultiFrameImageStorageRetired2",
    "1.2.840.10008.5.1.4.1.1.5": "NuclearMedicineImageStorageRetired",
    "1.2.840.10008.5.1.4.1.1.6": "UltrasoundImageStorageRetired",
    "1.2.840.10008.5.1.4.1.1.12.3": "XRayAngiographicBiPlaneImageStorageRetired",
}
for _uid, _kw in RETIRADAS.items():
    try:
        register_uid(_uid, _kw, StorageServiceClass)
    except Exception:
        pass


@dataclass
class Alvo:
    """Destino de rede: um serviço remoto (PACS, RIS, impressora)."""
    aet: str
    ip: str = "127.0.0.1"
    porta: int = 104

    def __str__(self):
        return f"{self.aet}@{self.ip}:{self.porta}"


# Ajustáveis em tempo de execução (tela Técnico): segundos.
TIMEOUTS = {"acse": 10, "dimse": 30, "network": 10}


def nova_ae(aet_local, contextos=(), verification=True, acse=None, dimse=None, network=None):
    ae = AE(ae_title=aet_local)
    ae.acse_timeout = acse or TIMEOUTS["acse"]
    ae.dimse_timeout = dimse or TIMEOUTS["dimse"]
    ae.network_timeout = network or TIMEOUTS["network"]
    if verification:
        # Muitos PACS recusam a associação sem Verification.
        ae.add_requested_context(Verification)
    for c in contextos:
        if isinstance(c, (list, tuple)):
            ae.add_requested_context(c[0], c[1])
        else:
            ae.add_requested_context(c)
    return ae


@contextmanager
def associar(aet_local, alvo: Alvo, contextos=(), verification=True, **t):
    """Abre associação; entrega `assoc` (ou None se foi recusada) e sempre libera."""
    ae = nova_ae(aet_local, contextos, verification, **t)
    assoc = ae.associate(alvo.ip, alvo.porta, ae_title=alvo.aet)
    try:
        yield assoc if assoc.is_established else None
    finally:
        if assoc.is_established:
            assoc.release()


def status_hex(st):
    cod = getattr(st, "Status", None)
    return "sem resposta" if cod is None else f"0x{cod:04X}"


def status_ok(st, aceitos=(0x0000,)):
    return getattr(st, "Status", None) in aceitos


def porta_escuta_padrao(aet):
    """Porta determinística (11200-11699) onde a modalidade `aet` espera o
    N-EVENT-REPORT do Storage Commitment. PACS e modalidade chegam ao mesmo valor
    sem configuração; em equipamento real, cadastre a porta no PACS."""
    return 11200 + zlib.crc32(aet.encode()) % 500
