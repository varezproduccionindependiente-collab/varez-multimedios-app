from __future__ import annotations

import json
import ctypes
import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path

import av
import imageio_ffmpeg
import psutil
import requests
from faster_whisper import WhisperModel, download_model

OLLAMA = "http://127.0.0.1:11434"


def _cuda_dlls_available():
    # nvidia-smi only proves the driver exists. CTranslate2 also needs the
    # CUDA runtime DLLs. Checking them here avoids wasting time on a GPU load
    # that is guaranteed to fail.
    if not hasattr(ctypes, "WinDLL"):
        return False
    required = ("cublas64_12.dll", "cudnn64_9.dll")
    handles = []
    try:
        for dll in required:
            handles.append(ctypes.WinDLL(dll))
        return True
    except Exception:
        return False


def detect_runtime(config):
    cuda = False
    gpu_name = None
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=3)
        if p.returncode == 0 and p.stdout.strip():
            gpu_name = p.stdout.strip().splitlines()[0]
            cuda = _cuda_dlls_available()
    except Exception:
        pass
    return {
        "cuda": cuda,
        "gpu": gpu_name,
        "whisper_model": config["whisper_gpu_model"] if cuda else config["whisper_cpu_model"],
    }


def choose_ollama_model():
    ram = psutil.virtual_memory().total / 1024**3
    return "gpt-oss:20b" if ram >= 24 else "qwen3:8b"


def duration_seconds(path: Path):
    with av.open(str(path)) as c:
        if c.duration:
            return float(c.duration / av.time_base)
    return 0.0


def _whisper_direct_dir(model_name: str, whisper_root: Path):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", model_name)
    return whisper_root / "ready" / safe


def _whisper_model_complete(model_dir: Path):
    model_bin = model_dir / "model.bin"
    config_file = model_dir / "config.json"
    tokenizer = model_dir / "tokenizer.json"
    try:
        return (
            model_bin.is_file()
            and model_bin.stat().st_size > 50 * 1024 * 1024
            and config_file.is_file()
            and tokenizer.is_file()
        )
    except Exception:
        return False


def _remove_legacy_whisper_cache(model_name: str, whisper_root: Path):
    # Older Varez versions let Hugging Face create snapshot/symlink caches.
    # They are the source of the missing model.bin issue on this PC.
    for p in whisper_root.glob("models--*"):
        try:
            if model_name.lower() in p.name.lower():
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass


def ensure_whisper_model(model_name: str, whisper_root: Path, status=None):
    whisper_root.mkdir(parents=True, exist_ok=True)
    target = _whisper_direct_dir(model_name, whisper_root)
    cache_dir = whisper_root / "_download_cache"

    if _whisper_model_complete(target):
        if status:
            status(100, "Whisper listo", model_name + " verificado en D:.")
        return target

    last_error = None
    for attempt in range(1, 4):
        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if attempt > 1 and cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)

            if status:
                status(
                    10,
                    "Descargando Whisper…",
                    f"{model_name} · descarga limpia {attempt}/3 directamente a D:.",
                )

            # Important: output_dir makes the actual CT2 files live directly in
            # our own folder. Varez no longer loads from HF snapshot paths.
            downloaded = Path(download_model(
                model_name,
                output_dir=str(target),
                cache_dir=str(cache_dir),
                local_files_only=False,
            ))

            if downloaded != target and downloaded.exists() and not _whisper_model_complete(target):
                for src in downloaded.iterdir():
                    dst = target / src.name
                    if src.is_file():
                        shutil.copy2(src, dst)

            if not _whisper_model_complete(target):
                raise RuntimeError(
                    "La descarga terminó pero faltan archivos del modelo "
                    "(model.bin/config.json/tokenizer.json)."
                )

            _remove_legacy_whisper_cache(model_name, whisper_root)

            if status:
                status(92, "Verificando Whisper…", "Archivos completos. Probando que el modelo abra correctamente.")
            return target

        except Exception as e:
            last_error = e
            shutil.rmtree(target, ignore_errors=True)
            if status and attempt < 3:
                status(
                    15,
                    "Reintentando Whisper…",
                    f"Intento {attempt}/3 falló. Limpio la descarga y vuelvo a intentar.",
                )
            time.sleep(1.5)

    raise RuntimeError("No pude preparar Whisper después de 3 intentos: " + str(last_error))


