"""Build an offline x64 installer from an existing CPython runtime and prepared inputs."""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

project=Path(__file__).resolve().parents[1]
csc=Path(os.environ["WINDIR"])/"Microsoft.NET/Framework64/v4.0.30319/csc.exe"
skip=shutil.ignore_patterns("__pycache__","*.pyc",".git","test","tests","idlelib","turtledemo","*.pdb")
def tree(a,b):
    shutil.copytree(a,b,dirs_exist_ok=True,ignore=skip)

def compile_cs(source,target,*options):
    subprocess.run([str(csc),"/nologo","/utf8output","/optimize+","/target:winexe","/out:"+str(target),*options,str(project/"packaging"/source)],check=True)

def source_files(stage):
    for name in ("core","desktop","desktop_ui","engine","bridge","update_engine"):
        shutil.copy2(project/(name+".py"),stage)
    tree(project/"extension",stage/"extension")
    compile_cs("Host.cs",stage/"MediaHarbor.exe")

def main():
    ap=argparse.ArgumentParser();ap.add_argument("inputs",type=Path)
    ap.add_argument("--runtime",type=Path,default=Path(sys.base_prefix));ap.add_argument("--prepare-only",action="store_true")
    a=ap.parse_args();base=a.inputs.resolve();stage=base/"package"
    runtime=stage/"runtime";runtime.mkdir(parents=True,exist_ok=True)
    for f in a.runtime.iterdir():
        if f.is_file() and (f.suffix.lower() in (".exe",".dll") or f.name=="LICENSE.txt"):shutil.copy2(f,runtime)
    for name in ("DLLs","Lib","tcl"):tree(a.runtime/name,runtime/name)
    tree(base/"tools",stage/"tools");tree(base/"vendor",stage/"vendor")
    if (base/"licenses").exists():tree(base/"licenses",stage/"licenses")
    source_files(stage)
    shutil.copy2(project/"packaging/THIRD-PARTY.md",stage/"THIRD-PARTY.md")
    if a.prepare_only:return
    for name in ("ffmpeg.exe","ffprobe.exe","aria2c.exe","node.exe"):
        if not (stage/"tools"/name).is_file():raise SystemExit("缺少 "+name)
    out=project/"output";out.mkdir(exist_ok=True)
    archive=base/"bundle.zip"
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:z.write(f,f.relative_to(stage))
    exe=out/"MediaHarbor-Setup-x64.exe"
    compile_cs("Setup.cs",exe,"/reference:System.IO.Compression.dll","/reference:System.IO.Compression.FileSystem.dll",
               "/reference:System.Windows.Forms.dll","/reference:Microsoft.CSharp.dll","/resource:"+str(archive)+",bundle")
    print(exe,exe.stat().st_size)
if __name__=="__main__": main()

