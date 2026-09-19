"""Real FFmpeg render plus isolated partial-failure test. No external API calls."""
import array
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types

os.environ.setdefault('GH_TOKEN','test-only')
sys.modules['requests']=types.ModuleType('requests')
spec=importlib.util.spec_from_file_location('render',Path(__file__).resolve().parents[1]/'worker/render.py')
render=importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)

def cmd(*args):
    return subprocess.check_output(args,stderr=subprocess.PIPE)

def colorfulness(path,time):
    data=cmd('ffmpeg','-v','error','-ss',str(time),'-i',str(path),'-frames:v','1','-vf','crop=500:500:0:0,scale=32:32','-f','rawvideo','-pix_fmt','rgb24','-')
    return sum(abs(data[i]-data[i+1])+abs(data[i+1]-data[i+2]) for i in range(0,len(data),3))/(len(data)/3)

def frequency_ratio(path,time):
    raw=cmd('ffmpeg','-v','error','-ss',str(time),'-t','1','-i',str(path),'-vn','-ac','1','-ar','16000','-f','f32le','-')
    data=array.array('f',raw)
    def amplitude(freq):
        omega=2*math.pi*freq/16000
        real=sum(x*math.cos(omega*i) for i,x in enumerate(data))
        imag=sum(x*math.sin(omega*i) for i,x in enumerate(data))
        return math.hypot(real,imag)
    return amplitude(6000)/amplitude(1000)

with tempfile.TemporaryDirectory(prefix='varez-render-') as temp:
    d=Path(temp);src=d/'source.mp4';out=d/'output.mp4';ass=d/'captions.ass'
    cmd('ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=24',
        '-f','lavfi','-i','aevalsrc=0.08*sin(2*PI*120*t)+0.08*sin(2*PI*1000*t)+0.08*sin(2*PI*6000*t):s=48000',
        '-t','7','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(src))
    render.make_ass([{'word':'PRUEBA','start':.2,'end':1.4}],ass)
    render.run_ffmpeg(src,out,ass,{'start':0,'end':7,'intro_end_rel':3,'captions':True,'qa':True})
    probe=json.loads(cmd('ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(out)))
    assert abs(float(probe['format']['duration'])-7)<.1,probe
    assert any(s.get('width')==1080 and s.get('height')==1920 for s in probe['streams'])
    before=colorfulness(out,1);transition=colorfulness(out,2.82);after=colorfulness(out,4)
    assert before<3 and after>20,(before,after)
    assert before<transition<after,(before,transition,after)
    telephone=frequency_ratio(out,1);normal=frequency_ratio(out,4)
    assert telephone<normal*.5,(telephone,normal)
    print('PASS: 1080x1920, intact 7s timeline, B&W → transition → color, telephone → normal audio')

    teaser={'start':0,'end':7,'edit_style':'teaser','hook_start_rel':4,'hook_end_rel':7,'captions':True,'qa':True,
            'hook_words':[{'word':'FINAL','start':.1,'end':2.8}],
            'words':[{'word':'INICIO','start':.1,'end':1.0},{'word':'FINAL','start':4.1,'end':6.8}]}
    timeline=render.caption_words(teaser)
    assert timeline[1]['start']==3.1 and timeline[2]['start']==7.1
    render.make_ass(timeline,ass)
    render.run_ffmpeg(src,out,ass,teaser)
    probe=json.loads(cmd('ffprobe','-v','error','-show_entries','format=duration','-of','json',str(out)))
    assert abs(float(probe['format']['duration'])-10)<.1,probe
    assert colorfulness(out,2.9)<3 and colorfulness(out,3.05)>20
    assert frequency_ratio(out,1)<frequency_ratio(out,4)*.5
    print('PASS: ending teaser prepended, 10s total, hard color cut, phone audio, repeated captions')

    manifest={'render_id':'fixture-attempt-2','clips':[
      {'source_index':i,'source_parts':['broken' if i==2 else 'good'],'start':0,'end':7,'output_path':f'output-{i}.mp4','output_upload_url':f'upload-{i}'} for i in [1,2,3]]}
    class Response:
        def __init__(self,body):self.content=body
        def raise_for_status(self):pass
        def iter_content(self,size):yield self.content
    def get(url,**kwargs):
        if url=='broken':raise OSError('fixture download failure')
        return Response(json.dumps(manifest).encode() if url=='manifest' else src.read_bytes())
    render.requests.get=get
    render.run_ffmpeg=lambda src,out,ass,clip:out.write_bytes(b'fixture-render')
    published=[];done=[]
    render.upload_signed_supabase=lambda url,path:published.append(url)
    render.upload_asset=lambda rid,path,name,ctype:done.append((name,json.loads(path.read_text())))
    sys.argv=['render.py','--release-id','1','--job-id','fixture','--manifest-url','manifest']
    render.main()
    assert published==['upload-1','upload-3'],published
    assert done[0][0]=='fixture-attempt-2-done.json'
    assert done[0][1]['outputs']==['output-1.mp4','output-3.mp4']
    assert done[0][1]['errors'][0]['source_index']==2
    print('PASS: renderer preserves clip 1, reports failed clip 2 and delivers clip 3')
