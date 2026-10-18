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