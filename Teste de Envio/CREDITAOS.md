# Imagens de teste — origem e licença

Todas as imagens em `imagens/` são **reais**, anonimizadas e de uso livre.
Nada aqui é gerado artificialmente (as sintéticas ficam em `sinteticas/`
e não entram no jogo de envio).

## Fonte 1 — Open Microscopy Environment (OME)

- Endereço: <https://downloads.openmicroscopy.org/images/DICOM/samples/>
- Autoria: Sébastien Barré
- Licença declarada no `readme.txt` do próprio diretório:

> These files are free of known copyright restrictions and are in the public
> domain. See the Creative Commons Public Domain Mark page for usage details,
> <http://creativecommons.org/publicdomain/mark/1.0/>.

- Arquivos originais: <https://barre.dev/medical/samples/>

| Arquivo | Origem | Conteúdo real |
|---|---|---|
| `CR-MONO1-10-chest.dcm` | OME | Tórax — CR digital |
| `CT-MONO2-8-abdo.dcm` | OME | Abdome |
| `CT-MONO2-12-lomb-an2.dcm` | OME | Coluna lombar (ACR-NEMA legado — ver `casos_especiais/`) |
| `CT-MONO2-16-ankle.dcm` | OME | Tornozelo |
| `CT-MONO2-16-brain.dcm` | OME | Crânio |
| `CT-MONO2-16-chest.dcm` | OME | Tórax (JPEG Lossless) |
| `CT-MONO2-16-ort.dcm` | OME | Tórax / coluna |
| `MR-MONO2-12-an2.dcm` | OME | Tornozelo |
| `MR-MONO2-12-angio-an1.dcm` | OME | Angiografia (ACR-NEMA legado) |
| `MR-MONO2-12-shoulder.dcm` | OME | Ombro (JPEG Lossless) |
| `MR-MONO2-16-head.dcm` | OME | Crânio |
| `MR-MONO2-16-knee.dcm` | OME | Joelho |
| `MR-MONO2-8-16x-heart.dcm` | OME | Coração, 16 quadros |
| `NM-MONO2-16-13x-heart.dcm` | OME | Medicina nuclear, 13 quadros |
| `US-MONO2-8-8x-execho.dcm` | OME | Ecocardiograma, 8 quadros |
| `OT-MONO2-8-a7.dcm` | OME | Documento secundário |
| `OT-MONO2-8-colon.dcm` | OME | Colonoscopia |
| `OT-MONO2-8-hip.dcm` | OME | Quadril |

**Ressalva honesta:** 5 desses arquivos vieram **sem File Meta Information**
(DICOM anterior ao Part 10). Para que dê para enviá-los pela rede eles foram
reescritos como Part 10 válido em VR implícito; os originais estão preservados
em `casos_especiais/ANOM_SEM_META_*`.

## Fonte 2 — amostras do pacote pydicom

- Endereço: <https://github.com/pydicom/pydicom> (diretório `src/pydicom/data`)
- Licença do pacote: **MIT**

Imagens reais anonimizadas usadas: `CT_small`, `liver_1frame`,
`MR_small`, `MR_small_implicit`, `MR_small_bigendian`, `MR_small_RLE`,
`examples_rgb_color`, `examples_palette`, `examples_ybr_color`,
`SC_rgb_rle_32bit_2frame`, `rtdose`, `test-SR`, `waveform_ecg`.

## Casos de borda / anômalos (`casos_especiais/`, fora do jogo de envio)

Copiados do pydicom (MIT) para testar como o PACS reage a objetos problemas:

| Arquivo | Anomalia |
|---|---|
| `ANOM_SEM_META_*` | Sem File Meta Information |
| `ANOM_ACRNEMA_*` | Formato **ACR-NEMA 1.0 / 2.0** (1996/1997), sem SOP Class UID |
| `ANOM_MR_truncated.dcm` | Pixel data truncada |
| `ANOM_no_meta.dcm` | Objeto sem meta |
| `ANOM_badVR.dcm` | VR inválido |
| `ANOM_examples_jpeg2k.dcm` | Pixel data encapsulada em JPEG2000 |
| `ANOM_J2K_pixelrep_mismatch.dcm` | JPEG2000 com Pixel Representation divergente |
| `ANOM_SC_rgb_jpeg_dcmd.dcm` | Captura secundária comprimida |
| `ANOM_JPEG-lossy.dcm` | JPEG com perdas |
| `ANOM_examples_overlay.dcm` | Objeto com overlay |
| `ANOM_MR_small_padded.dcm` | RM com padding |

Estes **não** entram no `manifesto.json` de propósito: servem para
teste negativo (o PACS deve recusar ou aceitar com aviso).

## Por que isso importa para o teste de envio

Imagens reais trazem coisas que arquivos sintéticos nunca trazem:
transferências comprimidas (JPEG Lossless, JPEG Baseline, RLE), big endian,
multiframe, YBR em ultrassonografia, objetos sem pixel data (SR, ECG) e
proveniência real de Equipment/Manufacturer. É exatamente aí que os PACS
rejeitam ou corrompem sem avisar.

## Manutenção

```bat
python "Teste de Envio\14_imagens_reais.py"      :: baixa/fica com as reais (idempotente)
python "Teste de Envio\montar_manifesto.py"      :: reconstrói manifesto.json
```

