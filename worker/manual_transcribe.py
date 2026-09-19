import json, os, subprocess, sys
from pathlib import Path

def sh(cmd):
    subprocess.run(cmd, check=True)

task=json.loads(Path("manual/task.json").read_text())
file_id=task["drive_file_id"]
job_id=task["job_id"]
src=Path("/tmp/source.mp4")
audio=Path("/tmp/audio.mp3")

sh([sys.executable,"-m","gdown",file_id,"-O",str(src)])
probe=subprocess.check_output([
    "ffprobe","-v","error","-show_entries","format=duration:stream=width,height",
    "-of","json",str(src)
],text=True)
meta=json.loads(probe)
sh(["ffmpeg","-y","-i",str(src),"-vn","-ac","1","-ar","16000","-c:a","libmp3lame","-b:a","48k",str(audio)])

from faster_whisper import WhisperModel
model=WhisperModel("small",device="cpu",compute_type="int8")
segments, info=model.transcribe(str(audio),language="es",beam_size=1,vad_filter=True)
out=[]
for s in segments:
    txt=(s.text or "").strip()
    if txt:
        out.append({"start":round(float(s.start),2),"end":round(float(s.end),2),"text":txt})
result={
    "job_id":job_id,
    "drive_file_id":file_id,
    "title":task.get("title",""),
    "duration":float(meta.get("format",{}).get("duration") or 0),
    "streams":meta.get("streams",[]),
    "language":getattr(info,"language","es"),
    "segments":out
}
Path("manual/transcript.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
print("segments",len(out),"duration",result["duration"])