def prepare_whisper_model(config, status=None):
    rt = detect_runtime(config)
    model_name = rt["whisper_model"]
    device = "cuda" if rt["cuda"] else "cpu"
    compute = "float16" if device == "cuda" else "int8"
    model_root = Path(config.get("models_root") or (Path.home() / ".cache" / "varez-models"))
    whisper_root = model_root / "whisper"

    model_dir = ensure_whisper_model(model_name, whisper_root, status)

    try:
        probe = WhisperModel(str(model_dir), device=device, compute_type=compute)
        del probe
    except Exception:
        # If CUDA was detected but loading still fails, prepare and verify CPU.
        if device == "cuda":
            model_name = config["whisper_cpu_model"]
            device = "cpu"
            compute = "int8"
            model_dir = ensure_whisper_model(model_name, whisper_root, status)
            probe = WhisperModel(str(model_dir), device=device, compute_type=compute)
            del probe
        else:
            raise

    if status:
        status(100, "Whisper listo", model_name + " · " + device.upper() + " · verificado.")
    return {
        "model_name": model_name,
        "model_dir": str(model_dir),
        "device": device,
        "compute": compute,
    }


def _run_whisper(path: Path, model_name: str, device: str, compute: str, whisper_root: Path, status):
    status(7, "Cargando Whisper…", model_name + " · " + device.upper())
    model_dir = ensure_whisper_model(
        model_name,
        whisper_root,
        lambda p, t, d: status(6 + int(p * 0.04), t, d),
    )
    model = WhisperModel(str(model_dir), device=device, compute_type=compute)
    status(
        12,
        "Transcribiendo la nota completa…",
        "Whisper local con timestamps palabra por palabra.",
    )
    segs, info = model.transcribe(
        str(path),
        language="es",
        beam_size=5 if device == "cuda" else 3,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=350),
        condition_on_previous_text=True,
    )
    segments, words = [], []
    # faster-whisper ejecuta parte del trabajo al iterar el generador,
    # por eso este bloque también debe quedar dentro del try/fallback.
    for s in segs:
        txt = (s.text or "").strip()
        if txt:
            segments.append({"start": float(s.start), "end": float(s.end), "text": txt})
        for w in (s.words or []):
            token = (w.word or "").strip()
            if token:
                words.append({"word": token, "start": float(w.start), "end": float(w.end)})
    del model
    return {"segments": segments, "words": words}


def transcribe(path: Path, config, status):
    rt = detect_runtime(config)
    model_root = Path(config.get("models_root") or (Path.home() / ".cache" / "varez-models"))
    whisper_root = model_root / "whisper"
    whisper_root.mkdir(parents=True, exist_ok=True)

    if rt["cuda"]:
        try:
            return _run_whisper(
                path,
                config["whisper_gpu_model"],
                "cuda",
                "float16",
                whisper_root,
                status,
            )
        except Exception as gpu_error:
            # Una NVIDIA visible por nvidia-smi no garantiza que estén disponibles
            # cuBLAS/cuDNN para CTranslate2. En ese caso Varez sigue en CPU.
            try:
                import gc
                gc.collect()
            except Exception:
                pass
            status(
                9,
                "GPU sin CUDA compatible · sigo por CPU",
                "No hace falta instalar nada. Varez cambia automáticamente a Whisper "
                + config["whisper_cpu_model"]
                + ".",
            )

    return _run_whisper(
        path,
        config["whisper_cpu_model"],
        "cpu",
        "int8",
        whisper_root,
        status,
    )


