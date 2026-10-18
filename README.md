# Simulador-de-Envio-de-Exames
Aplicação desenvolvida para testes em campo. Capaz de simular envio de exames no formato DICOM.

# NOVO (v2): núcleo `dicomsim/` + tela `app_simulador.py`

Fluxo de modalidade completo e testável, em paralelo ao material antigo (que segue funcionando):

```bat
python -m pytest -q tests                  :: 7 testes ponta a ponta com servidor virtual
python -m dicomsim servidor --port 11112   :: PACS+RIS+MPPS+Commitment+Print virtual
python -m dicomsim exame --equipamento "CT Sala 1"
python -m dicomsim frota --exames 3        :: vários equipamentos em paralelo
abrir_simulador.bat                        :: tela com visões Cliente / Suporte / Técnico
```
Configuração única em `perfis.json` (destinos, fabricantes, equipamentos).
Plano B (recomeço limpo, mesmo núcleo): pasta `../novo`.
Os scripts `01`–`14` e `app_tela_testes.py` abaixo são o material antigo.

---

# Teste DICOM — Simulador de Modalidade / PACS / RIS / Impressora

Pasta dedicada a testes de comunicação DICOM (C-ECHO, C-STORE, C-FIND, C-MOVE, MWL, Print).
Todos os arquivos deste projeto ficam aqui dentro.

## 1. O que foi achado no GitHub (pronto)

Não precisa reinventar a roda para protocolo. Os principais prontos são:

| Projeto | Link | Linguagem | O que tem | Quando usar |
|---|---|---|---|---|
| **pynetdicom** | https://github.com/pydicom/pynetdicom | Python | `echoscu/echoscp, storescu/storescp, findscu, movescu, getscu, qrscp` + lib `AE.associate()`, `send_c_echo/store/find/move/get` | **Base deste simulador.** Ideal para customizar. 573★ |
| **dcm4che** | https://github.com/dcm4che/dcm4che | Java | `storescu/storescp, findscu, movescu, getscu, mppsscu/scp, stgcmtscu` + **`modality` (simula modalidade IHE: MWL + MPPS + Storage)** | Teste enterprise / simular modalidade completa |
| **DCMTK** | https://github.com/DCMTK/dcmtk | C++ | `echoscu, storescu/storescp, findscu, movescu, wlmscp` (referência OFFIS) | Padrão-ouro, quando precisa binário nativo |
| **Orthanc** | https://www.orthanc-server.com (fonte aberta) | C++ | PACS leve completo (C-STORE SCP, REST, viewer) | Subir um PACS real em 1 min com Docker para testar contra |
| **fo-dicom** | https://github.com/fo-dicom/fo-dicom | C# .NET | Stack DICOM .NET | Se seu sistema for .NET |

> Este simulador usa **pynetdicom + pydicom** (mesma base do primeiro item), então qualquer mudança futura é só editar os `.py` aqui.

Exemplo com ferramenta pronta (DCMTK):
```bat
echoscu 127.0.0.1 11112 -aec PACS_TESTE
storescu 127.0.0.1 11112 teste_CT.dcm -aec PACS_TESTE -aet SIMULADOR
```

Exemplo dcm4che `modality` (simula MWL->MPPS->STORE de verdade):
```bat
modality -c PACS_TESTE@127.0.0.1:11112 --mwl --mpps --store teste_CT.dcm
```

## 2. Protocolo DICOM — resumo para manutenção futura

Entenda isso antes de alterar o código:

**Modelo:** `SCU (cliente, quem pede)` x `SCP (servidor, quem atende)`.
Modalidade = SCU de Storage. PACS = SCP de Storage. Para query é o inverso: PACS é SCP de Find.

**Fluxo de toda conversa:**
1. **Association (ACSE)** — handshake TCP + `A-ASSOCIATE-RQ` com: `Calling AE Title`, `Called AE Title`, lista de Presentation Contexts.
   Se AET errado, PACS rejeita aqui (causa nº1 de falha em campo).
2. **Negociação de Presentation Context** — cada contexto = `Abstract Syntax (SOP Class UID)` + `Transfer Syntax (como os bytes vão)`.
   Ex: `CT Image Storage 1.2.840.10008.5.1.4.1.1.2` + `Explicit VR Little Endian 1.2.840.10008.1.2.1`.
3. **DIMSE** — comandos propriamente ditos (C-ECHO, C-STORE...), cada um com `Message ID` e `Status`.
4. **Release/Abort** — `A-RELEASE` no fim.

**Principais SOP Classes (Abstract Syntax):**

| Serviço | SOP Class | UID |
|---|---|---|
| C-ECHO | Verification | 1.2.840.10008.1.1 |
| C-STORE | CT Image Storage | 1.2.840.10008.5.1.4.1.1.2 |
| C-STORE | MR Image Storage | 1.2.840.10008.5.1.4.1.1.4 |
| C-STORE | Digital X-Ray (CR/DX) | 1.2.840.10008.5.1.4.1.1.1 / .1.1.1.1 |
| C-FIND | Study Root QR Find | 1.2.840.10008.5.1.4.1.2.2.1 |
| C-MOVE | Study Root QR Move | 1.2.840.10008.5.1.4.1.2.2.2 |
| C-GET | Study Root QR Get | 1.2.840.10008.5.1.4.1.2.2.3 |
| MWL | Modality Worklist Find | 1.2.840.10008.5.1.4.31 |
| MPPS | Modality Performed Procedure Step | 1.2.840.10008.3.1.2.3.3 |
| Storage Commitment | Storage Commitment Push | 1.2.840.10008.1.20.1 |

