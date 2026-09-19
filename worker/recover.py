#!/usr/bin/env python3
import argparse, os, requests, tempfile, sys
from pathlib import Path

OWNER="varezproduccionindependiente-collab"
REPO="varez-multimedios-app"
API="https://api.github.com"
CLOUD="https://fggygohsaoxlscgefshm.supabase.co/functions/v1/varez-cloud"
PIN="053362"
GH=os.environ["GH_TOKEN"]
HEAD={"Authorization":f"Bearer {GH}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2026-03-10"}

def gh(method,url,**kwargs):
    h=dict(HEAD); h.update(kwargs.pop("headers",{}))
    r=requests.request(method,url,headers=h,timeout=1200,**kwargs)
    if r.status_code>=400:
        raise RuntimeError(f"GitHub {r.status_code}: {r.text[:500]}")
    return r

def cloud(action,payload):
    r=requests.post(CLOUD+"?action="+action,headers={"x-varez-pin":PIN,"content-type":"application/json"},json=payload,timeout=120)
    if r.status_code>=400:
        raise RuntimeError(f"Cloud {r.status_code}: {r.text[:500]}")
    return r.json()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--release-id",type=int,required=True)
    ap.add_argument("--job-id",required=True)
    a=ap.parse_args()

    assets=gh("GET",f"{API}/repos/{OWNER}/{REPO}/releases/{a.release_id}/assets?per_page=100").json()
    amap={x["name"]:x for x in assets}

    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        for i in range(1,6):
            name=f"{a.job_id}-output-{i:02d}.mp4"
            asset=amap.get(name)
            if not asset:
                raise RuntimeError(f"Falta {name} en el release")
            path=td/name
            r=gh("GET",asset["url"],headers={"Accept":"application/octet-stream"},allow_redirects=True,stream=True)
            with open(path,"wb") as f:
                for chunk in r.iter_content(1024*1024):
                    if chunk: f.write(chunk)
            spec=cloud("upload-url",{"id":a.job_id,"name":name,"folder":"output"})
            with open(path,"rb") as f:
                up=requests.put(spec["signed_url"],headers={"content-type":"video/mp4","x-upsert":"true"},data=f,timeout=1800)
            if up.status_code>=400:
                raise RuntimeError(f"Supabase upload {name}: {up.status_code} {up.text[:500]}")
            print("Recovered",name)

if __name__=="__main__":
    try: main()
    except Exception as e:
        print(e,file=sys.stderr)
        raise
