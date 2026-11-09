"""Run every test file in pipeline/ (test_*.py) and say which passed.

    python pipeline/run_tests.py
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    failed = []
    for test in sorted(HERE.glob("test_*.py")):
        r = subprocess.run([sys.executable, str(test)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(f"{'ok  ' if r.returncode == 0 else 'FAIL'}  {test.name}")
        if r.returncode != 0:
            failed.append(test.name)
            print((r.stdout + r.stderr)[-1500:])
    print(f"\n{'ALL PASSED' if not failed else 'FAILED: ' + ', '.join(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
