import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ReleaseCheckTest(unittest.TestCase):
    def test_checker_works_inside_pi_installation_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / '.pi/agent/git/example/outlook-agent-skill'
            target.mkdir(parents=True)
            names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).decode().split('\0')
            for name in filter(None, names):
                source = ROOT / name
                if source.is_file():
                    dest = target / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, dest)
            subprocess.run(['git', 'init', '-q', str(target)], check=True, capture_output=True)
            result = subprocess.run([sys.executable, str(target / 'scripts/check_release.py')], cwd=target,
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Release checks passed', result.stdout)

    def test_checker_reads_non_ascii_docs_with_explicit_utf8(self):
        spec = importlib.util.spec_from_file_location('release_check', ROOT / 'scripts/check_release.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_read_text = Path.read_text
        # Simulate Windows' legacy default at the filesystem seam, not our own functions.
        def windows_default(path, *args, **kwargs):
            if not args and kwargs.get('encoding') is None:
                kwargs['encoding'] = 'cp1252'
            return real_read_text(path, *args, **kwargs)
        with patch.object(Path, 'read_text', windows_default), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(), 0)


if __name__ == '__main__':
    unittest.main()
