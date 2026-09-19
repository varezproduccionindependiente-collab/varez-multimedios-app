from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import av
import imageio_ffmpeg
import psutil
import requests
from faster_whisper import WhisperModel

OLLAMA = "http://127.0.0.1:11434"


def detect_runtime(config):
    cuda = False
    gpu_name = None
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=3)
        if p.returncode == 0 and p.stdout.strip():
            cuda = True
            gpu_name = p.stdout.strip().splitlines()[0]
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


def transcribe(path: Path, config, status):
    rt = detect_runtime(config)
    device = "cuda" if rt["cuda"] else "cpu"
    compute = "float16" if device == "cuda" else "int8"
    model_name = rt["whisper_model"]
    status(7, "Cargando Whisper…", model_name + " · " + device.upper())
    model_root = Path(config.get("models_root") or (Path.home() / ".cache" / "varez-models"))
    whisper_root = model_root / "whisper"
    whisper_root.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(model_name, device=device, compute_type=compute, download_root=str(whisper_root))
    status(12, "Transcribiendo la nota completa…", "Whisper local con timestamps palabra por palabra.")
    segs, info = model.transcribe(
        str(path), language="es",
        beam_size=5 if device == "cuda" else 3,
        word_timestamps=True, vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=350),
        condition_on_previous_text=True,
    )
    segments, words = [], []
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


def _fmt(t):
    m = int(t // 60)
    s = t - m * 60
    return f"{m:02d}:{s:05.2f}"


def _transcript_text(segments):
    return "\n".join(f"[{_fmt(s['start'])}-{_fmt(s['end'])}] {s['text']}" for s in segments)


def select_clips(transcript, total, options, config, status):
    model = config["ollama_model"]
    try:
        tags = requests.get(OLLAMA + "/api/tags", timeout=3)
        tags.raise_for_status()
    except Exception:
        raise RuntimeError("Ollama no está ejecutándose. Abrilo o tocá 'Preparar IA local'.")

    names = [x.get("name", "") for x in tags.json().get("models", [])]
    if not any(x == model or x.startswith(model + ":") for x in names):
        raise RuntimeError("Falta el modelo local " + model + ". Tocá 'Preparar IA local' una sola vez.")

    short = total < 150
    medium = 150 <= total < 300
    min_dur, max_dur = (14, 30) if short else ((18, 45) if medium else (25, 58))
    overlap = "Se permite superposición parcial si cada clip tiene una idea distinta." if short else "Evitá superposiciones importantes."
    category = str(options.get("category", "Entrevista"))
    mode = str(options.get("mode", "auto"))
    request = str(options.get("request", "")).strip() or "ninguno"
    political = ""
    if "pol" in category.lower():
        political = "Para contenido político, seleccioná por claridad y relevancia informativa, sin favorecer ni perjudicar actores, partidos o candidatos."

    prompt = f"""
Sos editor senior de Varez Servicios para Multimedios.
Elegí EXACTAMENTE 5 fragmentos para reels a partir de esta transcripción con timestamps.
Duración total: {total:.1f} segundos.
Cada clip debe durar entre {min_dur} y {max_dur} segundos. {overlap}
Priorizá respuestas completas, frases memorables, datos, consecuencias, explicaciones claras, emoción, sorpresa o humor.
Evitá saludos, relleno, contexto incompleto y cortes a mitad de frase.
Si hay una pregunta breve antes de una buena respuesta, incluí la pregunta y marcá question_start y question_end; si no, ambos = -1.
El end debe quedar entre 1.3 y 2.3 segundos después de la última palabra de la idea elegida.
Categoría: {category}. Modo: {mode}. Pedido específico: {request}.
{political}
Respondé SOLO JSON con exactamente esta forma:
{{"clips":[{{"title":"...","start":0.0,"end":25.0,"question_start":-1,"question_end":-1,"reason":"..."}}]}}
Debe haber exactamente 5 objetos.

TRANSCRIPCIÓN:
{_transcript_text(transcript["segments"])}
""".strip()

    status(42, "Eligiendo los 5 mejores momentos…", model + " está haciendo la selección editorial local.")
    r = requests.post(
        OLLAMA + "/api/chat",
        json={
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": "Respondé en español y respetá exactamente el JSON pedido."},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0.15},
        },
        timeout=1800,
    )
    r.raise_for_status()
    content = r.json().get("message", {}).get("content", "")
    a, b = content.find("{"), content.rfind("}")
    if a < 0 or b <= a:
        raise RuntimeError("La IA local no devolvió una selección válida.")
    raw = json.loads(content[a:b+1]).get("clips")
    if not isinstance(raw, list) or len(raw) != 5:
        raise RuntimeError("La IA local no devolvió exactamente 5 clips.")

    clips = []
    for i, c in enumerate(raw):
        st = max(0.0, min(float(c.get("start", 0)), max(0.0, total - 0.2)))
        en = max(st + 0.5, min(float(c.get("end", st + min_dur)), total))
        if en - st < min_dur:
            en = min(total, st + min_dur)
            st = max(0.0, en - min_dur)
        if en - st > max_dur + 2.5:
            en = min(total, st + max_dur + 2.0)
        en = min(total, en + 1.4)
        qs = float(c.get("question_start", -1) or -1)
        qe = float(c.get("question_end", -1) or -1)
        if not (st <= qs < qe < en):
            qs = qe = -1
        clips.append({
            "title": str(c.get("title") or f"Clip {i+1}"),
            "start": st, "end": en,
            "question_start": qs, "question_end": qe,
            "reason": str(c.get("reason") or ""),
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


def render_clip(video, clip, words, out, status, idx):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    dur = clip["end"] - clip["start"]
    ass = out.with_suffix(".ass")
    make_ass(words, clip, ass)
    q = clip["question_end"] - clip["start"] if clip["question_end"] > clip["start"] else 0
    qa = q > 0.7 and q < dur - 0.7
    base = "setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    f = []
    if qa:
        f += [
            f"[0:v]{base},split=2[vq0][vr0]",
            f"[vq0]trim=start=0:end={q:.3f},setpts=PTS-STARTPTS,hue=s=0[vq]",
            f"[vr0]trim=start={q:.3f},setpts=PTS-STARTPTS[vr]",
            "[vq][vr]concat=n=2:v=1:a=0[vbase]",
            "[0:a]asetpts=PTS-STARTPTS,asplit=2[aq0][ar0]",
            f"[aq0]atrim=start=0:end={q:.3f},asetpts=PTS-STARTPTS,highpass=f=300,lowpass=f=3400,equalizer=f=1400:t=q:w=1:g=3,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,volume=1.05[aq]",
            f"[ar0]atrim=start={q:.3f},asetpts=PTS-STARTPTS[ar]",
            "[aq][ar]concat=n=2:v=0:a=1[abase]",
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
