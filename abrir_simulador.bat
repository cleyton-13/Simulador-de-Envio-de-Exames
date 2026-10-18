@echo off
REM Tela de testes DICOM — duplo clique para abrir (funciona em qualquer PC com Python)
cd /d "%~dp0"

REM 1) Python instalado?
python --version >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Python nao encontrado neste computador.
  echo Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH",
  echo depois rode este arquivo de novo.
  pause
  exit /b 1
)

REM 2) Dependencias instaladas? (na primeira vez instala sozinho)
python -c "import streamlit, pynetdicom, pydicom, numpy" >nul 2>&1
if errorlevel 1 (
  echo Primeira vez neste PC: instalando dependencias, aguarde...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias. Confira a internet e rode de novo.
    pause
    exit /b 1
  )
)

echo Subindo a tela em http://localhost:8503 ...
python -m streamlit run app_simulador.py --server.port 8503
pause