def _fmt(t):
    m = int(t // 60)
    s = t - m * 60
    return f"{m:02d}:{s:05.2f}"


def _transcript_text(segments):
    return "\n".join(f"[{_fmt(s['start'])}-{_fmt(s['end'])}] {s['text']}" for s in segments)


def _clip_schema():
    return {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start": {"type": "number"},
                        "end": {"type": "number"},
                        "question_start": {"type": "number"},
                        "question_end": {"type": "number"},
                        "hook_end": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "title", "start", "end",
                        "question_start", "question_end", "hook_end", "reason",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["clips"],
        "additionalProperties": False,
    }


def _parse_clip_response(payload):
    message = payload.get("message") or {}
    content = (message.get("content") or "").strip()

    # Some Ollama/model combinations may include a fenced object even when
    # structured output was requested. Strip the fence defensively.
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.I)
        content = re.sub(r"\s*```$", "", content)

    if not content:
        raise ValueError("respuesta final vacía")

    try:
        parsed = json.loads(content)
    except Exception:
        a, b = content.find("{"), content.rfind("}")
        if a < 0 or b <= a:
            raise ValueError("respuesta sin JSON")
        parsed = json.loads(content[a:b + 1])

    raw = parsed.get("clips") if isinstance(parsed, dict) else None
    if not isinstance(raw, list) or len(raw) != 5:
        raise ValueError("la respuesta no contiene exactamente 5 clips")
    return raw


