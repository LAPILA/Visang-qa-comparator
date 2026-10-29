"""Run local-only tests with a writable temporary directory on Windows or CI."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TEMP = ROOT / 'output' / 'tmp'
TEMP.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEMP)

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
