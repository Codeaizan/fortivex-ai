import os
import re
import socket
import subprocess
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
LLAMA_RUNTIME = RUNTIME / "llama"
MODEL = LLAMA_RUNTIME / "model" / "LFM3-1.7B-Q4_K_M.gguf"
RAG_PROJECT = ROOT / "RAG__FORTIVEX_AI"
RAG_PYTHON = RUNTIME / "rag-venv" / "Scripts" / "python.exe"


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def find_gpu(server):
    result = subprocess.run([str(server), "--list-devices"], capture_output=True, text=True, timeout=12)
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        if "NVIDIA" in line:
            match = re.match(r"\s*([A-Za-z0-9]+):", line)
            if match:
                return match[1]
    return None


def start_process(args, directory, log, environment=None):
    with log.open("w", encoding="utf-8") as output:
        return subprocess.Popen(args, cwd=directory, env=environment, stdout=output, stderr=subprocess.STDOUT)


def start_model(processes):
    if os.getenv("SHOWROOM_LLM_URL") or port_open(8080):
        return
    server = LLAMA_RUNTIME / "llama-server.exe"
    if not server.is_file() or not MODEL.is_file():
        print("Local LFM3 files are missing. Follow README.md to start the model server.", flush=True)
        return
    args = [
        str(server), "-m", str(MODEL), "--alias", os.getenv("SHOWROOM_LLM_MODEL", "showroom"),
        "--host", "127.0.0.1", "--port", "8080", "--ctx-size", "4096", "--reasoning", "off", "--jinja",
    ]
    try:
        device = find_gpu(server)
    except (OSError, subprocess.TimeoutExpired):
        device = None
    args += ["--device", device, "--n-gpu-layers", "99"] if device else ["--n-gpu-layers", "0"]
    log = LLAMA_RUNTIME / "server.log"
    processes.append(start_process(args, LLAMA_RUNTIME, log))
    print(f"Starting local LFM3 on {device or 'CPU'}. Model log: {log}", flush=True)


def start_rag(processes):
    if os.getenv("SHOWROOM_RAG_URL"):
        return
    if not RAG_PYTHON.is_file():
        print("RAG environment is missing. See the RAG setup in README.md.", flush=True)
        return
    environment = {
        **os.environ,
        "HF_HOME": os.getenv("HF_HOME", str(RUNTIME / "huggingface")),
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "ANONYMIZED_TELEMETRY": "False",
        "OMP_NUM_THREADS": "4",
        "PYTHONUTF8": "1",
    }
    services = [
        (8000, "Tata RAG", "rag-server.log", ["-m", "uvicorn", "rag_server:app", "--host", "127.0.0.1", "--port", "8000"]),
        (8502, "Knowledge admin", "rag-admin.log", [
            "-m", "streamlit", "run", "rag_ui.py", "--server.address=127.0.0.1",
            "--server.port=8502", "--server.headless=true", "--browser.gatherUsageStats=false",
        ]),
    ]
    for port, label, filename, args in services:
        if port_open(port) or (port == 8502 and os.getenv("SHOWROOM_RAG_ADMIN_URL")):
            continue
        log = RUNTIME / filename
        processes.append(start_process([str(RAG_PYTHON), *args], RAG_PROJECT, log, environment))
        print(f"Starting {label} on localhost:{port}. Log: {log}", flush=True)


def main():
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", 8001))
        except OSError as error:
            print(f"Port 8001 is unavailable ({error}). Stop the existing voice desk before restarting.", flush=True)
            return 1
    processes = []
    try:
        start_model(processes)
        start_rag(processes)
        uvicorn.run("showroom.main:app", host="127.0.0.1", port=8001)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
