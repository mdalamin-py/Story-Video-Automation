import importlib.util
import json
from pathlib import Path
import sys

import pytest
from backend.cinematic import Pipeline, options, read, write, SCRIPTS

def plan(folder):
    folder.mkdir(parents=True,exist_ok=True)
    write(folder/'script.json',{'title':'A story','takes':[{'take':'one','lines':[{'id':1,'text':'এক কাপ চা','spoken':'এক কাপ চা','hero':'Tea leaves'}]}]})
    (folder/'scene.py').write_text('def build_film(doc): pass',encoding='utf-8')

def pipeline(tmp_path,**settings):
    plan(tmp_path)
    write(tmp_path/'cinematic-options.json',settings)
    return Pipeline(tmp_path,runner=lambda *a:None)

def test_workflow_stops_for_approval_and_rejects_skipped_stages(tmp_path):
    p=pipeline(tmp_path)
    p.run('prepare')
    assert read(tmp_path/'pipeline.json')['status']=='AWAITING_SCRIPT'
    with pytest.raises(ValueError,match='not available'):
        p.run('finish')
    assert p.config['review'] is True

def test_modified_story_invalidates_approval(tmp_path):
    p=pipeline(tmp_path)
    p.run('prepare')
    (tmp_path/'scene.py').write_text('# changed',encoding='utf-8')
    with pytest.raises(ValueError,match='Plan/settings changed'):
        p.run('preview')
    assert read(tmp_path/'pipeline.json')['status']=='FAILED'
    p.run('prepare')
    assert p.state['status']=='AWAITING_SCRIPT'

def test_failed_stage_retry_and_automatic_mode(tmp_path):
    p=pipeline(tmp_path)
    p.run('prepare')
    def failed():
        raise RuntimeError('voice service unavailable')
    p.preview=failed
    with pytest.raises(RuntimeError):
        p.run('preview')
    assert p.state['failed_action']=='preview'
    p.preview=lambda:p.save('AWAITING_LOOK')
    p.run('retry')
    assert p.state['status']=='AWAITING_LOOK'
    q=pipeline(tmp_path/'auto',review=False)
    q.preview=lambda:q.save('AWAITING_LOOK')
    q.draft=lambda:q.save('AWAITING_DRAFT')
    q.finish=lambda:q.save('READY_TO_PUBLISH')
    q.run('prepare')
    assert q.state['status']=='READY_TO_PUBLISH'

def test_invalid_settings_and_duplicate_ids(tmp_path):
    for data in ({'size':'99999x99999'},{'review':'false'},{'extra':1},{'music':'../../secret.mp3'},{'music':'audio/music.mp3','audio':False}):
        with pytest.raises(ValueError):options(data)
    p=pipeline(tmp_path)
    script=read(tmp_path/'script.json')
    script['takes'][0]['lines']*=2
    write(tmp_path/'script.json',script)
    with pytest.raises(ValueError,match='unique'):
        p.validate_plan()

def test_bangla_word_and_beat_timing_advance(tmp_path):
    sys.path.insert(0,str(SCRIPTS))
    spec=importlib.util.spec_from_file_location('cinematic_engine_under_test',SCRIPTS/'engine.py')
    engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
    write(tmp_path/'audio/timing.json',{'total_duration':4,'segments':[{'id':1,'start':1,'end':3,'vo':'সবুজ পাতা থেকে চা'}]})
    doc=engine.Doc(tmp_path)
    assert doc.W(1,'পাতা')>doc.W(1,'সবুজ')
    assert doc.W(1,'চা')>doc.W(1,'পাতা')

def test_portrait_previews_and_archive_metadata_keep_approval_valid(tmp_path):
    p=pipeline(tmp_path,audio=False,archive=True,size='360x640')
    calls=[]
    def runner(script,args):
        calls.append((Path(script).name,args))
        if Path(script).name=='fetch_commons.py' and args[0]=='get':
            write(tmp_path/'photos.json',{'photos':[],'verified_credit':'Public domain'})
    p.runner=runner
    p.run('prepare');p.run('preview')
    assert p.state['status']=='AWAITING_LOOK'
    p.assert_plan()
    probes=next(args for name,args in calls if name=='render.py' and '--probe' in args)
    review=next(args for name,args in calls if name=='review_look.py')
    assert probes[-1]=='720x1280'
    assert review[-1]=='360x640'
    assert [name for name,_ in calls][0]=='check_setup.py'


def test_photo_list_without_photos_key_is_repaired(tmp_path):
    p=pipeline(tmp_path)
    p.runner=lambda script,args: None
    write(tmp_path/'photos.json',{'images':[],'source_note':'all drawn in code'})
    p.run('prepare')
    fixed=read(tmp_path/'photos.json')
    assert fixed['photos']==[] and fixed['source_note']=='all drawn in code'

def test_lint_warnings_reach_the_reviewer_and_the_planner(tmp_path):
    p=pipeline(tmp_path)
    def runner(script,args):
        if Path(script).name=='make_beats.py':
            (tmp_path/'beats.md').write_text('# Beats\n\n| row |\n\n## Lint\n\n- line 1: no hero\n- line 2: digits in the spoken text\n',encoding='utf-8')
    p.runner=runner
    p.run('prepare')
    assert read(tmp_path/'pipeline.json')['lint']==['line 1: no hero','line 2: digits in the spoken text']
    prompts=[]
    p.planner=lambda: prompts.append(list(p.state['lint']))
    p.run('revise')
    assert prompts==[['line 1: no hero','line 2: digits in the spoken text']]


