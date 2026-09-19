import json, subprocess, sys, os
from pathlib import Path

def sh(cmd):
    subprocess.run(cmd, check=True)

def ass_time(t):
    t=max(0.0,float(t))
    h=int(t//3600); t-=h*3600
    m=int(t//60); t-=m*60
    return f"{h}:{m:02d}:{t:05.2f}"

def esc(w):
    return str(w).upper().replace("{","(").replace("}",")")

def make_word_ass(path, words, timeline_offset=0.0, source_offset=0.0, group_size=4):
    header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Varez,DejaVu Sans,66,&H00FFFFFF,&H0000FFFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,5,1,2,70,70,315,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines=[header]
    for g0 in range(0,len(words),group_size):
        group=words[g0:g0+group_size]
        if not group: continue
        for j,w in enumerate(group):
            a=timeline_offset+(float(w["start"])-source_offset)
            b=timeline_offset+(float(w["end"])-source_offset)
            if b<=0 or b<=a: continue
            parts=[]
            for k,x in enumerate(group):
                token=esc(x["word"])
                if k==j:
                    token=r"{\c&H0000FFFF&}"+token+r"{\c&H00FFFFFF&}"
                parts.append(token)
            lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Varez,,0,0,0,,{' '.join(parts)}\n")
    Path(path).write_text("".join(lines),encoding="utf-8")

task=json.loads(Path("manual/render_task.json").read_text())
src=Path(os.environ.get("SOURCE_PATH","/tmp/source.mp4"))
if not src.exists():
    sh([sys.executable,"-m","gdown",task["drive_file_id"],"-O",str(src)])

from faster_whisper import WhisperModel
model=WhisperModel("small",device="cpu",compute_type="int8")

outdir=Path("manual/output")
outdir.mkdir(parents=True,exist_ok=True)

clips=task["clips"]
idx=os.getenv("CLIP_INDEX")
if idx is not None:
    clips=[clips[int(idx)]]

for clip in clips:
    name=clip["name"]
    hs=float(clip["hook_start"]); he=float(clip["hook_end"])
    bs=float(clip["body_start"]); be=float(clip["body_end"])
    hd=he-hs; bd=be-bs

    audio=Path(f"/tmp/{name}_body.wav")
    hook_ass=Path(f"/tmp/{name}_hook.ass")
    body_ass=Path(f"/tmp/{name}_body.ass")
    out=outdir/f"{name}.mp4"

    sh(["ffmpeg","-y","-ss",str(bs),"-t",str(bd),"-i",str(src),
        "-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(audio)])

    segments,_=model.transcribe(str(audio),language="es",beam_size=1,vad_filter=True,word_timestamps=True)
    words=[]
    for seg in segments:
        for w in (seg.words or []):
            token=(w.word or "").strip()
            if token:
                words.append({"start":float(w.start),"end":float(w.end),"word":token})

    hook_rel_start=hs-bs
    hook_rel_end=he-bs
    hook_words=[w for w in words if w["end"]>hook_rel_start and w["start"]<hook_rel_end]
    make_word_ass(hook_ass,hook_words,0.0,hook_rel_start,4)
    make_word_ass(body_ass,words,0.0,0.0,4)

    delay=max(0,int((hd-0.22)*1000))
    fc=f"""
[0:v]trim=start={hs}:end={he},setpts=PTS-STARTPTS,
scale=1080:1920:force_original_aspect_ratio=decrease,
pad=1080:1920:(ow-iw)/2:(oh-ih)/2,
hue=s=0,eq=contrast=1.16:brightness=-0.03,
subtitles={hook_ass}[hv];
[0:a]atrim=start={hs}:end={he},asetpts=PTS-STARTPTS,
aresample=async=1:first_pts=0,
highpass=f=300,lowpass=f=3400,
acompressor=threshold=-18dB:ratio=3:attack=5:release=80,
volume=1.12,
apad=pad_dur={hd},atrim=duration={hd}[ha0];
anoisesrc=color=white:amplitude=0.18:duration=0.28,
highpass=f=550,lowpass=f=7000,
afade=t=in:st=0:d=0.025,afade=t=out:st=0.10:d=0.18,
adelay={delay}|{delay}[who];
[ha0][who]amix=inputs=2:duration=first:dropout_transition=0,atrim=duration={hd}[ha];

[0:v]trim=start={bs}:end={be},setpts=PTS-STARTPTS,
scale=1080:1920:force_original_aspect_ratio=decrease,
pad=1080:1920:(ow-iw)/2:(oh-ih)/2,
subtitles={body_ass}[bv];
[0:a]atrim=start={bs}:end={be},asetpts=PTS-STARTPTS,
aresample=async=1:first_pts=0,apad=pad_dur={bd},atrim=duration={bd}[ba];

[hv][ha][bv][ba]concat=n=2:v=1:a=1[v][a]
"""
    sh(["ffmpeg","-y","-i",str(src),"-filter_complex",fc,
        "-map","[v]","-map","[a]",
        "-c:v","libx264","-preset","veryfast","-crf","21",
        "-c:a","aac","-b:a","160k","-r","30","-movflags","+faststart",str(out)])
    print(name,out.stat().st_size)
