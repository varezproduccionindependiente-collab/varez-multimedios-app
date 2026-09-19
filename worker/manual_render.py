import json, subprocess, sys, re
from pathlib import Path

def sh(cmd):
    subprocess.run(cmd, check=True)

def ass_time(t):
    h=int(t//3600); t-=h*3600
    m=int(t//60); t-=m*60
    return f"{h}:{m:02d}:{t:05.2f}"

def chunks(text, max_words=5):
    words=text.upper().split()
    return [words[i:i+max_words] for i in range(0,len(words),max_words)]

def styled(words):
    if not words: return ""
    stop={"DE","LA","EL","Y","O","A","EN","QUE","SI","YO","MI","UN","UNA","POR","PARA","NO","ES","LO","LOS","LAS","DEL","AL","SE"}
    candidates=[(len(re.sub(r'[^A-ZÁÉÍÓÚÜÑ]','',w)),i) for i,w in enumerate(words) if re.sub(r'[^A-ZÁÉÍÓÚÜÑ]','',w) not in stop]
    hi=max(candidates)[1] if candidates else len(words)-1
    out=[]
    for i,w in enumerate(words):
        if i==hi: out.append(r"{\c&H0000FFFF&}"+w+r"{\c&H00FFFFFF&}")
        else: out.append(w)
    return " ".join(out)

def make_ass(path, segments, offset, trim_start):
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
    for seg in segments:
        st=max(seg["start"],trim_start); en=seg["end"]
        if en<=st: continue
        parts=chunks(seg["text"],5)
        dur=max(.4,en-st)/len(parts)
        for j,words in enumerate(parts):
            a=offset+(st-trim_start)+j*dur
            b=offset+(st-trim_start)+(j+1)*dur
            lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Varez,,0,0,0,,{styled(words)}\n")
    Path(path).write_text("".join(lines),encoding="utf-8")

task=json.loads(Path("manual/render_task.json").read_text())
src=Path("/tmp/source.mp4")
hook=Path("/tmp/hook.mp4")
body=Path("/tmp/body.mp4")
out=Path("manual/output/Nati_Clip_01.mp4")
out.parent.mkdir(parents=True,exist_ok=True)

sh([sys.executable,"-m","gdown",task["drive_file_id"],"-O",str(src)])

hs=float(task["hook_start"]); he=float(task["hook_end"])
bs=float(task["body_start"]); be=float(task["body_end"])
hd=he-hs
hook_segments=[s for s in task["segments"] if s["end"]>hs and s["start"]<he]
body_segments=[s for s in task["segments"] if s["end"]>bs and s["start"]<be]
make_ass("/tmp/hook.ass",hook_segments,0,hs)
make_ass("/tmp/body.ass",body_segments,0,bs)

# Hook: B&W, stronger contrast, telephone voice, synthetic whoosh at the cut.
fc=f"""[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,hue=s=0,eq=contrast=1.16:brightness=-0.03,subtitles=/tmp/hook.ass[v];
[0:a]highpass=f=300,lowpass=f=3400,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,volume=1.12[a0];
anoisesrc=color=white:amplitude=0.25:duration=0.30,highpass=f=500,lowpass=f=7500,afade=t=in:st=0:d=0.03,afade=t=out:st=0.12:d=0.18,adelay={max(0,int((hd-0.18)*1000))}|{max(0,int((hd-0.18)*1000))}[who];
[a0][who]amix=inputs=2:duration=first:normalize=0[a]"""
sh(["ffmpeg","-y","-ss",str(hs),"-t",str(hd),"-i",str(src),"-filter_complex",fc,
    "-map","[v]","-map","[a]","-c:v","libx264","-preset","veryfast","-crf","21",
    "-c:a","aac","-b:a","160k","-r","30","-movflags","+faststart",str(hook)])

# Body: clean color, subtitles only.
vf="scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,subtitles=/tmp/body.ass"
sh(["ffmpeg","-y","-ss",str(bs),"-t",str(be-bs),"-i",str(src),"-vf",vf,
    "-c:v","libx264","-preset","veryfast","-crf","21","-c:a","aac","-b:a","160k",
    "-r","30","-movflags","+faststart",str(body)])

Path("/tmp/list.txt").write_text("file '/tmp/hook.mp4'\nfile '/tmp/body.mp4'\n")
sh(["ffmpeg","-y","-f","concat","-safe","0","-i","/tmp/list.txt","-c","copy",str(out)])
print(out, out.stat().st_size)
