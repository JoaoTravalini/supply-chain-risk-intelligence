"""Command entrypoint for deterministic investigation-agent evaluations."""

from __future__ import annotations

import sys

from supplychain.agent.evaluation.harness import format_evaluation_summary, run_evaluation_suite


def main() -> int:
    """Run the deterministic evaluation suite and return a process exit code."""

    result = run_evaluation_suite()
    print(format_evaluation_summary(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
