#!/usr/bin/env python3
import argparse, json, os, subprocess, tempfile, requests, sys, re
from concurrent.futures import ThreadPoolExecutor, as_completed
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

def upload_signed_supabase(url,path):
    with open(path,"rb") as f:
        r=requests.put(url,headers={"content-type":"video/mp4","x-upsert":"true"},data=f,timeout=1800)
    if r.status_code>=400:
        raise RuntimeError(f"Supabase output upload -> {r.status_code}: {r.text[:500]}")
    return True

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
        segment=w.get("segment",0)
        w={"segment":segment,"word":str(w["word"]).strip(),"start":float(w.get("start",0)),"end":float(w.get("end",0))}
        gap=w["start"]-(g[-1]["end"] if g else w["start"])
        chars=sum(len(x["word"])+1 for x in g)+len(w["word"])
        if g and (segment != g[-1].get("segment",0) or len(g)>=4 or gap>.55 or chars>28):
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

def build_body_segments(words, duration, min_gap=.32, kept_gap=.14):
    duration=max(0.0,float(duration))
    clean=sorted((dict(w,start=float(w.get("start",0)),end=float(w.get("end",0))) for w in (words or [])
                  if float(w.get("end",0))>float(w.get("start",0))),key=lambda w:w["start"])
    if len(clean)<2: return [(0.0,duration)]
    segments=[]; start=0.0; side=kept_gap/2
    for left,right in zip(clean,clean[1:]):
        gap=max(0.0,right["start"]-left["end"])
        if gap<min_gap: continue
        end=min(duration,left["end"]+side)
        next_start=max(0.0,right["start"]-side)
        if next_start-end<.12: continue
        if end-start>=.08: segments.append((start,end))
        start=next_start
    if duration-start>=.08: segments.append((start,duration))
    return segments or [(0.0,duration)]

def remap_words(words, segments, segment_offset=0):
    offsets=[]; cursor=0.0
    for start,end in segments:
        offsets.append(cursor);cursor+=end-start
    mapped=[]
    for word in words or []:
        ws=float(word.get("start",0));we=float(word.get("end",0));mid=(ws+we)/2
        for i,(start,end) in enumerate(segments):
            if start-.04<=mid<=end+.04:
                item=dict(word,segment=segment_offset+i,
                          start=offsets[i]+max(start,ws)-start,
                          end=offsets[i]+min(end,we)-start)
                if item["end"]>item["start"]: mapped.append(item)
                break
    return mapped

def body_plan(clip):
    duration=max(1,float(clip["end"])-float(clip["start"]))
    if clip.get("remove_pauses",False):
        segments=build_body_segments(clip.get("words",[]),duration)
    else:
        segments=[(0.0,duration)]
    return segments,remap_words(clip.get("words",[]),segments,1),sum(end-start for start,end in segments)

def append_body_filters(fc, segments, base):
    count=len(segments)
    if count==1:
        start,end=segments[0]
        fc.extend([
            f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,{base}[bodyv]",
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,aresample=48000[bodya]",
        ])
        return
    vsrc=''.join(f"[vsrc{i}]" for i in range(count));asrc=''.join(f"[asrc{i}]" for i in range(count))
    fc.extend([f"[0:v]split={count}{vsrc}",f"[0:a]asplit={count}{asrc}"])
    chain=[]
    for i,(start,end) in enumerate(segments):
        fc.extend([
            f"[vsrc{i}]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,{base}[bv{i}]",
            f"[asrc{i}]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,aresample=48000[ba{i}]",
        ])
        chain.append(f"[bv{i}][ba{i}]")
    fc.append(''.join(chain)+f"concat=n={count}:v=1:a=1[bodyv][bodya]")

