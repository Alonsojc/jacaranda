"""CI must reject omitted tests, duplicate execution, and incomplete results."""

import json

import pytest

from scripts.ci_test_shards import partition, verify_reports


def test_partition_preserves_parametrized_tests_and_file_isolation():
    items = [("a.py", "a.py::test[x]", 9), ("a.py", "a.py::test[y]", 9),
             ("b.py", "b.py::test", 1), ("c.py", "c.py::test", 8)]
    groups = partition(items, 2)
    assert sorted(node for group in groups for node in group) == sorted(row[1] for row in items)
    assert any({"a.py::test[x]", "a.py::test[y]"} <= set(group) for group in groups)
    assert list(map(set, partition(list(reversed(items)), 2))) == list(map(set, groups))


@pytest.mark.parametrize("defect", [None, "missing", "duplicate", "omitted", "collection", "failed"])
def test_report_verification_fails_closed(tmp_path, defect):
    reports = [
        {"shard": i, "total": 2, "collected": ["a", "b"], "selected": [node], "exitstatus": 0}
        for i, node in enumerate(["a", "b"], 1)
    ]
    if defect == "missing":
        reports.pop()
    elif defect == "duplicate":
        reports[1]["selected"] = ["a", "b"]
    elif defect == "omitted":
        reports[1]["selected"] = ["a"]
    elif defect == "collection":
        reports[1]["collected"] = ["a", "b", "c"]
    elif defect == "failed":
        reports[1]["exitstatus"] = 1
    paths = []
    for index, report in enumerate(reports):
        path = tmp_path / f"{index}.json"
        path.write_text(json.dumps(report))
        paths.append(path)
    if defect:
        with pytest.raises(ValueError):
            verify_reports(paths, 2)
    else:
        assert verify_reports(paths, 2) == 2
