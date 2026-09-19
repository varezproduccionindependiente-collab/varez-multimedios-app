import json, math, re, subprocess, sys
from pathlib import Path
import requests

def sh(cmd):
    print("RUN", " ".join(map(str,cmd)), flush=True)
    subprocess.run(cmd, check=True)

def ass_time(t):
    t=max(0,float(t))
    h=int(t//3600); t-=h*3600
    m=int(t//60); t-=m*60
    s=int(t); cs=int(round((t-s)*100))
    if cs>=100: s+=1; cs-=100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def esc_ass(s):
    return s.replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("\n"," ")

task=json.loads(Path("manual/render_task.json").read_text())
trans=json.loads(Path("manual/transcript.json").read_text())
file_id=task["drive_file_id"]
start=float(task["start"]); end=float(task["end"])
hs=float(task["hook_start"]); he=float(task["hook_end"])
hook_dur=max(.5,he-hs)
job_id=task["job_id"]
src=Path("/tmp/source.mp4")
ass=Path("/tmp/subs.ass")
out=Path("/tmp/final.mp4")

sh([sys.executable,"-m","gdown",file_id,"-O",str(src)])

# Approximate word times from the already generated segment transcript.
words=[]
for seg in trans["segments"]:
    a=float(seg["start"]); b=float(seg["end"])
    if b < start-1 or a > end+1: continue
    toks=re.findall(r"\S+",seg["text"])
    if not toks: continue
    step=max(.04,(b-a)/len(toks))
    for i,w in enumerate(toks):
        wa=a+i*step; wb=min(b,a+(i+1)*step)
        words.append({"w":w,"a":wa,"b":wb})

body_words=[x for x in words if x["b"]>=start and x["a"]<=end]
hook_words=[x for x in words if x["b"]>=hs and x["a"]<=he]

header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Varez,Arial,76,&H00FFFFFF,&H00FFFFFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,2,90,90,300,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
events=[]

def add_dynamic(word_list, map_time):
    # Groups of 3 words; highlight each active word in yellow.
    for g0 in range(0,len(word_list),3):
        grp=word_list[g0:g0+3]
        if not grp: continue
        for j,cur in enumerate(grp):
            a=map_time(max(cur["a"], start if word_list is body_words else hs))
            b=map_time(min(cur["b"], end if word_list is body_words else he))
            if b<=a: continue
            parts=[]
            for k,x in enumerate(grp):
                txt=esc_ass(x["w"].upper())
                if k==j: parts.append(r"{\c&H0000FFFF&}"+txt+r"{\c&H00FFFFFF&}")
                else: parts.append(txt)
            events.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Varez,,0,0,0,,{' '.join(parts)}")

# Hook at t=0; body starts after hook.
if hook_words:
    for g0 in range(0,len(hook_words),3):
        grp=hook_words[g0:g0+3]
        for j,cur in enumerate(grp):
            a=max(0,cur["a"]-hs); b=min(hook_dur,cur["b"]-hs)
            if b<=a: continue
            parts=[]
            for k,x in enumerate(grp):
                txt=esc_ass(x["w"].upper())
                parts.append((r"{\c&H0000FFFF&}"+txt+r"{\c&H00FFFFFF&}") if k==j else txt)
            events.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Varez,,0,0,0,,{' '.join(parts)}")

for g0 in range(0,len(body_words),3):
    grp=body_words[g0:g0+3]
    for j,cur in enumerate(grp):
        a=hook_dur+max(0,cur["a"]-start)
        b=hook_dur+min(end-start,cur["b"]-start)
        if b<=a: continue
        parts=[]
        for k,x in enumerate(grp):
            txt=esc_ass(x["w"].upper())
            parts.append((r"{\c&H0000FFFF&}"+txt+r"{\c&H00FFFFFF&}") if k==j else txt)
        events.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Varez,,0,0,0,,{' '.join(parts)}")

ass.write_text(header+"\n".join(events),encoding="utf-8")

whoosh_at=max(0,hook_dur-.12)
filter_complex=(
f"[0:v]trim=start={hs}:end={he},setpts=PTS-STARTPTS,"
"scale=1080:1920:force_original_aspect_ratio=decrease,"
"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
"hue=s=0,eq=contrast=1.10:brightness=-0.025,"
"drawgrid=width=iw:height=5:thickness=1:color=white@0.05[hv];"
f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
"scale=1080:1920:force_original_aspect_ratio=decrease,"
"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black[bv];"
"[hv][bv]concat=n=2:v=1:a=0[vcat];"
f"[vcat]ass={ass.as_posix()}[vout];"
f"[0:a]atrim=start={hs}:end={he},asetpts=PTS-STARTPTS,"
"highpass=f=320,lowpass=f=3300,acompressor=threshold=-20dB:ratio=4:attack=5:release=70,volume=1.05[ha];"
f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,volume=1.0[ba];"
"[ha][ba]concat=n=2:v=0:a=1[speech];"
f"anoisesrc=color=white:amplitude=0.10:duration=0.32,"
"highpass=f=900,lowpass=f=6800,afade=t=in:st=0:d=0.05,afade=t=out:st=0.13:d=0.19,"
f"adelay={int(whoosh_at*1000)}|{int(whoosh_at*1000)}[whoosh];"
"[speech][whoosh]amix=inputs=2:duration=first:dropout_transition=0[aout]"
)

sh(["ffmpeg","-y","-i",str(src),"-filter_complex",filter_complex,
    "-map","[vout]","-map","[aout]","-c:v","libx264","-preset","veryfast","-crf","20",
    "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(out)])

# Upload through the existing Varez private cloud path.
cloud="https://fggygohsaoxlscgefshm.supabase.co/functions/v1/varez-cloud"
headers={"x-varez-pin":"053362","Content-Type":"application/json"}
name=task.get("output_name","Nati_Tarot_Futuro_Varez.mp4")
spec=requests.post(cloud+"?action=upload-url",headers=headers,json={"id":job_id,"name":name,"folder":"output"},timeout=60)
spec.raise_for_status()
sp=spec.json()
with out.open("rb") as fh:
    up=requests.put(sp["signed_url"],data=fh,headers={"Content-Type":"video/mp4","cache-control":"max-age=3600"},timeout=600)
up.raise_for_status()
dl=requests.post(cloud+"?action=download-url",headers=headers,json={"path":sp["path"]},timeout=60)
dl.raise_for_status()
result={"job_id":job_id,"path":sp["path"],"url":dl.json()["url"],"name":name,"start":start,"end":end,"hook_start":hs,"hook_end":he}
Path("manual/render_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False),flush=True)
