"""Read-only lint for department ownership. Does not execute modules or invoke Git.

This checks static references and names, not arbitrary Python/JavaScript behavior.
Trusted repository modules still require review; this is not a security sandbox.
"""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
import re


PREFIXES = {'product': 'PRODUCT_', 'design': 'DESIGN_', 'development': 'DEV_',
            'testing': 'QA_', 'growth': 'GROWTH_'}
PUBLIC_CONTRACTS = {'server.core.integrations'}
ENTRYPOINTS = {'create_adapter', 'execute', 'renderHome', 'renderWorkspace', 'mountHome', 'mountWorkspace'}


def check_tree(root, department=None):
    root = Path(root).resolve()
    selected = [department] if department else PREFIXES
    violations, dependencies = [], {}
    for identity in selected:
        if identity not in PREFIXES:
            raise ValueError('未知部门')
        directory = root / 'departments' / identity
        for file in sorted(directory.rglob('*')):
            if file.suffix not in ('.py', '.js') or '__pycache__' in file.parts:
                continue
            relative = file.relative_to(root).as_posix()
            text = file.read_text(encoding='utf-8')
            imports = []

            def report(rule, line, message):
                violations.append({'rule': rule, 'file': relative, 'line': line, 'message': message})

            def inspect_import(name, line):
                imports.append(name)
                if name == 'sqlite3' or name.startswith('sqlite3.'):
                    report('database', line, '部门代码不得直接访问数据库')
                elif name == 'server' or name.startswith('server.') and name not in PUBLIC_CONTRACTS:
                    report('platform-private', line, '仅可导入公开的 server.core.integrations 契约')
                elif name == 'departments' or name.startswith('departments.') and not (
                        name == 'departments.'+identity or name.startswith('departments.'+identity+'.')):
                    report('cross-department', line, '不得依赖其他部门实现')

            if file.name not in ('adapter.py', 'ui.js', '__init__.py') and not file.stem.startswith(PREFIXES[identity]):
                report('prefix', 1, '本部门新增代码文件使用 '+PREFIXES[identity]+' 前缀')
            if file.suffix == '.py':
                try:
                    tree = ast.parse(text)
                except SyntaxError as error:
                    report('syntax', error.lineno or 1, 'Python 语法错误')
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            inspect_import(name.name, node.lineno)
                    elif isinstance(node, ast.ImportFrom):
                        name = node.module or ''
                        if node.level:
                            package = '.'.join(file.relative_to(root).parts[:-1])
                            try:
                                name = importlib.util.resolve_name('.'*node.level+name, package)
                            except ImportError:
                                report('cross-department', node.lineno, '相对导入超出部门范围')
                                continue
                        inspect_import(name, node.lineno)
                    elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        allowed_entry = not isinstance(node, ast.ClassDef) and node.name in ENTRYPOINTS
                        if not allowed_entry and not node.name.startswith(PREFIXES[identity]) and not (
                                node.name.startswith('__') and node.name.endswith('__')):
                            report('prefix', node.lineno, '本部门类和函数使用 '+PREFIXES[identity]+' 前缀')
            else:
                for match in re.finditer(r'\b(?:from\s*|import\s*\(\s*|import\s*)([\'"])([^\'"]+)\1', text):
                    specifier = match.group(2)
                    imports.append(specifier)
                    if not specifier.startswith(('.', '/')):
                        continue
                    target = (root / specifier.lstrip('/') if specifier.startswith('/') else file.parent / specifier).resolve()
                    line = text.count('\n', 0, match.start())+1
                    if target.is_relative_to(root / 'departments') and not target.is_relative_to(directory):
                        report('cross-department', line, '前端不得导入其他部门模块')
                    elif not target.is_relative_to(directory):
                        report('platform-private', line, '前端不得导入公共壳内部实现；使用 context 和生命周期工具')
                for match in re.finditer(r'\bexport\s+(?:async\s+)?function\s+(\w+)', text):
                    name = match.group(1)
                    if name not in ENTRYPOINTS and not name.startswith(PREFIXES[identity]):
                        report('prefix', text.count('\n', 0, match.start())+1, '本部门 JS 导出函数使用 '+PREFIXES[identity]+' 前缀')
            dependencies[relative] = sorted(set(imports))
    return {'violations': violations, 'dependencies': dependencies}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--department', choices=PREFIXES)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = check_tree(args.root, args.department)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for violation in result['violations']:
            print(f"FAIL: {violation['file']}:{violation['line']}: {violation['message']}")
        print(f"{'FAIL' if result['violations'] else 'PASS'}: {len(result['dependencies'])} 个部门代码文件的静态依赖与命名检查；不代表代码沙箱隔离。")
    return int(bool(result['violations']))


if __name__ == '__main__':
    raise SystemExit(main())
