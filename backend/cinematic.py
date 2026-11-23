"""Cinematic-film workflow used directly by the Node dashboard."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/cinematic-film/scripts'
HELPERS = ROOT / 'tools/windows-bangla'
LOOK_REVIEW = ROOT / 'tools/review_look.py'
FINAL = 'out/final-video.mp4'      # projects made before multi-language support used out/final-bangla.mp4
LOOKS = {'studio', 'wall', 'slate', 'charcoal', 'blueprint', 'paper', 'night'}
LEGACY_RUNTIME = r'C:\Users\HP\Documents\Codex\2026-11-22\d-video-maker-cinematic-skill\work'
WAITING = {'AWAITING_SCRIPT', 'AWAITING_LOOK', 'AWAITING_DRAFT'}

def ffmpeg_dir():
    """Folder holding ffmpeg and ffprobe: FFMPEG_PATH from .env, then tools/ffmpeg in this project,
    then PATH, then the runtime this PC was first set up with (STUDIO_RUNTIME)."""
    exe = '.exe' if os.name == 'nt' else ''
    configured = os.environ.get('FFMPEG_PATH', '').strip().strip('"')
    candidates = [Path(configured).parent] if configured else []
    candidates += [ROOT/'tools/ffmpeg/bin', ROOT/'tools/ffmpeg']
    on_path = shutil.which('ffmpeg')
    if on_path:
        candidates.append(Path(on_path).parent)
    candidates.append(Path(os.environ.get('STUDIO_RUNTIME', LEGACY_RUNTIME))/'win32')
    return next((d for d in candidates if (d/f'ffmpeg{exe}').is_file() and (d/f'ffprobe{exe}').is_file()), None)

def add_ffmpeg_to_path():
    found = ffmpeg_dir()
    if found and str(found) not in os.environ.get('PATH', '').split(os.pathsep):
        os.environ['PATH'] = str(found) + os.pathsep + os.environ.get('PATH', '')
    return found

_CODEX = []

def codex_cli():
    """The Codex command line: CODEX_PATH in .env, then PATH, then the installed Codex app.
    Windows does not let ordinary programs list the WindowsApps folder, so the app's folder
    is asked from Windows (Get-AppxPackage) instead of searched for."""
    configured = os.environ.get('CODEX_PATH', '').strip().strip('"')
    if configured:
        return configured if Path(configured).is_file() else None
    if _CODEX:
        return _CODEX[0]
    found = shutil.which('codex')
    if not found and os.name == 'nt':
        try:
            located = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                                      "(Get-AppxPackage -Name 'OpenAI.Codex').InstallLocation"],
                                     capture_output=True, text=True, timeout=20).stdout.split()
            exe = Path(' '.join(located)) / 'app/resources/codex.exe' if located else None
            found = str(exe) if exe and exe.is_file() else None
        except (OSError, subprocess.SubprocessError):
            found = None
    if found:
        _CODEX.append(found)
    return found

def read(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def options(raw=None):
    value = dict(review=True, look='studio', size='640x360', voice='bn-BD-NabanitaNeural',
                 audio=True, captions=True, caption_style='clean', sfx=True, archive=False, maps=False,
                 duration=30, language='বাংলা', voice_source='edge', music=None)
    raw = raw or {}
    if set(raw) - set(value):
        raise ValueError('Unknown cinematic setting')
    value.update(raw)
    for key in ('review', 'audio', 'captions', 'sfx', 'archive', 'maps'):
        if type(value[key]) is not bool:
            raise ValueError(f'{key} must be true or false')
    if value['voice_source'] not in {'edge','takes','lines'}:
        raise ValueError('Unsupported voice source')
    if value['music'] is not None and (not isinstance(value['music'],str) or value['music']!='audio/music.mp3'):
        raise ValueError('Background score must be audio/music.mp3 inside the project')
    if value['music'] and not value['audio']:
        raise ValueError('Enable narration when using the background score mixer')
    if value['look'] not in LOOKS or value['caption_style'] not in {'clean','highlighter','paper','redbar'}:
        raise ValueError('Unsupported look or caption style')
    if value['size'] not in {'640x360','1280x720','1920x1080','360x640','720x1280','1080x1920','2560x1440','3840x2160','1440x2560','2160x3840'}:
        raise ValueError('Unsupported render size')
    if type(value['duration']) is not int or not 5 <= value['duration'] <= 180:
        raise ValueError('Duration must be between 5 and 180 seconds')
    if not isinstance(value['voice'], str) or not value['voice'].strip() or len(value['voice']) > 100:
        raise ValueError('Choose a valid voice')
    if not isinstance(value['language'], str) or len(value['language']) > 100:
        raise ValueError('Choose a language')
    return value

def codex_options():
    """Optional Codex model and reasoning effort from .env (CODEX_MODEL, CODEX_REASONING_EFFORT).
    Unset keeps your Codex defaults; a lower effort plans faster and uses less of your quota."""
    import re
    args=[]
    model=os.environ.get('CODEX_MODEL','').strip()
    if model:
        if not re.fullmatch(r'[A-Za-z0-9._:-]{1,80}',model):
            raise ValueError('CODEX_MODEL contains unsupported characters')
        args+=['-m',model]
    effort=os.environ.get('CODEX_REASONING_EFFORT','').strip().lower()
    if effort:
        if effort not in {'minimal','low','medium','high','xhigh'}:
            raise ValueError('CODEX_REASONING_EFFORT must be minimal, low, medium, high or xhigh')
        args+=['-c',f'model_reasoning_effort="{effort}"']
    return args


class Pipeline:
    def __init__(self, folder, runner=None, planner=None):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.config = options(read(self.folder/'cinematic-options.json', {}))
        self.state = read(self.folder/'pipeline.json', {'status':'NEW','events':[],'completed':[]})
        self.runner = runner or self.execute
        self.planner = planner or self.generate_plan
        os.environ['CINEMATIC_REPO'] = str(ROOT)
        os.environ['PYTHONUTF8'] = '1'
        add_ffmpeg_to_path()

    def save(self, status=None, stage=None, error=None):
        if status:
            self.state['status'] = status
        if stage:
            self.state['stage'] = stage
        self.state['error'] = error
        self.state['updated'] = datetime.now(timezone.utc).isoformat()
        write(self.folder/'pipeline.json', self.state)

    def execute(self, script, args):
        command = [sys.executable, '-X', 'utf8', str(script), *map(str,args)]
        name = Path(script).name
        result = subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                                encoding='utf-8',errors='replace',env=dict(os.environ,PYTHONUTF8='1'),
                                timeout=120 if name=='build_sfx.py' else 1800)
        with (self.folder/'production.log').open('a',encoding='utf-8') as log:
            log.write('\n' + name + '\n' + result.stdout)
        if result.returncode:
            lines = [l for l in result.stdout.splitlines() if l.strip()]
            if name == 'check_setup.py':
                missing = [l.strip() for l in lines if '[MISSING]' in l]
                raise RuntimeError('Setup check failed. ' + ' '.join(missing or lines[-3:]))
            raise RuntimeError(f'{name} failed (exit {result.returncode}): ' + ' | '.join(lines[-6:])[-1500:])
        return result.stdout

    def step(self, name, script, *args):
        self.save('RUNNING',name)
        self.runner(script,list(args))
        if name not in self.state['completed']:
            self.state['completed'].append(name)
        self.state['events'].append({'stage':name,'at':datetime.now(timezone.utc).isoformat()})
        self.state['events'] = self.state['events'][-100:]
        self.save()

    def tool(self, name, script, *args):
        self.step(name,SCRIPTS/script,'--project',self.folder,*args)

    def fingerprint(self, ignore=()):
        digest=hashlib.sha256()
        for name in ('script.json','scene.py','photos.json','map.json','cinematic-options.json'):
            if name in ignore:
                continue
            p=self.folder/name
            if p.exists():
                digest.update(name.encode());digest.update(p.read_bytes())
        return digest.hexdigest()

    def validate_plan(self):
        script=read(self.folder/'script.json')
        if not isinstance(script,dict) or not script.get('takes') or not (self.folder/'scene.py').is_file():
            raise ValueError('A valid script.json and scene.py are required')
        ids=set()
        for take in script['takes']:
            if not isinstance(take.get('take'),str) or not take.get('lines'):
                raise ValueError('Each take needs a name and narration lines')
            for line in take['lines']:
                ident=line.get('id')
                if type(ident) is not int or ident in ids:
                    raise ValueError('Narration line IDs must be unique integers')
                ids.add(ident)
                for field in ('spoken','text','hero'):
                    if not isinstance(line.get(field),str) or not line[field].strip():
                        raise ValueError(f'Line {ident} needs {field}')
        if len(ids)>100:
            raise ValueError('Split films with over 100 narration lines into smaller projects')
        return script

    def generate_plan(self):
        cli=codex_cli()
        if not cli:
            raise RuntimeError('Codex CLI is missing. Install/sign in to Codex before generating a script.')
        request=(self.folder/'user-prompt.txt').read_text(encoding='utf-8')
        lint=self.state.get('lint') or []
        fix_now=('\nThe current beat table has these lint warnings; fix every one:\n- '+'\n- '.join(lint)) if lint else ''
        prompt=f'''Prepare a cinematic-film PROJECT PLAN only in {self.folder}.{fix_now}
User story: {request}
Structured settings (take priority): {json.dumps(self.config,ensure_ascii=False)}
Read skills/cinematic-film/SKILL.md and references/story.md and references/film.md.
Create script.json (takes/lines with id,text,spoken,hero,typed), scene.py (build_film(doc)),
photos.json, optional map.json, story-plan.json, and credits.md with honest asset sources.
Use one continuous world, camera shots and spotlights from the bundled engine, word/line-timed effects.
Use the selected look, render aspect and duration. Design actual illustrations or meaningful visual items,
not generic scene-number cards. Drawn illustration is fine; never pretend generated art is evidence.
Use archival Commons assets only if archive=true. If maps=true, provide map.json compatible with make_map.py.
Keep scene.py independent of timing files at import; use doc inside build_film.
Write the narration (spoken), captions (text) and on-screen words in the selected language:
{self.config['language']}. Keep names and brands as they are normally written in that language.
The engine shapes every script (Devanagari, Bengali, Tamil, Arabic/Urdu right to left, Chinese,
Japanese, Korean, Thai, ...) and picks a font for it, so on-screen text can be in that language.
doc.W times words by Unicode letter shares (approximate word timing); do not claim exact alignment.
In languages without spaces between words (Chinese, Japanese, Thai) time items with doc.L/doc.E.
Keep narration short enough for the requested duration; speak numbers as words. Use the selected language.
Use large readable text; captions are shaped by FFmpeg/libass in a font for their script. Read the engine API before writing code.
Do not render, synthesize voice, run paid media APIs, upload, change dependencies, or edit other projects.
When the plan files exist, run: "{sys.executable}" -X utf8 "{SCRIPTS/'make_beats.py'}" --project "{self.folder}"
then read the Lint section at the end of beats.md and fix every warning in script.json (and scene.py if needed),
repeating until it is clean or a warning is a deliberate choice you can justify in story-plan.json.
The app then requests the user's script approval. Only save the plan files above and beats.md.
If plan files already exist, preserve the user's story and edit them in place: change only what the
revision notes or lint warnings ask for, and re-read references only for the parts you change.
Finish by describing the plan briefly. Never print credentials.'''
        command=[cli,'exec','--sandbox','workspace-write','-C',str(ROOT),'--color','never','-o',str(self.folder/'result.txt')]
        command+=codex_options()
        with (self.folder/'run.log').open('a',encoding='utf-8') as log:
            subprocess.run([*command,'-'],input=prompt,
                           encoding='utf-8',stdout=log,stderr=subprocess.STDOUT,check=True,cwd=ROOT)

    def lint(self):
        """Warnings from the Lint section make_beats.py appends to beats.md."""
        beats=self.folder/'beats.md'
        text=beats.read_text(encoding='utf-8-sig') if beats.exists() else ''
        section=text.split('\n## Lint\n',1)[1] if '\n## Lint\n' in text else ''
        self.state['lint']=[l[2:].strip() for l in section.splitlines() if l.startswith('- ')]
        return self.state['lint']

    def prepare(self):
        # A new or revised plan makes earlier look and voice findings stale.
        for key in ('look_review','voice_flags'):
            self.state.pop(key,None)
        self.step('setup check',SCRIPTS/'check_setup.py')
        if not (self.folder/'script.json').is_file() or not (self.folder/'scene.py').is_file():
            self.save('RUNNING','story')
            self.planner()
        self.validate_plan()
        for sub in ('audio','assets/photos','assets/prep','out','fonts'):
            (self.folder/sub).mkdir(parents=True,exist_ok=True)
        if not (self.folder/'photos.json').exists():
            write(self.folder/'photos.json',{'grade':'natural','photos':[],'recreations':[]})
        self.tool('beats','make_beats.py')
        self.lint()
        self.state['plan_hash']=self.fingerprint()
        self.save('AWAITING_SCRIPT','script review')

    def revise(self):
        self.state['completed']=[]
        self.save('RUNNING','revising story')
        self.planner()
        self.prepare()

    def assert_plan(self):
        self.validate_plan()
        if self.fingerprint()!=self.state.get('plan_hash'):
            raise ValueError('Plan/settings changed. Prepare the plan again before continuing.')

    def timed_voice(self):
        script=self.validate_plan()
        if self.config['audio']:
            # Cache is tied to spoken text and the selected voice, not only file existence.
            voice_script=[{k:line.get(k) for k in ('id','spoken','text','gap_after')} for take in script['takes'] for line in take['lines']]
            key=hashlib.sha256(json.dumps([voice_script,self.config['voice'],self.config['voice_source']],sort_keys=True).encode()).hexdigest()
            if self.config['voice_source']!='edge':
                paths=sorted((self.folder/'audio'/self.config['voice_source']).glob('*.wav'))
                key=hashlib.sha256((key+''.join(hashlib.sha256(p.read_bytes()).hexdigest() for p in paths)).encode()).hexdigest()
            if read(self.folder/'audio/voice-cache.json',{}).get('key')!=key or not (self.folder/'audio/narration.m4a').exists():
                if self.config['voice_source']=='edge':
                    self.step('voice',HELPERS/'bangla_tools.py','voice','--project',self.folder,'--voice',self.config['voice'])
                else:
                    if self.config['voice_source']=='takes':
                        self.tool('voice split','split_takes.py')
                        report=read(self.folder/'audio/lines/split_report.json',[])
                        self.state['voice_flags']=[f"Line {r['id']}: {r['lps']} letters/s is far from the median; listen for a misplaced cut or a dropped word ({r['text'][:60]})"
                                                   for r in report if r.get('flag')]
                    else:
                        segments=[]
                        for take in script['takes']:
                            for line in take['lines']:
                                if not (self.folder/'audio/lines'/f"seg{line['id']:02}.wav").exists():
                                    raise ValueError(f"Missing recorded line: audio/lines/seg{line['id']:02}.wav")
                                segments.append(dict(id=line['id'],scene=take['take'],caption=line['text'],vo=line['spoken'],gap_after=line.get('gap_after',.55)))
                        write(self.folder/'audio/segments.json',{'segments':segments})
                    self.tool('voice','build_narration.py')
                write(self.folder/'audio/voice-cache.json',{'key':key})
        else:
            # Silent films deliberately use estimated durations, never present these as speech timings.
            segments=[];cursor=0.6
            lines=[line for take in script['takes'] for line in take['lines']]
            budget=max(1,self.config['duration']-1.2)
            weights=[max(1,len(line['spoken'])) for line in lines]
            for line,weight in zip(lines,weights):
                duration=budget*weight/sum(weights)
                segments.append(dict(id=line['id'],vo=line['spoken'],caption=line['text'],start=cursor,end=cursor+duration,duration=duration))
                cursor+=duration
            write(self.folder/'audio/timing.json',{'segments':segments,'total_duration':cursor+0.6,'timing_source':'silent film estimates'})

    def preview(self):
        self.assert_plan();core_hash=self.fingerprint(ignore={'photos.json'});self.timed_voice()
        if self.config['archive']:
            self.step('archive',SCRIPTS/'fetch_commons.py','get','--project',self.folder)
        else:
            self.step('credits',SCRIPTS/'fetch_commons.py','credits','--project',self.folder)
        if self.config['maps']:
            if not (self.folder/'map.json').is_file():
                raise ValueError('Maps enabled but no map.json was created in the plan')
            self.tool('maps','make_map.py')
        self.tool('fonts','get_fonts.py')
        self.tool('assets','prep_assets.py')
        self.tool('timed beats','make_beats.py')
        self.lint()
        timing=read(self.folder/'audio/timing.json')
        if timing['total_duration']>max(20,self.config['duration']*2):
            raise ValueError('Narration is much longer than requested. Shorten the script or increase the planned duration.')
        self.state['actual_duration']=timing['total_duration']
        times=[round((s['start']+s['end'])/2,2) for s in timing['segments']]
        preview_size='720x1280' if int(self.config['size'].split('x')[0]) < int(self.config['size'].split('x')[1]) else '1280x720'
        self.tool('preview','render.py','--probe',','.join(map(str,times)),'--size',preview_size)
        # One contact sheet per camera move plus automatic checks (the skill's self-review list).
        self.step('look review',LOOK_REVIEW,'--project',self.folder,'--size','360x640' if preview_size=='720x1280' else '640x360')
        self.state['look_review']=read(self.folder/'out/look-review.json',{}).get('warnings',[])
        if core_hash!=self.fingerprint(ignore={'photos.json'}):
            raise ValueError('Script, scene or settings changed during preview. Recheck the plan.')
        # Commons adds verified licence/credit metadata to photos.json after downloading.
        self.state['plan_hash']=self.fingerprint()
        self.save('AWAITING_LOOK','look review')

    def render(self, name, seconds=None, audio=None):
        w,h=map(int,self.config['size'].split('x'))
        # The skill drafts at 1280x720 whatever the final size: sharp enough to judge, quick to render.
        # Never larger than the final film: a 640x360 film gets a 640x360 draft.
        size=(('1280x720' if w>=h else '720x1280') if w*h>1280*720 else self.config['size']) if seconds else self.config['size']
        args=['--project',self.folder,'--size',size,'--out',self.folder/'out'/name]
        if seconds:
            args+=['--seconds',seconds]
        if audio:
            args+=['--audio',audio]
        self.step('draft' if seconds else 'final render',HELPERS/'render_serial.py',*args)

    def draft(self):
        self.assert_plan()
        self.render('draft.mp4',min(30,read(self.folder/'audio/timing.json')['total_duration']),
                    'audio/narration.m4a' if self.config['audio'] else None)
        self.verify(self.folder/'out/draft.mp4')
        self.save('AWAITING_DRAFT','draft review')

    def verify(self, path):
        result=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height:format=duration',
                               '-of','json',str(path)],capture_output=True,text=True,check=True)
        data=json.loads(result.stdout)
        if not any(s.get('codec_type')=='video' for s in data.get('streams',[])) or float(data['format']['duration'])<=0:
            raise ValueError('Export validation failed: no playable video')
        if self.config['audio'] and not any(s.get('codec_type')=='audio' for s in data['streams']):
            raise ValueError('Export validation failed: voice audio is missing')
        return data

    def finish(self):
        self.assert_plan()
        audio='audio/narration.m4a' if self.config['audio'] else None
        if self.config['sfx']:
            self.tool('sound cues','render.py','--cues')
            self.tool('sound effects','build_sfx.py')
            if self.config['audio']:
                music=self.config['music']
                if music and not (self.folder/music).is_file():
                    raise ValueError('Place your licensed score at audio/music.mp3 before final export')
                self.tool('sound mix','mix_soundtrack.py',*(['--music',music] if music else []))
                audio='audio/mix.m4a'
            else:
                audio='audio/sfx.wav'
        if self.config['music'] and not self.config['sfx']:
            if not self.config['audio']:
                raise ValueError('Background music currently requires narration enabled')
            if not (self.folder/self.config['music']).is_file():
                raise ValueError('Place your licensed score at audio/music.mp3 before final export')
            self.tool('sound mix','mix_soundtrack.py','--music',self.config['music'],'--sfx','audio/no-effects.wav')
            audio='audio/mix.m4a'
        self.render('final.mp4',audio=audio)
        if self.config['captions']:
            self.step('captions',HELPERS/'bangla_tools.py','captions','--project',self.folder,
                      '--video',self.folder/'out/final.mp4','--out',self.folder/FINAL,
                      '--style',self.config['caption_style'])
        else:
            shutil.copy2(self.folder/'out/final.mp4',self.folder/FINAL)
            self.step('subtitle file',HELPERS/'bangla_tools.py','captions','--project',self.folder)
        report=self.verify(self.folder/FINAL)
        write(self.folder/'out/verification.json',report)
        self.state['artifacts']=[FINAL,'out/captions.srt','credits.md','beats.md','out/verification.json']
        self.save('READY_TO_PUBLISH','complete')

    def run(self, action):
        allowed={'revise':{'FAILED','AWAITING_SCRIPT','AWAITING_LOOK','AWAITING_DRAFT'},'prepare':{'NEW','FAILED','AWAITING_SCRIPT'},'preview':{'AWAITING_SCRIPT'},
                 'draft':{'AWAITING_LOOK'},'finish':{'AWAITING_DRAFT'}}
        if action=='retry':
            if self.state['status']!='FAILED':
                raise ValueError('Only failed stages can be retried')
            action=self.state['failed_action']
            self.state['status']=self.state['resume_status']
        if action not in allowed or self.state['status'] not in allowed[action]:
            raise ValueError(f"Action {action} is not available while {self.state['status']}")
        before=self.state['status']
        try:
            self.state['failed_action']=action;self.state['resume_status']=before
            getattr(self,action)()
            if not self.config['review']:
                while self.state['status'] in WAITING:
                    self.run({'AWAITING_SCRIPT':'preview','AWAITING_LOOK':'draft','AWAITING_DRAFT':'finish'}[self.state['status']])
        except Exception as exc:
            self.save('FAILED',error=str(exc))
            raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder');parser.add_argument('action',choices=['prepare','preview','draft','finish','retry','revise'])
    args=parser.parse_args()
    folder=Path(args.folder).resolve();folder.relative_to(ROOT/'runs'/'local')
    Pipeline(folder).run(args.action)

if __name__=='__main__':
    main()
