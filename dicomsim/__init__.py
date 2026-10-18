"""dicomsim — núcleo reutilizável do simulador de modalidades DICOM.

Camadas:
  events   eventos estruturados (substitui procurar "FALHOU" no texto do log)
  netutil  associação e AE em um só lugar
  library  biblioteca de imagens (reais) e gerador sintético por modalidade
  steps    um passo DICOM por função: MWL, MPPS, C-STORE, Storage Commitment, Print
  exam     o exame completo de uma modalidade (usa os passos)
  profiles perfis de equipamento / fabricante (perfis.json)
  servers  PACS+RIS+MPPS+Commitment virtual para testar sem equipamento real
  fleet    várias modalidades ao mesmo tempo
"""
__version__ = "0.1.0"
