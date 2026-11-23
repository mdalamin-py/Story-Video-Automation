"""Windows serial runner for the local cinematic-skill checkout."""
import argparse,pathlib,sys,subprocess
p=argparse.ArgumentParser()
p.add_argument('--project',required=True)
p.add_argument('--size',default='1280x720')
p.add_argument('--seconds',type=float)
p.add_argument('--out',required=True)
p.add_argument('--audio')
a=p.parse_args()
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2] / 'skills/cinematic-film/scripts'))
import render
from engine import Doc
# Keep x264 from allocating a large automatic thread pool on Windows.
_original_encoder_args = render.encoder_args
def _bounded_encoder_args(width, crf):
    args = _original_encoder_args(width, crf)
    return args if '-threads' in args else args + ['-threads', '2']
render.encoder_args = _bounded_encoder_args
project=pathlib.Path(a.project).resolve()
out=pathlib.Path(a.out).resolve(); out.parent.mkdir(parents=True,exist_ok=True)
film=render.load_scene(project).build_film(Doc(project))
end=min(a.seconds,film.duration) if a.seconds else film.duration
video=out.with_name(out.stem+'.video.mp4') if a.audio else out
print(render.worker((str(project),a.size,0,round(end*film.fps),video,20)),flush=True)
if a.audio:
 audio=pathlib.Path(a.audio)
 if not audio.is_absolute(): audio=project/audio
 subprocess.run(['ffmpeg','-y','-v','error','-i',str(video),'-i',str(audio),'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-shortest','-movflags','+faststart',str(out)],check=True)
 video.unlink()
print(out)