def _fallback_clip_windows(transcript, total, min_dur, max_dur):
    # Last-resort local fallback: never leave the user with a dead job merely
    # because the editorial model returned malformed output. It builds five
    # self-contained speech windows, spread across the note.
    segs = [s for s in transcript.get("segments", []) if (s.get("text") or "").strip()]
    if not segs:
        raise RuntimeError("No hay suficiente transcripción para crear clips.")

    candidates = []
    for i, s in enumerate(segs):
        st = float(s["start"])
        en = float(s["end"])
        text_parts = [(s.get("text") or "").strip()]
        j = i + 1
        while j < len(segs) and en - st < min_dur:
            gap = float(segs[j]["start"]) - en
            if gap > 2.2:
                break
            en = float(segs[j]["end"])
            text_parts.append((segs[j].get("text") or "").strip())
            j += 1
        while j < len(segs) and en - st < min(max_dur, min_dur + 10):
            gap = float(segs[j]["start"]) - en
            if gap > 1.2:
                break
            trial_end = float(segs[j]["end"])
            if trial_end - st > max_dur:
                break
            en = trial_end
            text_parts.append((segs[j].get("text") or "").strip())
            j += 1

        dur = en - st
        if dur < max(3.0, min_dur * 0.65):
            continue
        text = " ".join(x for x in text_parts if x)
        words = text.split()
        if len(words) < 10:
            continue

        # Prefer dense, complete-sounding speech with punctuation and useful
        # concrete information; penalize greetings/filler.
        lower = text.lower()
        score = min(len(words), 90) / 12.0
        score += 1.2 if re.search(r"[.!?…]['\"]?$", text.strip()) else 0
        score += 0.8 if re.search(r"\b\d+[\d.,%]*\b", text) else 0
        score += 0.5 * sum(
            1 for cue in (
                "porque", "entonces", "pero", "hoy", "ahora", "importante",
                "problema", "solución", "resultado", "significa", "necesitamos",
                "queremos", "pasó", "ocurrió", "decidimos", "vamos",
            )
            if cue in lower
        )
        score -= 2.0 * sum(
            1 for cue in ("buen día", "buenas tardes", "gracias por venir", "cómo estás")
            if cue in lower
        )
        candidates.append({
            "start": st,
            "end": min(total, en + 1.4),
            "text": text,
            "score": score,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    chosen = []
    for cand in candidates:
        overlap = False
        for prev in chosen:
            inter = max(0.0, min(cand["end"], prev["end"]) - max(cand["start"], prev["start"]))
            shorter = min(cand["end"] - cand["start"], prev["end"] - prev["start"])
            if shorter > 0 and inter / shorter > 0.55:
                overlap = True
                break
        if not overlap:
            chosen.append(cand)
        if len(chosen) == 5:
            break

    # Extremely short material may require overlap; fill remaining slots.
    if len(chosen) < 5:
        for cand in candidates:
            if cand not in chosen:
                chosen.append(cand)
            if len(chosen) == 5:
                break

    if len(chosen) < 5:
        step = max(1.0, total / 5.0)
        while len(chosen) < 5:
            idx = len(chosen)
            st = max(0.0, min(total - 1.0, idx * step))
            en = min(total, st + max(5.0, min(max_dur, step * 1.4)))
            chosen.append({"start": st, "end": en, "text": "", "score": 0})

    chosen.sort(key=lambda x: x["start"])
    return [
        {
            "title": f"Clip {i + 1}",
            "start": x["start"],
            "end": x["end"],
            "question_start": -1,
            "question_end": -1,
            "reason": "Selector local de respaldo",
        }
        for i, x in enumerate(chosen[:5])
    ]


def select_clips(transcript, total, options, config, status):
    model = config["ollama_model"]
    try:
        tags = requests.get(OLLAMA + "/api/tags", timeout=3)
        tags.raise_for_status()
    except Exception:
        raise RuntimeError("Ollama no está ejecutándose. Abrilo o tocá 'Preparar todo'.")

    names = [x.get("name", "") for x in tags.json().get("models", [])]
    if not any(x == model or x.startswith(model + ":") for x in names):
        raise RuntimeError("Falta el modelo local " + model + ". Tocá 'Preparar todo' una sola vez.")

    if total < 45:
        min_dur, max_dur = 5, max(8, min(20, int(total * 0.7)))
        overlap = "Se permite bastante superposición porque el material es muy corto, pero cada clip debe tener una idea distinta."
    elif total < 90:
        min_dur, max_dur = 8, 24
        overlap = "Se permite superposición parcial si cada clip tiene una idea distinta."
    elif total < 150:
        min_dur, max_dur = 12, 30
        overlap = "Se permite superposición parcial si cada clip tiene una idea distinta."
    elif total < 300:
        min_dur, max_dur = 18, 45
        overlap = "Evitá superposiciones importantes."
    else:
        min_dur, max_dur = 25, 58
        overlap = "Evitá superposiciones importantes."

    category = str(options.get("category", "Entrevista"))
    mode = str(options.get("mode", "auto"))
    request = str(options.get("request", "")).strip() or "ninguno"
    political = ""
    if "pol" in category.lower():
        political = (
            "Para contenido político, seleccioná por claridad y relevancia informativa, "
            "sin favorecer ni perjudicar actores, partidos o candidatos."
        )

    prompt = f"""
Sos editor senior de Varez Servicios para Multimedios.
Elegí EXACTAMENTE 5 fragmentos para reels a partir de esta transcripción con timestamps.
Duración total: {total:.1f} segundos.
Cada clip debe durar entre {min_dur} y {max_dur} segundos. {overlap}
Priorizá respuestas completas, frases memorables, datos, consecuencias, explicaciones claras, emoción, sorpresa o humor.
Cada clip debe ser una mini historia autosuficiente: planteo o contexto suficiente, desarrollo y remate/cierre.
No empieces a mitad de palabra, oración o razonamiento. Evitá comienzos huérfanos como "sí", "no", "también", "porque", "entonces", "pero", "eso" o "esto" cuando no se entienda el referente.
No termines en conectores o promesas de continuación como "y", "pero", "porque", "entonces", "además", "yo creo que" o "lo que pasa es".
El corte debe quedar después de la última palabra que cierra la idea y antes de que comience la oración o el tema siguiente.
Evitá saludos, relleno, contexto incompleto y cortes a mitad de frase. Preferí una idea completa más corta antes que rellenarla o truncarla para alcanzar la duración máxima.
Empezá con una frase contundente, completa y autosuficiente del protagonista, nunca con la pregunta del entrevistador. Esa frase inicial lleva blanco y negro y audio telefónico. Después continúa el desarrollo en color y audio normal. Devolvé hook_end con el segundo absoluto donde termina esa frase completa; debe quedar desarrollo después. No inventes una duración fija. question_start y question_end deben ser -1. Si necesitás una pregunta para entender la respuesta, elegí otro momento autosuficiente.
Dejá solamente entre 0.25 y 0.65 segundos de aire después de la última palabra. No incluyas las primeras palabras de la idea siguiente.
Categoría: {category}. Modo: {mode}. Pedido específico: {request}.
{political}
Devolvé solamente la estructura solicitada, con exactamente 5 clips.

TRANSCRIPCIÓN:
{_transcript_text(transcript["segments"])}
""".strip()

    schema = _clip_schema()
    raw = None
    last_error = None

    # gpt-oss can separate reasoning from final content. For this machine and
    # workflow we want the final structured answer directly, so thinking is off.
    for attempt in range(3):
        try:
            status(
                42 + attempt,
                "Eligiendo los 5 mejores momentos…" if attempt == 0 else "Reintentando selección editorial…",
                model + (" · salida estructurada" if attempt == 0 else f" · intento {attempt + 1}/3"),
            )
            user_prompt = prompt
            if attempt:
                user_prompt += (
                    "\n\nEl intento anterior no produjo una respuesta estructurada válida. "
                    "Respondé exclusivamente con los 5 clips requeridos."
                )

            r = requests.post(
                OLLAMA + "/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "think": False,
                    "format": schema,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Sos un editor audiovisual. Respondé únicamente con datos que "
                                "cumplan exactamente el esquema JSON provisto."
                            ),
                        },
                        {"role": "user", "content": user_prompt},
                    ],
                    "options": {
                        "temperature": 0,
                        "num_predict": 2200,
                    },
                },
                timeout=1800,
            )
            r.raise_for_status()
            raw = _parse_clip_response(r.json())
            break
        except Exception as e:
            last_error = e
            time.sleep(0.8)

    if raw is None:
        status(
            46,
            "Usando selector de respaldo…",
            "El modelo editorial no entregó un JSON válido. Varez sigue sin perder la transcripción.",
        )
        raw = _fallback_clip_windows(transcript, total, min_dur, max_dur)

    clips = []
    for i, item in enumerate(raw):
        st = max(0.0, min(float(item.get("start", 0)), max(0.0, total - 0.2)))
        en = max(st + 0.5, min(float(item.get("end", st + min_dur)), total))
        qs = float(item.get("question_start", -1) or -1)
        qe = float(item.get("question_end", -1) or -1)
        if not (st <= qs < qe < en):
            qs = qe = -1

        clips.append({
            "title": str(item.get("title") or f"Clip {i+1}"),
            "start": st,
            "end": en,
            "question_start": qs,
            "question_end": qe,
            "hook_end": item.get("hook_end"),
            "reason": str(item.get("reason") or ""),
        })
    return clips



