from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
import shutil
import time
import zipfile
from pathlib import Path

import psutil
import requests
import webview

ROOT = Path(__file__).resolve().parent
UI = ROOT / "ui" / "index.html"
PREFERRED_ROOT = Path("D:/VarezMultimedios")
DATA = PREFERRED_ROOT if Path("D:/").exists() else Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "VarezMultimedios"
MODELS = DATA / "models"
OUTPUTS = DATA / "outputs"
RUNTIME = DATA / "runtime"
OLLAMA_RUNTIME = RUNTIME / "ollama"
MODELS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)
OLLAMA_RUNTIME.mkdir(parents=True, exist_ok=True)

# Force the heavy model caches to D: when that drive exists.
os.environ["HF_HOME"] = str(MODELS / "huggingface")
os.environ["HUGGINGFACE_HUB_CACHE"] = str(MODELS / "huggingface" / "hub")
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["OLLAMA_MODELS"] = str(MODELS / "ollama")

from core import run_job, detect_runtime, choose_ollama_model

CONFIG_PATH = DATA / "config.json"

def persist_model_paths():
    if os.name != "nt":
        return
    pairs = {
        "OLLAMA_MODELS": str(MODELS / "ollama"),
        "HF_HOME": str(MODELS / "huggingface"),
        "HUGGINGFACE_HUB_CACHE": str(MODELS / "huggingface" / "hub"),
    }
    for key, value in pairs.items():
        try:
            subprocess.run(
                ["setx", key, value],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=8,
            )
        except Exception:
            pass

