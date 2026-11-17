#!/usr/bin/env python3
"""Build an isolated memory-match Android APK from an explicit JSON spec."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from departments.development.DEV_game_builder import DEV_build_game


def DEV_main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, help='memory_match JSON spec path')
    parser.add_argument('--output', required=True, help='new empty isolated output directory')
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text())
    result = DEV_build_game(args.output, spec, progress=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    DEV_main()
