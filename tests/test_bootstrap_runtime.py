import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

path=Path(__file__).resolve().parents[1]/'scripts/bootstrap_runtime.py'
spec=importlib.util.spec_from_file_location('bootstrap_runtime',path)
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)

class BootstrapTests(unittest.TestCase):
    def test_checkpoint_is_verified_before_replacing_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'new.pth';target=root/'old.pth'
            source.write_bytes(b'new');target.write_bytes(b'valid-original')
            with self.assertRaisesRegex(RuntimeError,'SHA-256'):
                runtime.verified_copy(source,target,'incorrect')
            self.assertEqual(target.read_bytes(),b'valid-original')

    def test_zip_reads_only_the_named_checkpoint_without_extracting_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);package=root/'model.zip';data=b'checkpoint'
            with zipfile.ZipFile(package,'w') as z:
                z.writestr('../wav2lip-compatible.pth',data)
                z.writestr('../unwanted.txt','unwanted')
            runtime.verified_copy(package,root/'models/model.pth',hashlib.sha256(data).hexdigest())
            self.assertEqual((root/'models/model.pth').read_bytes(),data)
            self.assertFalse((root/'unwanted.txt').exists())

    def test_zip_with_multiple_checkpoints_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);package=root/'model.zip'
            with zipfile.ZipFile(package,'w') as z:
                z.writestr('a/wav2lip-compatible.pth',b'a');z.writestr('b/wav2lip-compatible.pth',b'b')
            with self.assertRaisesRegex(RuntimeError,'único checkpoint'):
                runtime.verified_copy(package,root/'model.pth','unused')
