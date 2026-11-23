"""Compatibility launcher for the unified Python + Node.js cinematic studio."""
from pathlib import Path
import shutil
import subprocess
import sys

if __name__=='__main__':
    root=Path(__file__).resolve().parent
    node=shutil.which('node')
    if not node:
        sys.exit('Install Node.js 22+ and start studio.cmd.')
    sys.exit(subprocess.call([node,str(root/'studio.mjs')],cwd=root))
