import subprocess
import unittest
from unittest.mock import Mock, patch

from ou_dedetai import system


class TestDependencyFailures(unittest.TestCase):
    def test_package_install_failure_is_reported_to_maintenance(self):
        app = Mock()
        app.conf.skip_install_system_dependencies = False
        app.superuser_command = 'sudo'
        manager = Mock(packages='required-package', incompatible_packages='', install=['apt', 'install'], remove=[])
        with patch.object(system, 'get_package_manager', return_value=manager), \
                patch.object(system, 'get_os', return_value=('debian', '12')), \
                patch.object(system, 'query_packages', side_effect=[['required-package'], []]), \
                patch.object(system, 'preinstall_dependencies', return_value=[]), \
                patch.object(system, 'postinstall_dependencies', return_value=[]), \
                patch.object(system, 'run_command', side_effect=subprocess.CalledProcessError(1, 'apt')):
            with self.assertRaisesRegex(RuntimeError, 'dependencies could not be installed'):
                system.install_dependencies(app)
