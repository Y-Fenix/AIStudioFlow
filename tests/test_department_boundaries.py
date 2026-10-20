import tempfile
import unittest
from pathlib import Path

from tools.check_department_boundaries import check_tree


class DepartmentBoundaryTests(unittest.TestCase):
    def test_current_department_modules_follow_owned_names_and_dependency_rules(self):
        self.assertEqual(check_tree(Path(__file__).resolve().parent.parent)['violations'], [])

    def test_reports_cross_department_private_platform_and_database_imports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            module = root / 'departments/product'
            module.mkdir(parents=True)
            (module / 'adapter.py').write_text(
                'import sqlite3\nfrom server.store import Store\n'
                'from departments.design.adapter import create_adapter\n'
                'class WrongName: pass\n', encoding='utf-8')
            result = check_tree(root, department='product')
            self.assertEqual({v['rule'] for v in result['violations']}, {'database', 'platform-private', 'cross-department', 'prefix'})
            self.assertTrue(all(v['file'] == 'departments/product/adapter.py' and v['line'] > 0 for v in result['violations']))

    def test_public_contract_and_framework_entrypoint_names_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            module = root / 'departments/product'
            module.mkdir(parents=True)
            (module / 'adapter.py').write_text(
                'from server.core.integrations import ExecutionContext\n'
                'class PRODUCT_Adapter:\n'
                '    def execute(self, context): pass\n'
                'def create_adapter(): return PRODUCT_Adapter()\n', encoding='utf-8')
            result = check_tree(root, department='product')
            self.assertEqual(result['violations'], [])
            self.assertIn('server.core.integrations', result['dependencies']['departments/product/adapter.py'])

    def test_frontend_import_cannot_reach_another_department_or_public_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            module = root / 'departments/design'
            module.mkdir(parents=True)
            (module / 'ui.js').write_text(
                'import x from "../product/ui.js";\n'
                'const y = import("../../web/studio.js");\n', encoding='utf-8')
            result = check_tree(root, department='design')
            self.assertEqual({v['rule'] for v in result['violations']}, {'cross-department', 'platform-private'})


if __name__ == '__main__':
    unittest.main()
