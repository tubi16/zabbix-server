import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('wizard', Path(__file__).with_name('setup.py'))
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)


class WizardTests(unittest.TestCase):
    def test_invalid_ip_reprompts(self):
        with patch('builtins.input', side_effect=['invalid', '192.0.2.10']):
            self.assertEqual(wizard.prompt('IP', validator=wizard.ipaddress.ip_address), '192.0.2.10')

    def test_enroll_declined_runs_only_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            (target / 'install.py').touch()
            with patch('builtins.input', side_effect=['pc1', '192.0.2.10', '192.0.2.1', 'user@192.0.2.10', temp]), patch.object(wizard, 'ask', return_value=False), patch.object(wizard, 'run') as run:
                wizard.enroll(target)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[-1], '--plan')

    def test_existing_directory_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'staj-server').mkdir()
            with patch.object(wizard.shutil, 'which', return_value='/usr/bin/git'), patch.object(wizard, 'run') as run:
                with self.assertRaises(SystemExit):
                    wizard.checkout('server', Path(temp), 'arch')
                run.assert_not_called()

    def test_wrong_origin_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'staj-agent' / '.git').mkdir(parents=True)
            with patch.object(wizard.shutil, 'which', return_value='/usr/bin/git'), patch.object(wizard.subprocess, 'check_output', return_value='https://example.org/other.git'), patch.object(wizard, 'run') as run:
                with self.assertRaises(SystemExit):
                    wizard.checkout('agent', Path(temp), 'arch')
                run.assert_not_called()

    def test_invalid_psk_cannot_apply_tls(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / 'key'
            key.write_text('invalid')
            with patch.object(wizard, 'install_agent', return_value='agent2'), patch.object(wizard, 'ask', return_value=True), patch('builtins.input', side_effect=['host', str(key)]), patch.object(wizard, 'run') as run:
                with self.assertRaises(SystemExit):
                    wizard.agent(Path(temp), {'ID': 'arch'})
                run.assert_not_called()

    def test_compose_failure_prevents_start(self):
        def execute(*args, **kwargs):
            if args[:4] == ('docker', 'compose', 'config', '--quiet'):
                raise wizard.subprocess.CalledProcessError(1, args)
        with patch.object(wizard.shutil, 'which', return_value='/usr/bin/docker'), patch.object(wizard.subprocess, 'run') as process, patch.object(wizard, 'run', side_effect=execute) as run, patch.object(wizard, 'ask', return_value=True):
            process.return_value.returncode = 0
            with self.assertRaises(wizard.subprocess.CalledProcessError):
                wizard.server(Path('/tmp/example'), 'arch')
            self.assertFalse(any(call.args[:3] == ('docker', 'compose', 'up') for call in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
