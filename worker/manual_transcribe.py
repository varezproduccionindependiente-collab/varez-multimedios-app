import json, os, shutil, subprocess, sys
from pathlib import Path

def sh(cmd):
    subprocess.run(cmd, check=True)

task=json.loads(Path("manual/task.json").read_text())
job_id=task["job_id"]
src=Path("/tmp/source.mp4")
audio=Path("/tmp/audio.mp3")
source_name=""

if task.get("drive_file_id"):
    file_id=task["drive_file_id"]
    sh([sys.executable,"-m","gdown",file_id,"-O",str(src)])
    source_name=task.get("source_name","source.mp4")
elif task.get("drive_folder_id"):
    import gdown
    folder_id=task["drive_folder_id"]
    folder=Path("/tmp/drive_folder")
    folder.mkdir(parents=True,exist_ok=True)
    downloaded=gdown.download_folder(id=folder_id,output=str(folder),quiet=False,use_cookies=False)
    candidates=[]
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".mp4",".mov",".m4v",".mkv",".avi",".webm"}:
            candidates.append(p)
    if not candidates:
        raise RuntimeError("No se encontro ningun video descargable en la carpeta de Drive")
    chosen=max(candidates,key=lambda p:p.stat().st_size)
    shutil.copy2(chosen,src)
    file_id=""
    source_name=chosen.name
    print("selected_video",source_name,"bytes",chosen.stat().st_size)
else:
    raise RuntimeError("task.json requiere drive_file_id o drive_folder_id")

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
    "drive_folder_id":task.get("drive_folder_id",""),
    "source_name":source_name,
    "title":task.get("title",""),
    "duration":float(meta.get("format",{}).get("duration") or 0),
    "streams":meta.get("streams",[]),
    "language":getattr(info,"language","es"),
    "segments":out
}
Path("manual/transcript.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
print("segments",len(out),"duration",result["duration"],"source",source_name)
