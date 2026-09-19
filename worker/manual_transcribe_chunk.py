import json, os
from pathlib import Path
from faster_whisper import WhisperModel

idx=int(os.environ["CHUNK_INDEX"])
chunk=Path(f"/tmp/chunks/chunk_{idx:03d}.mp3")
offset=float(os.environ.get("CHUNK_SECONDS","300"))*idx

model=WhisperModel("base",device="cpu",compute_type="int8")
segments,info=model.transcribe(str(chunk),language="es",beam_size=1,vad_filter=True)
out=[]
for s in segments:
    txt=(s.text or "").strip()
    if txt:
        out.append({
            "start":round(offset+float(s.start),2),
            "end":round(offset+float(s.end),2),
            "text":txt
        })
Path("/tmp/out").mkdir(exist_ok=True)
Path(f"/tmp/out/chunk_{idx:03d}.json").write_text(
    json.dumps({"idx":idx,"language":getattr(info,"language","es"),"segments":out},ensure_ascii=False,indent=2),
    encoding="utf-8"
)
print("chunk",idx,"segments",len(out))
