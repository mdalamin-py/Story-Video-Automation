"""Look review for a cinematic-film project: one contact sheet per camera move, plus automatic checks.

  python -X utf8 tools/review_look.py --project <folder> --size 640x360

The cinematic-film skill asks for `render.py --strip` on every big camera move and a self-review of the
stills before the user sees them. This does both without an agent:

  * finds the camera moves with the engine's own speed test (the one that places whoosh cues)
    and writes out/probe/strip_<t0>_<t1>.jpg for each (at most --max-moves, longest first)
  * spotlight drift: the camera moved on but the spotlight stayed behind (a dark frame)
  * dark or empty frames in the probe stills (out/probe/t*.png), outside the fade in/out

Writes out/look-review.json: {"moves": [[t0, t1], ...], "strips": [...], "warnings": [{"t", "kind", "message"}]}.
Warnings are advice for the reviewer; the script fails only when the scene cannot be rendered.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/cinematic-film/scripts'))

MOVE_START, MOVE_KEEP = 90, 60      # 4K screen px per frame; same thresholds as Film.all_cues' whooshes
DARK_MEAN, EMPTY_STD = 32, 6         # 0-255 luminance


def camera_moves(film, step=1):
    """[(t0, t1)] spans where the camera moves fast, merged when less than half a second apart."""
    fps, n = film.fps, int(film.duration * film.fps)
    moves, i = [], 0
    while i < n:
        if film.screen_speed(i / fps) > MOVE_START:
            j = i
            while j < n and film.screen_speed(j / fps) > MOVE_KEEP:
                j += step
            t0, t1 = max(0.0, i / fps - 0.25), min(film.duration, j / fps + 0.25)
            if moves and t0 - moves[-1][1] < 0.5:
                moves[-1] = (moves[-1][0], t1)
            else:
                moves.append((t0, t1))
            i = j
        i += step
    return [(round(a, 2), round(b, 2)) for a, b in moves]


def spotlight_drift(film, every=0.25):
    """Spans where the spotlight's centre sits outside the frame the camera shows."""
    if not film.focus_keys:
        return []
    spans, t, inside = [], film.fade_in, None
    while t < film.duration - film.fade_out:
        cx, cy, z, _ = film.camera(t)
        fx, fy, radius, strength = film.focus_at(t)
        off = math.hypot(fx - cx, fy - cy) * z          # 4K screen px between frame centre and light
        lost = strength > 0.2 and off > 1920 + radius * z * 0.25
        if lost and inside is None:
            inside = t
        if not lost and inside is not None:
            spans.append((inside, t)); inside = None
        t += every
    if inside is not None:
        spans.append((inside, t))
    return [(round(a, 2), round(b, 2)) for a, b in spans if b - a >= 0.5]


def still_checks(probe_dir, film):
    import numpy as np
    from PIL import Image
    warnings = []
    for p in sorted(probe_dir.glob('t*.png')):
        try:
            t = float(p.stem[1:])
        except ValueError:
            continue
        if t < film.fade_in or t > film.duration - film.fade_out:
            continue
        g = np.asarray(Image.open(p).convert('L'), dtype=np.float32)
        mean, std = float(g.mean()), float(g.std())
        if std < EMPTY_STD:
            warnings.append({'t': t, 'kind': 'empty', 'message': f'The still at {t:.1f}s is almost one flat colour: nothing is on screen.'})
        elif mean < DARK_MEAN:
            warnings.append({'t': t, 'kind': 'dark', 'message': f'The still at {t:.1f}s is very dark (average brightness {mean:.0f}/255). '
                             'Check for dark ink on a dark board or a spotlight left behind.'})
    return warnings


def contact_sheet(renderer, film, t0, t1, n, out):
    from PIL import Image
    frames = [Image.fromarray(renderer.frame(round((t0 + (t1 - t0) * i / max(1, n - 1)) * film.fps))) for i in range(n)]
    cols = 4; rows = (n + cols - 1) // cols
    tw, th = frames[0].width // 2, frames[0].height // 2
    sheet = Image.new('RGB', (cols * tw, rows * th), 'white')
    for i, f in enumerate(frames):
        sheet.paste(f.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    sheet.save(out, quality=85)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', required=True)
    ap.add_argument('--size', default='640x360')
    ap.add_argument('--frames', type=int, default=8)
    ap.add_argument('--max-moves', type=int, default=8)
    a = ap.parse_args()
    proj = Path(a.project).resolve()
    import render
    film, renderer, _ = render.make(proj, a.size)
    pdir = proj / 'out' / 'probe'; pdir.mkdir(parents=True, exist_ok=True)
    for old in pdir.glob('strip_*.jpg'):          # sheets from an earlier plan would mislead the review
        old.unlink()

    moves = camera_moves(film)
    chosen = sorted(sorted(moves, key=lambda m: m[1] - m[0], reverse=True)[:a.max_moves])
    spans = chosen or [(0.0, round(max(0.1, film.duration - 0.1), 2))]   # no big moves: one sheet of the film
    strips = []
    for t0, t1 in spans:
        out = pdir / f'strip_{t0:06.2f}_{t1:06.2f}.jpg'
        contact_sheet(renderer, film, t0, t1, a.frames, out)
        strips.append('out/probe/' + out.name); print(out)

    warnings = [{'t': t0, 'kind': 'spotlight', 'message': f'From {t0:.1f}s to {t1:.1f}s the spotlight is off-frame: the camera moved on '
                 'but the light stayed behind. Use film.shot() so they move together.'} for t0, t1 in spotlight_drift(film)]
    warnings += still_checks(pdir, film)
    if len(moves) > a.max_moves:
        warnings.append({'t': 0, 'kind': 'info', 'message': f'{len(moves)} camera moves found; contact sheets show the {a.max_moves} longest.'})
    report = {'moves': moves, 'strips': strips, 'warnings': sorted(warnings, key=lambda w: w['t'])}
    (proj / 'out' / 'look-review.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"{len(moves)} camera moves, {len(strips)} contact sheets, {len(report['warnings'])} warnings")


if __name__ == '__main__':
    main()
