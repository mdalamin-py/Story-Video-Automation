"""Dashboard adapter for the cinematic Python backend."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.cinematic import Pipeline

if __name__ == '__main__':
    from backend.cinematic import ROOT
    folder=Path(sys.argv[1]).resolve()
    folder.relative_to(ROOT/'runs/local')
    Pipeline(folder).run(sys.argv[2] if len(sys.argv)>2 else 'prepare')