def _ass_time(sec):
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def make_ass(words, clip, out: Path):
    rel = []
    for w in words:
        if w["end"] >= clip["start"] and w["start"] <= clip["end"]:
            rel.append({
                "word": w["word"],
                "start": max(0.0, w["start"] - clip["start"]),
                "end": max(0.02, w["end"] - clip["start"]),
            })
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Varez,Arial,82,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,0,2,70,70,255,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    groups, group = [], []
    for w in rel:
        if group and (len(group) >= 4 or w["start"] - group[-1]["end"] > 0.55):
            groups.append(group); group = []
        group.append(w)
        if re.search(r"[.!?…]$", w["word"]) and len(group) >= 2:
            groups.append(group); group = []
    if group:
        groups.append(group)

    lines = []
    for g in groups:
        for i, w in enumerate(g):
            en = max(w["end"], g[i+1]["start"] if i + 1 < len(g) else w["end"] + 0.12)
            pieces = []
            for j, x in enumerate(g):
                color = "&H0033D6FF&" if j == i else "&H00FFFFFF&"
                token = x["word"].replace("{", "").replace("}", "").upper()
                pieces.append("{\\c" + color + "}" + token)
            lines.append(f"Dialogue: 0,{_ass_time(w['start'])},{_ass_time(en)},Varez,,0,0,0,,{' '.join(pieces)}")
    out.write_text(header + "\n".join(lines), encoding="utf-8")


