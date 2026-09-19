#!/usr/bin/env python3
import argparse, json, subprocess, tempfile, requests, sys, re
from pathlib import Path

def get_json(url):
    r=requests.get(url,timeout=120)
    r.raise_for_status()
    return r.json()

def download(url,path):
    with requests.get(url,stream=True,timeout=600) as r:
        r.raise_for_status()
        with open(path,"wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk: f.write(chunk)

def upload_signed(url,path,ctype="video/mp4"):
    with open(path,"rb") as f:
        r=requests.put(url,data=f,headers={
            "content-type":ctype,
            "cache-control":"max-age=3600",
            "x-upsert":"true",
        },timeout=1200)
    if r.status_code>=400:
        raise RuntimeError(f"Supabase upload {r.status_code}: {r.text[:500]}")

def at(sec):
    sec=max(0.0,float(sec or 0))
    h=int(sec//3600); m=int((sec%3600)//60); s=sec%60
    return f"{h}:{m:02d}:{s:05.2f}"

def esc(s):
    return str(s or "").replace("{","").replace("}","").replace("\n"," ").strip()

def make_ass(words,path):
    words=[w for w in (words or []) if str(w.get("word","")).strip()]
    groups=[]; g=[]
    for raw in words:
        w={"word":str(raw["word"]).strip(),"start":float(raw.get("start",0)),"end":float(raw.get("end",0))}
        gap=w["start"]-(g[-1]["end"] if g else w["start"])
        chars=sum(len(x["word"])+1 for x in g)+len(w["word"])
        if g and (len(g)>=4 or gap>.55 or chars>28):
            groups.append(g); g=[]
        g.append(w)
        if re.search(r"[.!?…]$",w["word"]) and len(g)>=2:
            groups.append(g); g=[]
    if g: groups.append(g)
    head="""[Script Info]
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
    white="&H00FFFFFF&"; yellow="&H0033D6FF&"; lines=[]
    for group in groups:
        for i,w in enumerate(group):
            st=w["start"]
            en=max(w["end"],group[i+1]["start"]) if i<len(group)-1 else w["end"]+.15
            text=" ".join("{\\c"+(yellow if j==i else white)+"}"+esc(x["word"]).upper() for j,x in enumerate(group))
            lines.append(f"Dialogue: 0,{at(st)},{at(en)},Varez,,0,0,0,,{text}")
    Path(path).write_text(head+"\n".join(lines),encoding="utf-8")

def render(src,out,ass,c):
    offset=max(0,float(c.get("source_offset",0)))
    duration=max(1,float(c.get("duration",0)))
    q=float(c.get("question_end_rel") or 0)
    captions=bool(c.get("captions",True))
    qa=bool(c.get("qa",True)) and .7<q<duration-.7

    base="setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    fc=[]
    if qa:
        fc += [
            f"[0:v]{base},split=2[vq0][vr0]",
            f"[vq0]trim=start=0:end={q:.3f},setpts=PTS-STARTPTS,hue=s=0[vq]",
            f"[vr0]trim=start={q:.3f},setpts=PTS-STARTPTS[vr]",
            "[vq][vr]concat=n=2:v=1:a=0[vbase]",
            "[0:a]asetpts=PTS-STARTPTS,asplit=2[aq0][ar0]",
            f"[aq0]atrim=start=0:end={q:.3f},asetpts=PTS-STARTPTS,highpass=f=300,lowpass=f=3400,acompressor=threshold=-18dB:ratio=3,volume=1.05[aq]",
            f"[ar0]atrim=start={q:.3f},asetpts=PTS-STARTPTS[ar]",
            "[aq][ar]concat=n=2:v=0:a=1[abase]",
        ]
    else:
        fc += [f"[0:v]{base}[vbase]","[0:a]asetpts=PTS-STARTPTS[abase]"]

    if captions:
        ae=str(ass).replace("\\","\\\\").replace(":","\\:")
        fc.append(f"[vbase]subtitles='{ae}'[v]")
    else:
        fc.append("[vbase]null[v]")
    fc.append("[abase]loudnorm=I=-16:TP=-1.5:LRA=11[a]")

    cmd=[
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-ss",str(offset),"-t",str(duration),"-i",str(src),
        "-filter_complex",";".join(fc),
        "-map","[v]","-map","[a]",
        "-c:v","libx264","-preset","veryfast","-crf","21","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)
    ]
    subprocess.run(cmd,check=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--manifest-url",required=True)
    ap.add_argument("--job-id",required=True)
    a=ap.parse_args()
    manifest=get_json(a.manifest_url)
    clips=manifest.get("clips",[])
    if len(clips)!=5: raise RuntimeError("El manifest no tiene 5 clips.")
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        for i,c in enumerate(clips,1):
            src=td/f"source-{i:02d}.mp4"
            ass=td/f"clip-{i:02d}.ass"
            out=td/f"output-{i:02d}.mp4"
            download(c["source_url"],src)
            make_ass(c.get("words",[]),ass)
            render(src,out,ass,c)
            upload_signed(c["output_upload_url"],out)

if __name__=="__main__":
    try: main()
    except Exception as e:
        print(str(e),file=sys.stderr)
        raise