def find_ollama_exe():
    candidates = [
        str(OLLAMA_RUNTIME / "ollama.exe"),
        shutil.which("ollama"),
        str(Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
    ]
    for item in candidates:
        if item and Path(item).exists():
            return item
    return None


class API:
    def __init__(self):
        persist_model_paths()
        self.video_path = None
        self.lock = threading.Lock()
        self.config = self._load_config()
        self.state = {
            "running": False,
            "progress": 0,
            "title": "Listo",
            "detail": "Elegí una nota para empezar.",
            "outputs": [],
            "error": None,
            "job_id": None,
        }

    def _load_config(self):
        cfg = {
            "ollama_model": choose_ollama_model(),
            "whisper_gpu_model": "large-v3-turbo",
            "whisper_cpu_model": "small",
            "models_root": str(MODELS),
            "data_root": str(DATA),
        }
        if CONFIG_PATH.exists():
            try:
                cfg.update(json.loads(CONFIG_PATH.read_text("utf-8")))
            except Exception:
                pass
        return cfg

    def _save_config(self):
        CONFIG_PATH.write_text(json.dumps(self.config, indent=2), encoding="utf-8")

    def system_info(self):
        rt = detect_runtime(self.config)
        return {
            **rt,
            "ram_gb": round(psutil.virtual_memory().total / 1024**3, 1),
            "ollama_model": self.config["ollama_model"],
            "video": self.video_path,
            "data_root": str(DATA),
            "models_root": str(MODELS),
            "runtime_root": str(OLLAMA_RUNTIME),
            "allow_20b": True,
        }

    def pick_video(self):
        win = webview.windows[0]
        result = win.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Video (*.mp4;*.mov;*.m4v;*.mkv;*.avi;*.webm)", "All files (*.*)"),
        )
        if not result:
            return None
        self.video_path = str(result[0])
        return {"path": self.video_path, "name": Path(self.video_path).name}

    def set_model(self, model):
        self.config["ollama_model"] = str(model)
        self._save_config()
        return self.system_info()

    def install_ollama(self):
        persist_model_paths()
        existing = find_ollama_exe()
        if existing:
            return {"ok": True, "message": "Ollama ya está instalado en " + existing}

        def install_worker():
            with self.lock:
                self.state.update(
                    running=True, progress=1, title="Instalando Ollama en D:…",
                    detail="Buscando la versión oficial más reciente.", error=None
                )
            try:
                api = requests.get("https://api.github.com/repos/ollama/ollama/releases/latest", timeout=30)
                api.raise_for_status()
                release = api.json()
                asset = next((a for a in release.get("assets", []) if a.get("name") == "ollama-windows-amd64.zip"), None)
                if not asset:
                    raise RuntimeError("No encontré el ZIP oficial de Ollama para Windows.")
                url = asset["browser_download_url"]
                total = int(asset.get("size") or 0)
                zip_path = RUNTIME / "ollama-windows-amd64.zip"
                downloaded = 0
                with requests.get(url, stream=True, timeout=1800) as r:
                    r.raise_for_status()
                    if not total:
                        total = int(r.headers.get("content-length") or 0)
                    with open(zip_path, "wb") as f:
                        for chunk in r.iter_content(1024 * 1024):
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            pct = int(downloaded * 78 / total) if total else 15
                            with self.lock:
                                self.state["progress"] = max(2, min(78, pct))
                                self.state["detail"] = f"Descargando Ollama: {downloaded/1024**2:.0f} MB / {total/1024**2:.0f} MB" if total else f"Descargados {downloaded/1024**2:.0f} MB"
                with self.lock:
                    self.state.update(progress=82, title="Instalando Ollama en D:…", detail="Descomprimiendo runtime oficial.")
                if OLLAMA_RUNTIME.exists():
                    for p in OLLAMA_RUNTIME.iterdir():
                        if p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            try: p.unlink()
                            except Exception: pass
                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extractall(OLLAMA_RUNTIME)
                try:
                    zip_path.unlink()
                except Exception:
                    pass
                exe = find_ollama_exe()
                if not exe:
                    # Some release zips contain a top-level directory; search recursively.
                    matches = list(OLLAMA_RUNTIME.rglob("ollama.exe"))
                    if matches:
                        target = OLLAMA_RUNTIME / "ollama.exe"
                        if matches[0] != target:
                            shutil.copy2(matches[0], target)
                        exe = str(target)
                if not exe:
                    raise RuntimeError("Ollama se descargó pero no encontré ollama.exe.")
                with self.lock:
                    self.state.update(running=False, progress=100, title="Ollama listo", detail="Instalado en " + str(OLLAMA_RUNTIME))
            except Exception as e:
                with self.lock:
                    self.state.update(running=False, progress=100, title="Falló la instalación de Ollama", detail=str(e), error=str(e))

        threading.Thread(target=install_worker, daemon=True).start()
        return {"ok": True, "message": "Varez está instalando Ollama directamente en D:. Mirá el progreso dentro de la app."}

    def prepare_ai(self):
        persist_model_paths()
        model = self.config["ollama_model"]
        try:
            requests.get("http://127.0.0.1:11434/api/tags", timeout=2).raise_for_status()
        except Exception:
            exe = find_ollama_exe()
            if not exe:
                return {"ok": False, "message": "Ollama todavía se está instalando. Esperá a que termine y volvé a tocar Preparar IA local."}
            try:
                env = os.environ.copy()
                env["OLLAMA_MODELS"] = str(MODELS / "ollama")
                subprocess.Popen(
                    [exe, "serve"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                for _ in range(10):
                    time.sleep(0.5)
                    try:
                        requests.get("http://127.0.0.1:11434/api/tags", timeout=1).raise_for_status()
                        break
                    except Exception:
                        pass
                else:
                    return {"ok": False, "message": "Ollama está instalado pero todavía no pudo iniciar. Cerrá y abrí Varez e intentá otra vez."}
            except Exception as e:
                return {"ok": False, "message": "No pude iniciar Ollama: " + str(e)}

        def pull():
            with self.lock:
                self.state.update(
                    running=True, progress=2, title="Preparando IA local…",
                    detail="Descargando " + model + ". Esto se hace una sola vez.", error=None
                )
            try:
                with requests.post(
                    "http://127.0.0.1:11434/api/pull",
                    json={"name": model, "stream": True},
                    stream=True, timeout=3600,
                ) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                            total, completed = d.get("total"), d.get("completed")
                            pct = int((completed / total) * 100) if total and completed else None
                            with self.lock:
                                if pct is not None:
                                    self.state["progress"] = max(2, min(100, pct))
                                self.state["detail"] = d.get("status", self.state["detail"])
                        except Exception:
                            pass
                with self.lock:
                    self.state.update(running=False, progress=100, title="IA local lista", detail=model + " ya está instalado.")
            except Exception as e:
                with self.lock:
                    self.state.update(running=False, progress=100, title="Error preparando IA", detail=str(e), error=str(e))

        threading.Thread(target=pull, daemon=True).start()
        return {"ok": True}

    def start_job(self, options):
        if not self.video_path or not Path(self.video_path).exists():
            return {"ok": False, "message": "Elegí un video primero."}
        with self.lock:
            if self.state.get("running"):
                return {"ok": False, "message": "Ya hay un trabajo en curso."}
            job_id = uuid.uuid4().hex[:12]
            self.state = {
                "running": True, "progress": 1, "title": "Preparando…",
                "detail": "Abriendo el video.", "outputs": [], "error": None, "job_id": job_id,
            }

        def status(progress, title, detail=""):
            with self.lock:
                self.state["progress"] = int(max(0, min(100, progress)))
                self.state["title"] = title
                self.state["detail"] = detail

        def worker():
            try:
                outputs = run_job(
                    video_path=Path(self.video_path),
                    job_id=job_id,
                    options=dict(options or {}),
                    config=self.config,
                    data_dir=DATA,
                    status=status,
                )
                with self.lock:
                    self.state.update(
                        running=False, progress=100, title="5 clips listos",
                        detail="Revisalos y abrí los que quieras.",
                        outputs=[str(x) for x in outputs],
                    )
            except Exception as e:
                with self.lock:
                    self.state.update(
                        running=False, progress=100, title="Hubo un problema",
                        detail=str(e), error=str(e)
                    )

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "job_id": job_id}

    def get_status(self):
        with self.lock:
            return dict(self.state)

    def open_output(self, index):
        outs = self.state.get("outputs") or []
        i = int(index)
        if i < 0 or i >= len(outs):
            return False
        os.startfile(outs[i])
        return True

    def open_output_folder(self):
        outs = self.state.get("outputs") or []
        folder = Path(outs[0]).parent if outs else OUTPUTS
        os.startfile(str(folder))
        return True


def main():
    api = API()
    webview.create_window(
        "Varez Servicios para Multimedios",
        str(UI),
        js_api=api,
        width=1180, height=820,
        min_size=(900, 650),
        background_color="#070b11",
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
