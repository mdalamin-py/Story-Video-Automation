from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'skills/cinematic-film/scripts'))
engine = pytest.importorskip('engine')  # needs skia-python
import review_look


def film_with_pan():
    film = engine.Film(12, look='studio')
    film.shot(0, 0, 0, 0.5)
    film.shot(3, 0, 0, 0.5)
    film.shot(4, 12000, 0, 0.5)     # a fast pan between 3 s and 4 s
    film.shot(12, 12000, 0, 0.5)
    return film


def test_finds_the_fast_camera_move_and_nothing_else():
    moves = review_look.camera_moves(film_with_pan())
    assert len(moves) == 1
    t0, t1 = moves[0]
    assert 2.0 < t0 < 3.6 and 3.4 < t1 < 5.0


def test_static_camera_has_no_moves_and_no_drift():
    film = engine.Film(6, look='studio')
    film.shot(0, 0, 0, 0.9); film.shot(6, 0, 0, 0.86)
    assert review_look.camera_moves(film) == []
    assert review_look.spotlight_drift(film) == []


def test_spotlight_left_behind_is_reported_but_shot_is_not():
    assert review_look.spotlight_drift(film_with_pan()) == []      # film.shot keeps the light with the camera
    film = engine.Film(12, look='studio')
    film.cam(0, 0, 0, 0.5); film.cam(3, 0, 0, 0.5); film.cam(4, 12000, 0, 0.5); film.cam(12, 12000, 0, 0.5)
    film.focus(0, 0, 0, 1600, 0.55); film.focus(12, 0, 0, 1600, 0.55)   # light never follows
    spans = review_look.spotlight_drift(film)
    assert spans and spans[0][0] < 4.5 and spans[-1][1] > 9   # checked up to the fade-out (12 - 2.2 s)


def test_dark_and_empty_stills_are_flagged_outside_the_fades(tmp_path):
    from PIL import Image
    film = film_with_pan()
    Image.new('L', (64, 36), 8).save(tmp_path / 't0005.00.png')        # flat: empty
    dark = Image.new('L', (64, 36), 10); dark.paste(60, (0, 0, 16, 36)); dark.save(tmp_path / 't0006.00.png')
    Image.new('L', (64, 36), 0).save(tmp_path / 't0000.20.png')        # inside the fade-in: ignored
    good = Image.new('L', (64, 36), 230); good.paste(20, (10, 10, 30, 20)); good.save(tmp_path / 't0007.00.png')
    kinds = {w['t']: w['kind'] for w in review_look.still_checks(tmp_path, film)}
    assert kinds == {5.0: 'empty', 6.0: 'dark'}
