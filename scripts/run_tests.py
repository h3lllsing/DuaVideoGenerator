"""
Test runner for DuaVideoGenerator
Run all unit tests and integration tests
"""

import os
import subprocess
import sys


def run_tests():
    """Run all tests using pytest"""
    print("Running DuaVideoGenerator Tests...")
    print("=" * 50)

    # Change to project root directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)

    # Run pytest
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=900
        )

        print("STDOUT:")
        print(result.stdout)

        if result.stderr:
            print("\nSTDERR:")
            print(result.stderr)

        print("\n" + "=" * 50)
        if result.returncode == 0:
            print("All tests PASSED!")
        else:
            print(f"Some tests FAILED (exit code: {result.returncode})")

        return result.returncode

    except subprocess.TimeoutExpired:
        print("Tests timed out after 900 seconds")
        return 1
    except Exception as e:
        print(f"Error running tests: {e}")
        return 1


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)
