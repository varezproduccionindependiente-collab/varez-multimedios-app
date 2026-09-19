#!/usr/bin/env python3
import argparse, json, os, subprocess, tempfile, requests, sys, re
from pathlib import Path

API="https://api.github.com"
OWNER="varezproduccionindependiente-collab"
REPO="varez-multimedios-app"
TOKEN=os.environ["GH_TOKEN"]
HEAD={
    "Authorization": f"Bearer {TOKEN}",
    "Accept":"application/vnd.github+json",
    "X-GitHub-Api-Version":"2026-03-10",
}

def req(method,url,**kwargs):
    h=dict(HEAD); h.update(kwargs.pop("headers",{}))
    r=requests.request(method,url,headers=h,timeout=600,**kwargs)
    if r.status_code>=400:
        raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text[:500]}")
    return r

def list_assets(release_id):
    return req("GET",f"{API}/repos/{OWNER}/{REPO}/releases/{release_id}/assets?per_page=100").json()

def download_asset(asset,path):
    h={"Accept":"application/octet-stream"}
    r=req("GET",asset["url"],headers=h,allow_redirects=True,stream=True)
    with open(path,"wb") as f:
        for chunk in r.iter_content(1024*1024):
            if chunk: f.write(chunk)

def delete_asset(asset_id):
    req("DELETE",f"{API}/repos/{OWNER}/{REPO}/releases/assets/{asset_id}")

def upload_asset(release_id,path,name,ctype="application/octet-stream"):
    url=f"https://uploads.github.com/repos/{OWNER}/{REPO}/releases/{release_id}/assets"
    with open(path,"rb") as f:
        r=requests.post(url,params={"name":name},headers={
            "Authorization":f"Bearer {TOKEN}",
            "Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2026-03-10",
            "Content-Type":ctype,
        },data=f,timeout=1800)
    if r.status_code>=400:
        raise RuntimeError(f"upload {name}: {r.status_code} {r.text[:500]}")
    return r.json()

def at(sec):
    sec=max(0.0,float(sec or 0))
    h=int(sec//3600); m=int((sec%3600)//60); s=sec%60
    return f"{h}:{m:02d}:{s:05.2f}"

def ass_escape(s):
    return str(s or "").replace("{","").replace("}","").replace("\n"," ").strip()

def make_ass(words, out_path):
    words=[w for w in (words or []) if str(w.get("word","")).strip()]
    groups=[]; g=[]
    for w in words:
        w={"word":str(w["word"]).strip(),"start":float(w.get("start",0)),"end":float(w.get("end",0))}
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
    lines=[]; white="&H00FFFFFF&"; yellow="&H0033D6FF&"
    for group in groups:
        for i,w in enumerate(group):
            st=w["start"]; en=(max(w["end"],group[i+1]["start"]) if i<len(group)-1 else w["end"]+.15)
            txt=" ".join(
                "{\\c"+(yellow if j==i else white)+"}"+ass_escape(x["word"]).upper()
                for j,x in enumerate(group)
            )
            lines.append(f"Dialogue: 0,{at(st)},{at(en)},Varez,,0,0,0,,{txt}")
    Path(out_path).write_text(head+"\n".join(lines),encoding="utf-8")

def run_ffmpeg(src, out, ass, clip):
    source_offset=max(0,float(clip.get("source_offset",0)))
    duration=max(1,float(clip["end"])-float(clip["start"]))
    q=float(clip.get("question_end_rel") or 0)
    captions=bool(clip.get("captions",True))
    qa=bool(clip.get("qa",True)) and q>.7 and q<duration-.7

    base="setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    fc=[]
    if qa:
        fc += [
            f"[0:v]{base},split=2[vq0][vr0]",
            f"[vq0]trim=start=0:end={q:.3f},setpts=PTS-STARTPTS,hue=s=0[vq]",
            f"[vr0]trim=start={q:.3f},setpts=PTS-STARTPTS[vr]",
            "[vq][vr]concat=n=2:v=1:a=0[vbase]",
            "[0:a]asetpts=PTS-STARTPTS,asplit=2[aq0][ar0]",
            f"[aq0]atrim=start=0:end={q:.3f},asetpts=PTS-STARTPTS,highpass=f=320,lowpass=f=3300,volume=1.08[aq]",
            f"[ar0]atrim=start={q:.3f},asetpts=PTS-STARTPTS[ar]",
            "[aq][ar]concat=n=2:v=0:a=1[abase]",
        ]
    else:
        fc += [f"[0:v]{base}[vbase]","[0:a]asetpts=PTS-STARTPTS[abase]"]
    if captions:
        ass_escaped=str(ass).replace("\\","\\\\").replace(":","\\:")
        fc.append(f"[vbase]subtitles='{ass_escaped}'[v]")
    else:
        fc.append("[vbase]null[v]")
    fc.append("[abase]loudnorm=I=-16:TP=-1.5:LRA=11[a]")

    cmd=[
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-ss",str(source_offset),"-t",str(duration),"-i",str(src),
        "-filter_complex",";".join(fc),
        "-map","[v]","-map","[a]",
        "-c:v","libx264","-preset","veryfast","-crf","21","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)
    ]
    subprocess.run(cmd,check=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--release-id",required=True,type=int)
    ap.add_argument("--job-id",required=True)
    ap.add_argument("--manifest-url",required=True)
    a=ap.parse_args()
    rid=a.release_id; jid=a.job_id
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        mpath=td/"manifest.json"
        r=requests.get(a.manifest_url,timeout=600)
        r.raise_for_status()
        mpath.write_bytes(r.content)
        manifest=json.loads(mpath.read_text("utf-8"))
        made=[]
        for i,clip in enumerate(manifest["clips"],1):
            src_name=f"{jid}-source-{i:02d}.mp4"
            src=td/src_name
            source_url=clip.get("source_url")
            if not source_url: raise RuntimeError(f"Falta source_url para clip {i}")
            rr=requests.get(source_url,timeout=1200,stream=True)
            rr.raise_for_status()
            with open(src,"wb") as f:
                for chunk in rr.iter_content(1024*1024):
                    if chunk: f.write(chunk)
            ass=td/f"clip-{i:02d}.ass"; make_ass(clip.get("words",[]),ass)
            out=td/f"{jid}-output-{i:02d}.mp4"
            run_ffmpeg(src,out,ass,clip)
            old=[x for x in list_assets(rid) if x["name"]==out.name]
            for x in old: delete_asset(x["id"])
            upload_asset(rid,out,out.name,"video/mp4")
            made.append(out.name)
        done=td/f"{jid}-done.json"
        done.write_text(json.dumps({"ok":True,"job_id":jid,"outputs":made}),encoding="utf-8")
        upload_asset(rid,done,done.name,"application/json")

if __name__=="__main__":
    try:
        main()
    except Exception as e:
        print(str(e),file=sys.stderr)
        raise