def _intro_end(clip, words):
    dur = clip["end"] - clip["start"]
    declared = float(clip.get("hook_end") or 0) - clip["start"]
    if 0.7 < declared < dur - 0.7:
        return declared
    raise RuntimeError("No hay un gancho contundente inicial validado. Volvé a analizar la nota.")


def render_clip(video, clip, words, out, status, idx):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    dur = clip["end"] - clip["start"]
    ass = out.with_suffix(".ass")
    make_ass(words, clip, ass)
    q = _intro_end(clip, words)
    qa = q > 0.7 and q < dur - 0.7
    base = "setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    f = []
    if qa:
        transition = max(0.18, min(0.38, q - 0.25, dur - q - 0.25))
        f += [
            f"[0:v]{base},split=2[vq0][vr0]",
            f"[vq0]trim=start=0:end={q:.3f},setpts=PTS-STARTPTS,hue=s=0,eq=contrast=1.06:brightness=-0.025[vq]",
            f"[vr0]trim=start={q-transition:.3f},setpts=PTS-STARTPTS[vr]",
            f"[vq][vr]xfade=transition=fade:duration={transition:.3f}:offset={q-transition:.3f}[vbase]",
            "[0:a]asetpts=PTS-STARTPTS,asplit=2[aq0][ar0]",
            f"[aq0]atrim=start=0:end={q:.3f},asetpts=PTS-STARTPTS,highpass=f=300,lowpass=f=3400,equalizer=f=1400:t=q:w=1:g=3,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,volume=1.05[aq]",
            f"[ar0]atrim=start={q-transition:.3f},asetpts=PTS-STARTPTS[ar]",
            f"[aq][ar]acrossfade=d={transition:.3f}:c1=tri:c2=tri[abase]",
        ]
    else:
        f += [f"[0:v]{base}[vbase]", "[0:a]asetpts=PTS-STARTPTS[abase]"]
    ass_path = str(ass).replace("\\", "/").replace(":", "\\:")
    f += [f"[vbase]subtitles='{ass_path}'[v]", "[abase]loudnorm=I=-16:TP=-1.5:LRA=11[a]"]

    status(58 + idx * 8, f"Editando clip {idx+1}/5…", "1080×1920 · subtítulos dinámicos · audio normalizado.")
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{clip['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
        "-filter_complex", ";".join(f), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    ass.unlink(missing_ok=True)
    if p.returncode != 0:
        raise RuntimeError("FFmpeg falló en clip " + str(idx + 1) + ": " + p.stderr[-800:])


def _video_cache_key(video_path: Path):
    st = video_path.stat()
    raw = f"{video_path.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:24]


def _load_or_transcribe(video_path: Path, config, data_dir: Path, status):
    rt = detect_runtime(config)
    model_hint = rt["whisper_model"]
    cache_dir = data_dir / "cache" / "transcripts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{_video_cache_key(video_path)}_{model_hint}.json"

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text("utf-8"))
            if cached.get("segments") and cached.get("words"):
                status(35, "Transcripción recuperada…", "Ya estaba guardada en esta PC; no la vuelvo a procesar.")
                return cached
        except Exception:
            cache_file.unlink(missing_ok=True)

    transcript = _load_or_transcribe(video_path, config, data_dir, status)
    try:
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache_file)
    except Exception:
        pass
    return transcript


def run_job(video_path: Path, job_id: str, options, config, data_dir: Path, status):
    total = duration_seconds(video_path)
    if total <= 1:
        raise RuntimeError("No pude leer la duración del video.")
    transcript = transcribe(video_path, config, status)
    clips = select_clips(transcript, total, options, config, status)
    out_dir = data_dir / "outputs" / (time.strftime("%Y-%m-%d_%H-%M-%S") + "_" + job_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "selection.json").write_text(json.dumps(clips, indent=2, ensure_ascii=False), encoding="utf-8")
    outputs = []
    for i, clip in enumerate(clips):
        safe = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ_-]+", "_", clip["title"]).strip("_")[:55] or ("clip_" + str(i+1))
        out = out_dir / f"Varez_{i+1:02d}_{safe}.mp4"
        render_clip(video_path, clip, transcript["words"], out, status, i)
        outputs.append(out)
    return outputs