O manifesto é sempre reconstruído **varrendo a pasta**, então basta jogar um
`.dcm` novo em `imagens/` e rodar o `montar_manifesto.py` para ele entrar no
jogo de envio.
## Fonte 3 — The Cancer Imaging Archive (TCIA)

Imagens **reais e anonimizadas** de pacientes, publicadas pelo TCIA (<https://www.cancerimagingarchive.net>),
baixadas por `baixar_imagens.py` (1 imagem por série) para `imagens_tcia/<MODALIDADE>/`.
Essa pasta **não é versionada**: a lista exata (coleção, UIDs, licença, DOI) está em `fontes_tcia.json`,
e `python baixar_imagens.py` baixa tudo de novo. Apenas coleções com licença **CC BY** ou **CC0**
entram; coleções sintéticas (VICTRE, MIDI-B) são excluídas de propósito.

**Atribuição (CC BY):** ao divulgar resultados feitos com estas imagens, cite cada coleção pelo DOI abaixo
e o artigo de dados do TCIA: Clark K. et al., *The Cancer Imaging Archive (TCIA): Maintaining and Operating a Public Information Repository*, J Digit Imaging 26(6):1045-1057, 2013.

| Coleção | Modalidades usadas | Licença | DOI |
|---|---|---|---|
| ACRIN-Contralateral-Breast-MR | CR×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/Q1EE-J082 |
| ACRIN-FLT-Breast | OT×2, PT×2 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) |  |
| ACRIN-NSCLC-FDG-PET | CR×1, NM×1, OT×3 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/tcia.2019.30ilqfcl |
| Anti-PD-1_Lung | OT×3, PT×1 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) |  https://doi.org/10.7937/tcia.2019.zjjwb9ip |
| BREAST-DIAGNOSIS | MG×2 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2015.SDNRQXXR |
| CC-Radiomics-Phantom | CT×1 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2017.zuzrml5b |
| CMB-AML | XA×5 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/PCTE-6M66 |
| CMB-BRCA | MG×1, MR×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/dx22-8j71 |
| CMB-CRC | DX×2, MR×2, NM×1, US×3, XA×2 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/DJG7-GZ87 |
| CMB-GEC | CT×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/e7kh-r486 |
| CMB-LCA | NM×2, US×4 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/3CX3-S132 |
| CMB-MEL | CT×1, US×2 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/GWSP-WH72 |
| CMB-MML | CR×1, XA×4 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/szkb-sw39 |
| CMB-PCA | DX×1, NM×2, RF×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/25T7-6Y12 |
| CMMD | MG×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/tcia.eqde-4b16 |
| COVID-19-AR | CR×1, CT×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/tcia.2020.py71-5978 |
| COVID-19-NY-SBU | CR×1, DX×1, NM×1, OT×2 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/TCIA.BBAG-2923 |
| CPTAC-CCRCC | CT×1, MR×2 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/K9/TCIA.2018.OBLAMN27 |
| CPTAC-LSCC | PT×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/K9/TCIA.2018.6EMUB5L2 |
| CPTAC-LUAD | CT×1, PT×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/K9/TCIA.2018.PAT12TBS |
| CPTAC-PDA | CT×1, US×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/K9/TCIA.2018.SC20FO18 |
| CPTAC-UCEC | CT×1, PT×1, US×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/K9/TCIA.2018.3R3JUISW |
| EA1141 | MG×6 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/2BAS-HR33 |
| EAY131 | CT×1, NM×1, PT×2, XA×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/c5ke-yx42 |
| ICDC-Glioma | MR×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/TCIA.SVQT-Q016 |
| ISPY2 | MR×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/TCIA.D8Z0-9T85 |
| LIDC-IDRI | CR×4, DX×4 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2015.LO9QL9SX |
| Mediastinal-Lymph-Node-SEG | CT×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/QVAZ-JA09 |
| Pseudo-PHI-DICOM-Data | CR×1, DX×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/s17z-r072 |
| QIN-PROSTATE-Repeatability | MR×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/K9/TCIA.2018.MR1CKGND |
| RIDER PHANTOM MRI | MR×1 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2015.MI4QDDHU |
| RIDER Pilot | CR×2, DX×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/m87f-mz83 |
| TCGA-BLCA | CT×1 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2016.8LNG8XDR |
| TCGA-BRCA | MG×2 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2016.AB2NAZRP |
| TCGA-CESC | MR×1 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2016.SQ4M8YP4 |
| TCGA-COAD | OT×1 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2016.HJJHBOXZ |
| TCGA-KIRC | CT×1 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2016.V6PBVTDR |
| TCGA-KIRP | PT×1 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2016.ACWOGBEF |
| TCGA-LUAD | NM×2 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2016.JGNIHEP5 |
| TCGA-LUSC | NM×1, PT×3 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2016.TYGKKFMQ |
| TCGA-OV | OT×1 | [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/) | https://doi.org/10.7937/K9/TCIA.2016.NDO1MDFQ |
| UPENN-GBM | MR×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/TCIA.709X-DN49 |
| VAREPOP-APOLLO | DX×2, NM×1, RF×11, US×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/GHKN-MD15 |
| Vestibular-Schwannoma-MC-RC | MR×1 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | https://doi.org/10.7937/HRZH-2N82 |
