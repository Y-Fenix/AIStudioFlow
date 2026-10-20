"""隔离执行既有生产方法探针，证据写入平台目录，不启动 Unity Editor。"""
import argparse
import importlib.util
import json
from pathlib import Path


def run(repository, evidence):
    root = Path(repository).resolve()
    project = root / 'GagaSort'
    script = project / 'Assets/Editor/Tools/TEST/TEST_test-business-automation.py'
    spec = importlib.util.spec_from_file_location('gagasort_business_probe', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = next(line.split(':', 1)[1].strip() for line in
                   (project / 'ProjectSettings/ProjectVersion.txt').read_text().splitlines()
                   if line.startswith('m_EditorVersion:'))
    unity = Path('/Applications/Unity/Hub/Editor') / version / 'Unity.app/Contents/MacOS/Unity'
    directory = Path(evidence).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    rows = module.run_probe(unity, directory)
    for index, row in enumerate(rows):
        row['id'] = 'logic-' + str(index + 1)
    report = {'cases': rows}
    (directory / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    run(args.repository, args.evidence)