**Transfer Syntaxes comuns:** Implicit VR LE `1.2.840.10008.1.2`, Explicit VR LE `1.2.840.10008.1.2.1`, Explicit VR BE `1.2.840.10008.1.2.2`, JPEG Lossless, JPEG-LS, JPEG2000, RLE.

**Status DIMSE que você vai ver nos logs:**
`0x0000` Success | `0xFF00/0xFF01` Pending (tem mais, só em FIND) | `0xAxxx` Failure no Store | `0xBxxx` Warning (ex: Coercion) | `0xFE00` Cancel.

**Onde mexer no código:**
- `01_scp_pacs.py: handle_store` — o que fazer ao receber imagem (hoje: salva em `./received`).
- `01_scp_pacs.py: handle_find` — como responder query (hoje: varre `./received`).
- `02_scu_teste.py: build_ae` — quais SOP Classes pedir na associação.
- `config.json` — AETs, IP, portas. **AET é case-sensitive e com limite de 16 chars.**
- Para MWL/MPPS: adicionar `ModalityWorklistInformationModelFind (1.2.840.10008.5.1.4.31)` como requested+supported context + handler `EVT_C_FIND` separado por Abstract Syntax.

## 3. Como usar este simulador

```bat
cd "C:\Users\cleyton.santos\Documents\16 - Relatorio de chamados grupo\teste dicom"
pip install -r requirements.txt

:: 1) gerar imagem fake
python 03_gerar_imagem.py

:: 2) subir PACS fake (terminal 1)
python 01_scp_pacs.py

:: 3) testar PACS (terminal 2)
python 02_scu_teste.py --teste echo
python 02_scu_teste.py --teste store --arquivo teste_CT.dcm
python 02_scu_teste.py --teste find

:: 4) MWL — subir RIS fake (terminal 1) e testar (terminal 2)
python 05_mwl_scp.py
python 02_scu_teste.py --teste mwl
python 02_scu_teste.py --teste mwl --modality CT --patient-name "SILVA*"

:: 5) Print — subir impressora fake (terminal 1) e testar (terminal 2)
python 06_print_scp.py
python 02_scu_teste.py --teste print

:: 6) validacao automatica (sem 2 terminais)
python 04_teste_automatico.py
python 08_teste_mwl_print.py

:: 7) tela web (recomendado)
streamlit run app_tela_testes.py
```

Contra equipamento real (troque IP/AET):
```bat
python 02_scu_teste.py --teste echo --ip 192.168.1.50 --port 104 --aet PACS_REAL
python 02_scu_teste.py --teste store --ip 192.168.1.50 --port 104 --aet PACS_REAL --arquivo teste_CT.dcm
python 02_scu_teste.py --teste mwl --ip 192.168.1.60 --mwl-port 104 --mwl-aet RIS_REAL --modality CT
python 02_scu_teste.py --teste print --ip 192.168.1.70 --print-port 104 --print-aet PRINTER_REAL
```

## 4. MWL e Print — como funciona

**MWL (Modality Worklist, SOP 1.2.840.10008.5.1.4.31):**
Fluxo real: modalidade -> C-FIND p/ RIS com filtros (Modality, StationAET, StartDate)
-> RIS retorna lista (PatientName/ID, AccessionNumber, RequestedProcedure).
Aqui: `05_mwl_scp.py` le `worklist.json` (edite p/ seus pacientes) e filtra
por Modality/PatientName/AccessionNumber/Date. `--teste mwl` no cliente monta o C-FIND.

**Print (Basic Grayscale Print Management Meta 1.2.840.10008.5.1.1.9):**
Fluxo real: N-CREATE FilmSession -> N-CREATE FilmBox -> N-SET ImageBox (pixels)
-> N-ACTION FilmBox (action=1 imprime) -> N-GET Printer (status) -> N-DELETE.
Detalhe pynetdicom: o UID criado pelo SCP nao volta no retorno (so no command),
por isso nosso SCU **gera os UIDs e manda no request** — impressora real aceita.
Teste valida associacao + contextos + DIMSE-N ponta a ponta; log em `printed/print_jobs.log`.

Checklist de falha em campo: 1) ping porta (104/11112) 2) AET origem/destino 3) Presentation Context (SOP+TS) aceito 4) firewall 5) `received/` com permissão.

## Arquivos
- `config.json` — AETs/IPs/portas (pacs 11112, mwl 11114, printer 11115)
- `01_scp_pacs.py` — PACS simulado (C-ECHO/C-STORE/C-FIND SCP)
- `02_scu_teste.py` — modalidade simulada (echo/store/find/move/mwl/print SCU)
- `03_gerar_imagem.py` — gera `teste_CT.dcm`
- `04_teste_automatico.py` — valida echo/store/find em 1 processo
- `05_mwl_scp.py` + `worklist.json` — RIS simulado (MWL C-FIND)
- `06_print_scp.py` + `printed/` — impressora simulada (N-CREATE/SET/ACTION/GET/DELETE)
- `08_teste_mwl_print.py` — valida MWL + Print em 1 processo
- `10_envio_validacao.py` + `Teste de Envio/` (12 imagens + `manifesto.json`) —
  ENVIO do jogo de imagens: C-STORE -> C-FIND -> C-MOVE + SHA-256 do array de pixels
  (`received_envio/` = o que o PACS guardou, `recuperado/` = o que voltou pelo C-MOVE)
- `app_tela_testes.py` + `.streamlit/config.toml` + `modalidades.json` + `relatorios/` —
  tela web em 6 paginas: Visao geral / Modalidades / Destinos / Testes / Imagens / Diagnostico
- `received/` — imagens recebidas via C-STORE (PACS simulado do `01_scp_pacs.py`)