def test_draft_renders_at_most_720p_and_final_at_the_chosen_size(tmp_path):
    # A draft is never larger than the film: a 640x360 film renders a 640x360 draft.
    for size,draft in (('640x360','640x360'),('360x640','360x640'),('1280x720','1280x720'),('3840x2160','1280x720'),('1080x1920','720x1280')):
        p=pipeline(tmp_path/size,audio=False,size=size)
        calls=[]
        p.runner=lambda script,args:calls.append(args)
        p.render('draft.mp4',seconds=10); p.render('final.mp4')
        assert calls[0][calls[0].index('--size')+1]==draft
        assert calls[1][calls[1].index('--size')+1]==size


def test_failed_stage_reports_its_own_output(tmp_path):
    p=pipeline(tmp_path)
    script=tmp_path/'broken.py'
    script.write_text('print("reading scene.py");raise SystemExit("the film has no camera keys")',encoding='utf-8')
    with pytest.raises(RuntimeError,match='no camera keys'):
        p.execute(script,[])
    missing=tmp_path/'check_setup.py'
    missing.write_text('print("  [ok] numpy");print("  [MISSING] ffmpeg  install ffmpeg");raise SystemExit(1)',encoding='utf-8')
    with pytest.raises(RuntimeError,match=r'Setup check failed\. \[MISSING\] ffmpeg'):
        p.execute(missing,[])
    assert 'reading scene.py' in (tmp_path/'production.log').read_text(encoding='utf-8')


def test_edits_during_preview_require_plan_recheck(tmp_path):
    p=pipeline(tmp_path,audio=False)
    def runner(script,args):
        if Path(script).name=='prep_assets.py':
            (tmp_path/'scene.py').write_text('# changed during render',encoding='utf-8')
    p.runner=runner
    p.run('prepare')
    with pytest.raises(ValueError,match='changed during preview'):
        p.run('preview')
    assert p.state['status']=='FAILED'


def test_ffmpeg_is_found_from_env_project_folder_or_path(tmp_path, monkeypatch):
    from backend import cinematic
    exe = '.exe' if sys.platform == 'win32' else ''
    tools = tmp_path/'bin'; tools.mkdir()
    for name in ('ffmpeg', 'ffprobe'):
        (tools/f'{name}{exe}').write_bytes(b'')
    monkeypatch.setenv('FFMPEG_PATH', str(tools/f'ffmpeg{exe}'))
    assert cinematic.ffmpeg_dir() == tools
    (tools/f'ffprobe{exe}').unlink()          # ffprobe is needed too, so this folder no longer counts
    assert cinematic.ffmpeg_dir() != tools


def load_voice_tool():
    spec = importlib.util.spec_from_file_location('voice_tool', Path(__file__).resolve().parents[1]/'tools/windows-bangla/bangla_tools.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class FakeEdge:
    """Stands in for edge_tts: drops the first `failures` requests like the free service sometimes does."""
    class exceptions:
        class NoAudioReceived(Exception):
            pass

    def __init__(self, failures):
        self.calls = 0; self.failures = failures
        edge = self

        class Communicate:
            def __init__(self, text, voice, rate):
                pass

            async def save(self, path):
                edge.calls += 1
                if edge.calls <= edge.failures:
                    raise edge.exceptions.NoAudioReceived('No audio was received.')
                Path(path).write_bytes(b'mp3')
        self.Communicate = Communicate


def test_edge_voice_retries_a_dropped_line(tmp_path, monkeypatch):
    import asyncio
    tool = load_voice_tool()
    real_sleep = asyncio.sleep; monkeypatch.setattr(tool.asyncio, 'sleep', lambda s: real_sleep(0))
    edge = FakeEdge(failures=2)
    asyncio.run(tool.speak(edge, 'Hello', 'en-US-AndrewNeural', '+0%', tmp_path/'a.mp3', 1))
    assert edge.calls == 3 and (tmp_path/'a.mp3').read_bytes() == b'mp3'


def test_edge_voice_gives_a_clear_message_when_it_keeps_failing(tmp_path, monkeypatch):
    import asyncio
    tool = load_voice_tool()
    real_sleep = asyncio.sleep; monkeypatch.setattr(tool.asyncio, 'sleep', lambda s: real_sleep(0))
    with pytest.raises(SystemExit, match='line 7 after 4 tries.*Retry'):
        asyncio.run(tool.speak(FakeEdge(failures=99), 'Hello', 'hi-IN-SwaraNeural', '+0%', tmp_path/'a.mp3', 7))


def test_codex_failures_are_explained_in_plain_words():
    from backend.cinematic import codex_failure
    assert 'not signed in' in codex_failure('working...\nError: Not logged in. Run codex login\n')
    assert 'usage limit' in codex_failure('stream error: 429 Too Many Requests\n')
    assert 'internet' in codex_failure('error sending request for url\n')
    assert 'CODEX_MODEL' in codex_failure("ERROR: The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.\n")
    plain = codex_failure('the plan mentions a sign in screen early on\n' + 'x\n' * 900 + 'panic: something else\n')
    assert plain.startswith('Codex could not write the script') and 'panic: something else' in plain
