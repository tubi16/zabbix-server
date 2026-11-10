from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepare_config as prepare


class ProductionTests(unittest.TestCase):
    def test_new_production_setup_pins_versions_and_binds_management_locally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env.example').write_text((prepare.ROOT / '.env.example').read_text())
            (root / 'env_vars').mkdir()
            with patch.object(prepare, 'ROOT', root), patch('sys.argv', ['prepare', '--production', '--interactive']), patch('builtins.input', side_effect=['alpine-7.4.1', '12.1.0', '8.4.1', '', '', '']):
                prepare.main()
            content = (root / '.env').read_text()
            self.assertIn('ZBX_IMAGE_TAG=alpine-7.4.1', content)
            self.assertIn('ZABBIX_WEB_BIND_IP=127.0.0.1', content)
            self.assertIn('GRAFANA_BIND_IP=127.0.0.1', content)
            self.assertEqual((root / '.env').stat().st_mode & 0o777, 0o600)

    def test_existing_development_config_is_never_silently_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = (prepare.ROOT / '.env.example').read_text()
            (root / '.env.example').write_text(original)
            (root / '.env').write_text(original)
            with patch.object(prepare, 'ROOT', root), patch('sys.argv', ['prepare', '--production']):
                with self.assertRaises(SystemExit):
                    prepare.main()
            self.assertEqual((root / '.env').read_text(), original)
