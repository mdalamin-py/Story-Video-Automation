"""Compatibility entry point: the studio is now supervised by Node.js."""
import shutil
import subprocess
import sys
from backend.environment import ROOT

def main():
    node=shutil.which('node')
    if not node:
        raise RuntimeError('Install Node.js 22 or newer and reopen the studio.')
    return subprocess.call([node,str(ROOT/'studio.mjs')],cwd=ROOT)

if __name__=='__main__':
    try:
        sys.exit(main())
    except (OSError,RuntimeError) as exc:
        sys.exit(f'Studio startup failed: {exc}')