def run_ffmpeg(src, out, ass, clip):
    source_offset=max(0,float(clip.get("source_offset",0)))
    duration=max(1,float(clip["end"])-float(clip["start"]))
    q=float(clip.get("intro_end_rel") or clip.get("question_end_rel") or 0)
    captions=bool(clip.get("captions",True))
    qa=bool(clip.get("qa",True)) and q>.7 and q<duration-.7
    teaser=clip.get("edit_style")=="teaser" and bool(clip.get("qa",True))

    base="fps=30,settb=AVTB,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    fc=[];extra_inputs=[]
    if teaser or not qa:
        segments,_,_=body_plan(clip)
        append_body_filters(fc,segments,base)
    if teaser:
        hs=float(clip["hook_start_rel"]); he=float(clip["hook_end_rel"]);q=he-hs
        if not (0 <= hs < he <= duration+.02 and .7 < q <= 6): raise ValueError("Invalid teaser bounds")
        extra_inputs=["-ss",str(source_offset+hs),"-t",str(q),"-i",str(src)]
        fc += [
            f"[1:v]setpts=PTS-STARTPTS,{base},hue=s=0,eq=contrast=1.06:brightness=-0.025,drawgrid=w=iw:h=6:t=1:c=black@0.12[hookv]",
            f"[1:a]asetpts=PTS-STARTPTS,aresample=48000,highpass=f=300,lowpass=f=3400,equalizer=f=1400:t=q:w=1:g=3,apad,atrim=duration={q:.6f}[hooka]",
            "[hookv][hooka][bodyv][bodya]concat=n=2:v=1:a=1[vbase][speech]",
            f"anoisesrc=color=pink:amplitude=0.10:duration=0.24:sample_rate=48000,highpass=f=700,lowpass=f=6500,afade=t=in:d=0.10,afade=t=out:st=0.10:d=0.14,adelay={round((q-.12)*1000)}:all=1[whoosh]",
            "[speech][whoosh]amix=inputs=2:duration=first:normalize=0[abase]",
        ]
    elif qa:
        transition=max(.18,min(.38,q-.25,duration-q-.25))
        base_with_pts="setpts=PTS-STARTPTS,"+base
        fc += [
            f"[0:v]{base_with_pts},split=2[vq0][vr0]",
            f"[vq0]trim=start=0:end={q:.3f},setpts=PTS-STARTPTS,hue=s=0,eq=contrast=1.06:brightness=-0.025[vq]",
            f"[vr0]trim=start={q-transition:.3f},setpts=PTS-STARTPTS[vr]",
            f"[vq][vr]xfade=transition=fade:duration={transition:.3f}:offset={q-transition:.3f}[vbase]",
            "[0:a]asetpts=PTS-STARTPTS,asplit=2[aq0][ar0]",
            f"[aq0]atrim=start=0:end={q:.3f},asetpts=PTS-STARTPTS,highpass=f=300,lowpass=f=3400,equalizer=f=1400:t=q:w=1:g=3,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,volume=1.05[aq]",
            f"[ar0]atrim=start={q-transition:.3f},asetpts=PTS-STARTPTS[ar]",
            f"[aq][ar]acrossfade=d={transition:.3f}:c1=tri:c2=tri[abase]",
        ]
    else:
        fc += ["[bodyv]null[vbase]","[bodya]anull[abase]"]
    if captions:
        ass_escaped=str(ass).replace("\\","\\\\").replace(":","\\:")
        fc.append(f"[vbase]subtitles='{ass_escaped}'[v]")
    else:
        fc.append("[vbase]null[v]")
    fc.append("[abase]loudnorm=I=-16:TP=-1.5:LRA=11[a]")

    cmd=[
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-ss",str(source_offset),"-t",str(duration),"-i",str(src),
        *extra_inputs,
        "-filter_complex",";".join(fc),
        "-map","[v]","-map","[a]",
        "-c:v","libx264","-preset","veryfast","-crf","21","-maxrate","4200k","-bufsize","8400k","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)
    ]
    subprocess.run(cmd,check=True)

def caption_words(clip):
    teaser=clip.get("edit_style")=="teaser" and clip.get("qa",True)
    if not teaser and clip.get("qa",True): return clip.get("words",[])
    _,body,_=body_plan(clip)
    if not teaser: return body
    duration=float(clip["hook_end_rel"])-float(clip["hook_start_rel"])
    # Separate subtitle groups at the cut; the teaser must not borrow body words.
    return [dict(w, segment=0, end=min(float(w["end"]),duration-.15)) for w in clip.get("hook_words", [])] + [
        dict(w,start=float(w["start"])+duration,end=float(w["end"])+duration) for w in body
    ]

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
        def process_clip(item):
            i,clip=item
            index=clip.get("source_index",i)
            try:
                src=td/f"{jid}-source-{i:02d}.mp4"
                source_parts=clip.get("source_parts") or ([clip["source_url"]] if clip.get("source_url") else [])
                if not source_parts:
                    raise RuntimeError(f"Falta la fuente para clip {i}")
                with open(src,"wb") as f:
                    for part_url in source_parts:
                        rr=requests.get(part_url,timeout=1200,stream=True)
                        rr.raise_for_status()
                        for chunk in rr.iter_content(1024*1024):
                            if chunk: f.write(chunk)
                ass=td/f"clip-{i:02d}.ass"; make_ass(caption_words(clip),ass)
                out=td/f"{jid}-output-{i:02d}.mp4"
                run_ffmpeg(src,out,ass,clip)
                output_url=clip.get("output_upload_url")
                if not output_url: raise RuntimeError(f"Falta el destino para clip {i}")
                upload_signed_supabase(output_url,out)
                return {"ok":True,"order":i,"source_index":index,"output":clip.get("output_path") or out.name}
            except Exception as error:
                detail=str(error).strip()[:500]
                print(f"Clip {index} pendiente: {type(error).__name__}: {detail}. Continúan los demás.",file=sys.stderr)
                return {"ok":False,"order":i,"source_index":index,"error":type(error).__name__,"message":detail}
        items=list(enumerate(manifest["clips"],1))
        workers=max(1,min(2,len(items)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results=[future.result() for future in as_completed(pool.submit(process_clip,item) for item in items)]
        results.sort(key=lambda result:result["order"])
        made=[result["output"] for result in results if result["ok"]]
        errors=[{key:value for key,value in result.items() if key not in {"ok","order"}} for result in results if not result["ok"]]
        render_id=manifest.get("render_id") or jid
        if not re.fullmatch(r"[a-zA-Z0-9-]+",render_id): raise ValueError("render_id inválido")
        done=td/f"{render_id}-done.json"
        done.write_text(json.dumps({"ok":not errors,"job_id":jid,"outputs":made,"errors":errors}),encoding="utf-8")
        upload_asset(rid,done,done.name,"application/json")

if __name__=="__main__":
    try:
        main()
    except Exception as e:
        print(str(e),file=sys.stderr)
        raise
