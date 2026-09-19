from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
import shutil
import time
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
MODELS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)

# Force the heavy model caches to D: when that drive exists.
os.environ["HF_HOME"] = str(MODELS / "huggingface")
os.environ["HUGGINGFACE_HUB_CACHE"] = str(MODELS / "huggingface" / "hub")
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
            "allow_20b": psutil.virtual_memory().total / 1024**3 >= 24,
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
        try:
            subprocess.Popen(
                [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    "winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements",
                ],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            return {"ok": True, "message": "Se abrió la instalación de Ollama. Cuando termine, volvé y tocá Preparar IA local."}
        except Exception as e:
            return {"ok": False, "message": str(e)}

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
