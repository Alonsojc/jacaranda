"""Run every collected test once across isolated CI jobs and verify their reports."""

import argparse
import json
from pathlib import Path


def partition(items, total):
    """Keep files together; balance expensive authentication fixtures first."""
    if total < 1:
        raise ValueError("The shard count must be positive")
    files = {}
    for path, nodeid, weight in items:
        files.setdefault(path, []).append((nodeid, weight))
    groups = [[] for _ in range(total)]
    costs = [0] * total
    for _path, tests in sorted(files.items(), key=lambda row: (-sum(t[1] for t in row[1]), row[0])):
        shard = min(range(total), key=lambda index: (costs[index], index))
        groups[shard].extend(nodeid for nodeid, _ in tests)
        costs[shard] += sum(weight for _, weight in tests)
    return groups


def verify_reports(paths, total):
    reports = [json.loads(Path(path).read_text()) for path in paths]
    if len(reports) != total or {r["shard"] for r in reports} != set(range(1, total + 1)):
        raise ValueError("Missing or duplicate shard reports")
    expected = reports[0]["collected"]
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("Empty or duplicate test collection")
    selected = []
    for report in reports:
        if report["total"] != total or report["collected"] != expected:
            raise ValueError("Shards collected different test suites")
        if report["exitstatus"] != 0 or not report["selected"]:
            raise ValueError("A shard failed or selected no tests")
        selected.extend(report["selected"])
    if len(selected) != len(set(selected)) or set(selected) != set(expected):
        raise ValueError("Tests were omitted or executed in multiple shards")
    return len(expected)


def pytest_addoption(parser):
    parser.addoption("--ci-shard", help="1-based shard/count, for example 1/4")
    parser.addoption("--ci-shard-report", help="Write the complete collection and selected node IDs")


def pytest_collection_modifyitems(config, items):
    value = config.getoption("--ci-shard")
    if not value:
        return
    import pytest

    try:
        shard, total = map(int, value.split("/"))
        if not 1 <= shard <= total:
            raise ValueError
    except ValueError as error:
        raise pytest.UsageError("--ci-shard must be in the range 1/count..count/count") from error
    collected = sorted(item.nodeid for item in items)
    if len(collected) != len(set(collected)):
        raise pytest.UsageError("Duplicate collected test IDs")
    weighted = []
    for item in items:
        fixtures = set(item.fixturenames)
        weight = 1 + 8 * ("auth_headers" in fixtures) + 4 * ("admin_user" in fixtures)
        weighted.append((str(item.path), item.nodeid, weight))
    selected = set(partition(weighted, total)[shard - 1])
    if not selected:
        raise pytest.UsageError("The selected shard has no tests")
    deselected = [item for item in items if item.nodeid not in selected]
    items[:] = [item for item in items if item.nodeid in selected]
    config.hook.pytest_deselected(items=deselected)
    config._ci_shard_report = {
        "shard": shard, "total": total, "collected": collected, "selected": sorted(selected),
    }


def pytest_sessionfinish(session, exitstatus):
    path = session.config.getoption("--ci-shard-report")
    report = getattr(session.config, "_ci_shard_report", None)
    if path and report:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({**report, "exitstatus": int(exitstatus)}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--total", type=int, required=True)
    parser.add_argument("reports", nargs="+")
    args = parser.parse_args()
    print(f"Verified {verify_reports(args.reports, args.total)} tests, each assigned exactly once")
