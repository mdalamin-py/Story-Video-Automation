"""Render a draft or final film for the dashboard with the skill's parallel renderer (render.py).

The name is historical: this used to render on one worker, which left most CPU cores idle.
render.py splits the frames into chunks, renders them on as many workers as fit in memory and
joins the chunks losslessly, then muxes the narration."""
import argparse
import os
import pathlib
import subprocess
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / 'skills/cinematic-film/scripts'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', required=True)
    p.add_argument('--size', default='1280x720')
    p.add_argument('--seconds', type=float, help='render only the first N seconds (drafts)')
    p.add_argument('--out', required=True)
    p.add_argument('--audio')
    p.add_argument('--workers', type=int, default=int(os.environ.get('RENDER_WORKERS', '0') or 0),
                   help='0 = as many as fit in memory (RENDER_WORKERS in .env overrides it)')
    a = p.parse_args()
    project = pathlib.Path(a.project).resolve()
    out = pathlib.Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(SCRIPTS))
    import render
    from engine import Doc
    film = render.load_scene(project).build_film(Doc(project))
    end = min(a.seconds, film.duration) if a.seconds else film.duration
    command = [sys.executable, '-X', 'utf8', str(SCRIPTS / 'render.py'), '--project', str(project), '--size', a.size,
               '--t1', f'{end:.3f}', '--out', str(out), '--crf', '20', '--workers', str(a.workers)]
    if a.audio:
        command += ['--audio', a.audio]
    subprocess.run(command, check=True)
    print(out)


if __name__ == '__main__':
    main()
