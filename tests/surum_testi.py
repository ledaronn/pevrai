"""Version identity works with stale editable metadata and frozen resources."""
from importlib.metadata import PackageNotFoundError
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pevrai.baslat import surum
from pevrai import baslat


class VersionIdentity(unittest.TestCase):
    def test_source_version_wins_over_stale_editable_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'pyproject.toml').write_text('[project]\nversion="2.3.4"\n', encoding='utf-8')
            with patch('pevrai.DONMUS', False), patch('pevrai.KAYNAK_KOK', Path(tmp)), \
                 patch('importlib.metadata.version', return_value='1.0.0'):
                self.assertEqual(surum(), '2.3.4')

    def test_frozen_version_uses_bundled_metadata_without_pyproject(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('pevrai.DONMUS', True), patch('pevrai.KAYNAK_KOK', Path(tmp)), \
                 patch('importlib.metadata.version', return_value='2.3.4'):
                self.assertEqual(surum(), '2.3.4')

    def test_installed_package_without_source_pyproject(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('pevrai.DONMUS', False), patch('pevrai.KAYNAK_KOK', Path(tmp)), \
                 patch('importlib.metadata.version', return_value='2.3.4'):
                self.assertEqual(surum(), '2.3.4')

    def test_missing_metadata_is_detectable_by_build_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('pevrai.DONMUS', True), patch('pevrai.KAYNAK_KOK', Path(tmp)), \
                 patch('importlib.metadata.version', side_effect=PackageNotFoundError('pevrai')):
                self.assertEqual(surum(), '(surum bilgisi yok)')


class DiagnosticPrivacy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.tmp.name) / 'ornek'
        self.root.mkdir()
        self.secret = 'synthetic-private-diagnostic-token'
        self.error = f'{self.root}/credentials.json: {self.secret}'
        for name, value in (('PROJE_KOKU', self.root), ('PAKET', self.root/'kod'),
                            ('KAYNAK_KOK', self.root/'kaynak'), ('DONMUS', False)):
            self.stack.enter_context(patch('pevrai.' + name, value))
        self.stack.enter_context(patch.object(baslat, 'surum', return_value='0.1.1'))
        self.stack.enter_context(patch('pevrai.ceviri.dil', return_value='tr'))
        self.keys = self.stack.enter_context(patch('pevrai.anahtar.kaynak', return_value='ortam'))
        self.find = self.stack.enter_context(patch('importlib.util.find_spec', return_value=object()))
        self.ocr = self.stack.enter_context(patch('pevrai.ocr.kullanilamaz_nedeni', return_value=None))
        self.stack.enter_context(patch('pevrai.ocr.diller', return_value=['tr']))

    def test_default_hides_paths_but_preserves_component_and_key_status(self):
        (self.root/'policy.toml').touch()
        text = baslat.tanila()
        self.assertNotIn(str(self.root), text)
        self.assertIn('gizli (paylaşılabilir tanı)', text)
        self.assertRegex(text, r'policy\.toml\s+var')
        self.assertRegex(text, r'MCP \(zorunlu\)\s+var')
        self.assertRegex(text, r'Anahtar gemini\s+: ortam')
        self.assertIn('--tani-ayrintili', text)

    def test_default_hides_exception_text_and_keeps_error_types(self):
        self.keys.side_effect = PermissionError(self.error)
        self.ocr.side_effect = RuntimeError(self.error)
        text = baslat.tanila()
        self.assertNotIn(self.secret, text)
        self.assertNotIn(str(self.root), text)
        self.assertIn('PermissionError', text)
        self.assertIn('RuntimeError', text)

    def test_unexpected_key_source_and_ocr_reason_cannot_leak_secrets(self):
        self.keys.return_value = self.error
        self.ocr.return_value = self.error
        text = baslat.tanila()
        self.assertNotIn(self.secret, text)
        self.assertNotIn(str(self.root), text)
        self.assertIn('bilinmeyen anahtar kaynağı', text)
        self.assertRegex(text, r'OCR\s+yok')

    def test_key_error_for_one_provider_does_not_hide_the_others(self):
        def source(provider):
            if provider == 'gemini':
                raise PermissionError(self.error)
            return 'keyring' if provider == 'openai' else 'ortam'
        self.keys.side_effect = source
        text = baslat.tanila()
        self.assertRegex(text, r'Anahtar gemini\s+: okunamadi \(PermissionError\)')
        self.assertRegex(text, r'Anahtar openai\s+: keyring')
        self.assertRegex(text, r'Anahtar anthropic\s+: ortam')
        self.assertNotIn(self.secret, text)
        self.assertEqual(self.keys.call_count, 3)

    def test_missing_optional_namespace_does_not_stop_diagnostics(self):
        def find(name):
            if name == 'google.genai':
                raise ModuleNotFoundError("No module named 'google'")
            return object()
        self.find.side_effect = find
        text = baslat.tanila()
        self.assertRegex(text, r'Gemini\s+yok')
        self.assertRegex(text, r'Anthropic\s+var')

    def test_missing_spec_and_finder_error_do_not_stop_or_leak(self):
        def find(name):
            if name == 'google.genai':
                raise ValueError('google.__spec__ is None')
            if name == 'keyring':
                raise OSError(self.error)
            return object()
        self.find.side_effect = find
        text = baslat.tanila()
        self.assertRegex(text, r'Gemini\s+yok')
        self.assertIn('hata: OSError', text)
        self.assertNotIn(self.secret, text)
        self.assertRegex(text, r'PDF\s+var')

    def test_detailed_local_output_is_explicit_and_warns(self):
        self.keys.side_effect = PermissionError(self.error)
        self.ocr.return_value = 'synthetic OCR reason'
        text = baslat.tanila(ayrintili=True)
        self.assertIn(f'Veri    : {self.root}', text.splitlines())
        self.assertIn(self.secret, text)
        self.assertIn('synthetic OCR reason', text)
        self.assertIn('yalnızca yerelde kullanın', text)

    def test_entry_point_routes_both_diagnostic_flags_without_gui(self):
        for flag, detailed in (('--tani', False), ('--tani-ayrintili', True)):
            with self.subTest(flag=flag), patch.object(baslat, 'tanila', return_value='diagnostic') as probe, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(baslat.main([flag]), 0)
                probe.assert_called_once_with(ayrintili=detailed)

    def test_build_checks_exact_data_root_in_disposable_detailed_output(self):
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location('build_probe',
            Path(__file__).resolve().parents[1]/'packaging/build.py')
        build = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'path', sys.path.copy()):
            spec.loader.exec_module(build)
        env = {'LOCALAPPDATA': str(self.root)}
        text = ('dondurulmus .exe\nMCP (zorunlu)      var\nHTTP (zorunlu)     var\n'
                f'pencere (zorunlu)  var\nVeri    : {self.root/"Pevrai"}\n')
        results = [SimpleNamespace(returncode=0, stdout='0.1.1\n', stderr=''),
                   SimpleNamespace(returncode=0, stdout=text, stderr='')]
        with patch.object(build, 'surum', return_value='0.1.1'), \
             patch.object(build.subprocess, 'run', side_effect=results) as run, \
             patch.object(build, 'sorgula', return_value=({'id': 1, 'result': {'serverInfo': {}}}, b'')), \
             redirect_stdout(io.StringIO()):
            build._dogrula(env)
        self.assertIn('--tani-ayrintili', run.call_args_list[1].args[0])
        self.assertEqual(run.call_args_list[1].kwargs['env'], env)

    def test_build_rejects_hidden_or_wrong_data_root_before_mcp_probe(self):
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location('build_probe',
            Path(__file__).resolve().parents[1]/'packaging/build.py')
        build = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'path', sys.path.copy()):
            spec.loader.exec_module(build)
        env = {'LOCALAPPDATA': str(self.root)}
        for reported in ('hidden (shareable diagnostics)', str(self.root/'wrong')):
            with self.subTest(reported=reported):
                text = ('dondurulmus .exe\nMCP (zorunlu)      var\nHTTP (zorunlu)     var\n'
                        f'pencere (zorunlu)  var\nVeri    : {reported}\n')
                results = [SimpleNamespace(returncode=0, stdout='0.1.1\n', stderr=''),
                           SimpleNamespace(returncode=0, stdout=text, stderr='')]
                with patch.object(build, 'surum', return_value='0.1.1'), \
                     patch.object(build.subprocess, 'run', side_effect=results), \
                     patch.object(build, 'sorgula') as mcp, redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(SystemExit, 'LOCALAPPDATA'):
                        build._dogrula(env)
                    mcp.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
