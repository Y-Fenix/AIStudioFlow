#!/usr/bin/env python3
"""Start the local read-only release pipeline for GagaSort.

This entry point intentionally does not invoke Git, Unity, network services or
external issue publication.  Use --output to choose a persistent run folder.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from departments.testing.QA_release_contract import QA_freeze_profile
from departments.testing.QA_release_orchestrator import QA_run_release_pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    project = Path("/Users/yf/Documents/Unity/gagasort")
    sdk = Path("/Users/yf/Documents/Unity/SDK&服务器")
    repositories = {
        "client": str(project),
        "android": str(sdk / "bbsdkunity-android"),
        "ios": str(sdk / "bbsdkunity-ios"),
        "sdkserver": str(sdk / "sdkserver"),
        "gameserver": str(sdk / "server"),
    }
    skills = Path(__file__).resolve().parents[1] / ".agents" / "skills"
    profile = QA_freeze_profile(repositories, skills, allowed_checks=["syntax"])
    output = args.output or (Path(__file__).resolve().parents[1] / "data" / "release-runs" /
                             datetime.now().strftime("%Y%m%d-%H%M%S"))
    report = QA_run_release_pipeline(profile, output, resume=args.resume)
    print(json.dumps({"report_dir": str(output.resolve()), "run_id": report["run_id"],
                      "status": report["status"],
                      "release_verified": report["release_verified"],
                      "risks": report["risks"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
