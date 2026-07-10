#!/usr/bin/env python3
"""Standalone HDF5 quality validation – CLI entry point.

Usage:
    python -m astribot_dq.cli /path/to/file.hdf5
    python -m astribot_dq.cli /path/to/directory/
"""

import os
import sys
import traceback

from astribot_dq.validator import HDF5Validator
from astribot_dq.schemas import QualityCheckError
from astribot_dq.logger import g_logger


def validate_single_file(validator: HDF5Validator, file_path: str) -> dict:
    result = {
        "file": file_path,
        "status": "pass",
        "error_type": None,
        "error_summary": None,
    }
    try:
        validator.verify_data(file_path)
        g_logger.info(f"PASS: {file_path}")
    except QualityCheckError as qce:
        result["status"] = "fail"
        result["error_type"] = qce.error_type
        result["error_summary"] = qce.error_summary
        g_logger.error(f"FAIL: {file_path}  [{qce.error_type}] {qce.error_summary}")
    except Exception as e:
        result["status"] = "fail"
        result["error_type"] = type(e).__name__
        result["error_summary"] = str(e)
        g_logger.error(f"FAIL: {file_path}  [{type(e).__name__}] {e}")
        g_logger.debug(traceback.format_exc())
    return result


def validate_directory(validator: HDF5Validator, directory_path: str) -> dict:
    hdf5_files = []
    for root, _dirs, files in os.walk(directory_path):
        for f in files:
            if f.endswith(".h5") or f.endswith(".hdf5"):
                hdf5_files.append(os.path.join(root, f))

    g_logger.info(f"Found {len(hdf5_files)} HDF5 files in {directory_path}")

    results = []
    passed = 0
    failed = 0

    for i, file_path in enumerate(hdf5_files):
        g_logger.info(f"[{i+1}/{len(hdf5_files)}] Validating: {os.path.basename(file_path)}")
        result = validate_single_file(validator, file_path)
        results.append(result)
        if result["status"] == "pass":
            passed += 1
        else:
            failed += 1

    return {"total": len(hdf5_files), "passed": passed, "failed": failed, "results": results}


def print_summary(stats: dict) -> None:
    print()
    print("=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    print(f"  Total files:  {stats['total']}")
    print(f"  Passed:       {stats['passed']}")
    print(f"  Failed:       {stats['failed']}")
    if stats["failed"] > 0:
        print()
        print("  Failed files:")
        for r in stats["results"]:
            if r["status"] == "fail":
                print(f"    - {r['file']}")
                print(f"      [{r['error_type']}] {r['error_summary']}")
    print("=" * 70)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m astribot_dq.cli <file_or_directory>", file=sys.stderr)
        print(file=sys.stderr)
        print("Examples:", file=sys.stderr)
        print("  python -m astribot_dq.cli /data/episodes/episode_001.hdf5", file=sys.stderr)
        print("  python -m astribot_dq.cli /data/episodes/", file=sys.stderr)
        sys.exit(1)

    path = os.path.abspath(sys.argv[1])

    if not os.path.exists(path):
        g_logger.error(f"Path does not exist: {path}")
        sys.exit(1)

    validator = HDF5Validator()
    g_logger.info("Validation config: config/validation_config.yaml")

    fk_url = validator.config.fk_service_url
    g_logger.info(f"FK service URL: {fk_url if fk_url else '(not configured – FK check skipped)'}")

    if os.path.isfile(path):
        result = validate_single_file(validator, path)
        print()
        print("=" * 70)
        print("VALIDATION RESULT")
        print("=" * 70)
        print(f"  File:   {result['file']}")
        print(f"  Status: {result['status'].upper()}")
        if result["status"] == "fail":
            print(f"  Error:  [{result['error_type']}] {result['error_summary']}")
        print("=" * 70)
        if result["status"] == "fail":
            sys.exit(1)
    elif os.path.isdir(path):
        stats = validate_directory(validator, path)
        print_summary(stats)
        if stats["failed"] > 0:
            sys.exit(1)
    else:
        g_logger.error(f"Not a file or directory: {path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
