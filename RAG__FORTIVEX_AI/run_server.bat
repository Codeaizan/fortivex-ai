@echo off
cd /d "%~dp0"
set "RAG_PYTHON=%~dp0..\runtime\rag-venv\Scripts\python.exe"
if not exist "%RAG_PYTHON%" (
  echo RAG environment is missing. See RAG setup in the project README.
  exit /b 1
)
if not defined HF_HOME set "HF_HOME=%~dp0..\runtime\huggingface"
set "HF_HUB_OFFLINE=1"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "ANONYMIZED_TELEMETRY=False"
set "OMP_NUM_THREADS=4"
set "PYTHONUTF8=1"
"%RAG_PYTHON%" -m uvicorn rag_server:app --host 127.0.0.1 --port 8000
