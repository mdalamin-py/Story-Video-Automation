"""Narration (Edge TTS, any language) and Unicode subtitles for cinematic-film (Windows).

The folder keeps its historical name; nothing here is specific to Bangla any more."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(os.environ.get('CINEMATIC_REPO', str(Path(__file__).resolve().parents[2])))
sys.path.insert(0, str(REPO / 'src'))
from multilingual import caption_font, wrap_unspaced
WORK = Path(r'C:\Users\HP\Documents\Codex\2026-11-22\d-video-maker-cinematic-skill\work')
if (WORK / 'win32').exists():
    os.environ['PATH'] = str(WORK / 'win32') + os.pathsep + os.environ['PATH']

def run(args, **kwargs):
    subprocess.run([str(x) for x in args], check=True, **kwargs)

def stamp(t):
    ms = round(t * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'

def srt(project):
    timing = json.loads((project/'audio/timing.json').read_text(encoding='utf-8-sig'))
    rows = []
    for i, seg in enumerate(timing['segments'], 1):
        text = wrap_unspaced(seg.get('caption') or seg['vo'])
        rows.append(f"{i}\n{stamp(seg['start'])} --> {stamp(seg['end'])}\n{text}\n")
    out = project/'out/captions.srt'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(rows), encoding='utf-8')
    return out

async def voice(a, project):
    import edge_tts
    script = json.loads((project/'script.json').read_text(encoding='utf-8-sig'))
    lines_dir = project/'audio/lines'
    lines_dir.mkdir(parents=True, exist_ok=True)
    segments = []
    ids = set()
    for take in script['takes']:
        for line in take['lines']:
            ident = line['id']
            if not isinstance(ident, int) or ident in ids:
                raise ValueError('Line IDs must be unique integers')
            ids.add(ident)
            spoken = line['spoken'].strip()
            if not spoken:
                raise ValueError(f'Empty narration: {ident}')
            mp3 = lines_dir/f'seg{ident:02}.mp3'
            print(f'Generating line {ident}...', flush=True)
            await edge_tts.Communicate(spoken, a.voice, rate=a.rate).save(str(mp3))
            run(['ffmpeg','-y','-v','error','-i',mp3,'-ar','48000','-ac','1',lines_dir/f'seg{ident:02}.wav'])
            segments.append(dict(id=ident,scene=take['take'],caption=line.get('text',spoken),vo=spoken,gap_after=line.get('gap_after',0.55)))
    (project/'audio/segments.json').write_text(json.dumps({'segments':segments},ensure_ascii=True,indent=2),encoding='utf-8')
    env = dict(os.environ, PYTHONUTF8='1')
    run([sys.executable,'-X','utf8',REPO/'skills/cinematic-film/scripts/build_narration.py','--project',project],env=env)
    print(srt(project))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    v = sub.add_parser('voice',help='Online TTS: sends spoken script text to the Edge speech service')
    v.add_argument('--project',required=True)
    v.add_argument('--voice',default='bn-BD-NabanitaNeural')
    v.add_argument('--rate',default='+0%')
    c = sub.add_parser('captions',help='Write a UTF-8 SRT and optionally burn the captions in, in any script')
    c.add_argument('--project',required=True)
    c.add_argument('--video')
    c.add_argument('--out')
    c.add_argument('--style',choices=['clean','highlighter','paper','redbar'],default='clean')
    a = parser.parse_args()
    project = Path(a.project).resolve()
    for tool in ('ffmpeg','ffprobe'):
        if not shutil.which(tool):
            parser.error(f'{tool} missing: load Load-Cinematic.ps1 first')
    if a.command == 'voice':
        asyncio.run(voice(a,project))
        return
    captions = srt(project)
    print(captions)
    if a.video:
        if not a.out:
            parser.error('--out is required with --video')
        video, out = Path(a.video).resolve(), Path(a.out).resolve()
        if video == out:
            parser.error('Input and output video must differ')
        out.parent.mkdir(parents=True,exist_ok=True)
        styles = {
            'clean': 'Outline=1,BorderStyle=1',
            'highlighter': 'Outline=4,Shadow=0,BorderStyle=3,OutlineColour=&H003DCBEA,BackColour=&H003DCBEA,PrimaryColour=&H00242424',
            'paper': 'Outline=4,Shadow=0,BorderStyle=3,OutlineColour=&H00DDEAF5,BackColour=&H00DDEAF5,PrimaryColour=&H00242424',
            'redbar': 'Outline=4,Shadow=0,BorderStyle=3,OutlineColour=&H00352C9E,BackColour=&H00352C9E,PrimaryColour=&H00FFFFFF',
        }
        # Relative temporary subtitle path avoids drive-letter escaping in FFmpeg filters.
        # The font follows the captions' own script: Nirmala UI for Indic, Segoe UI for Arabic/Urdu,
        # Microsoft YaHei for Chinese, Yu Gothic for Japanese, Malgun Gothic for Korean, and so on.
        font = caption_font(captions.read_text(encoding='utf-8'))
        print(f'Caption font: {font}')
        with tempfile.TemporaryDirectory(prefix='captions-') as temp:
            shutil.copy2(captions,Path(temp)/'captions.srt')
            run(['ffmpeg','-y','-v','warning','-i',video,'-vf',
                 f"subtitles=filename=captions.srt:charenc=UTF-8:force_style='FontName={font},FontSize=22,MarginV=22," + styles[a.style] + "'",
                 '-c:v','libx264','-threads','2','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',out],cwd=temp)
        print(out)

if __name__ == '__main__':
    main()
