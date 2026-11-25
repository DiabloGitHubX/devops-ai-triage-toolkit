"""Regression tests for evaluation dataset validation."""

import json
from pathlib import Path

import pytest

from agent.eval.runner import (
    MAX_DATASET_BYTES,
    EvaluationRunnerError,
    load_cases,
    validate_case,
)


def valid_case():
    """Return an independent valid dataset case."""

    return {
        "id": "ci-test-failure",
        "category": "ci",
        "description": "Synthetic CI failure.",
        "arguments": ["--ci", "build-1423"],
        "expected_root_cause": "Missing payment validation.",
        "root_cause_groups": [
            ["payment"],
            ["validation"],
        ],
        "evidence_groups": [
            ["201 == 400"],
        ],
        "required_successful_tools": [
            "get_ci_log",
        ],
    }


def write_dataset(
    path: Path,
    cases: list,
    schema_version=1,
) -> Path:
    """Write an isolated test dataset."""

    path.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )

    return path


def test_project_dataset():
    cases = load_cases()

    assert len(cases) == 6

    assert len({case["id"] for case in cases}) == 6

    assert sum(case["category"] == "kubernetes" for case in cases) == 3

    assert sum(case["category"] == "ci" for case in cases) == 3


def test_expected_case_inventory():
    identifiers = {case["id"] for case in load_cases()}

    assert identifiers == {
        "k8s-image-pull",
        "k8s-crash-loop",
        "k8s-pending",
        "ci-test-failure",
        "ci-docker-build",
        "ci-helm-validation",
    }


def test_valid_ci_case():
    validate_case(valid_case())


def test_valid_kubernetes_case():
    case = valid_case()

    case["category"] = "kubernetes"

    case["arguments"] = [
        "--namespace",
        "staging",
        "--pod",
        "payments-api",
    ]

    validate_case(case)


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "../outside",
        "invalid/name",
        "invalid\\name",
        "UPPERCASE",
        "with space",
        ".hidden",
        "a" * 65,
        None,
        123,
        [],
    ],
)
def test_invalid_case_identifiers(identifier):
    case = valid_case()

    case["id"] = identifier

    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


@pytest.mark.parametrize(
    "category",
    [
        "",
        "unknown",
        "production",
        None,
        123,
        [],
    ],
)
def test_invalid_categories(category):
    case = valid_case()

    case["category"] = category

    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


@pytest.mark.parametrize(
    "field",
    [
        "description",
        "expected_root_cause",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        None,
        123,
        [],
    ],
)
def test_invalid_descriptions(field, value):
    case = valid_case()

    case[field] = value

    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


@pytest.mark.parametrize(
    "field",
    [
        "root_cause_groups",
        "evidence_groups",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        [],
        [[]],
        [[""]],
        [["   "]],
        [[123]],
        ["not-a-group"],
    ],
)
def test_invalid_concept_groups(field, value):
    case = valid_case()

    case[field] = value

    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


@pytest.mark.parametrize(
    "tools",
    [
        [],
        None,
        "get_ci_log",
        ["delete_pod"],
        ["get_ci_log", "get_ci_log"],
        [123],
        [[]],
    ],
)
def test_invalid_required_tools(tools):
    case = valid_case()

    case["required_successful_tools"] = tools

    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        None,
        "--ci build-1423",
        ["--ci"],
        ["--ci", "../outside"],
        ["--ci", "build-1423.log"],
        ["--ci", "build;echo"],
        ["--ci", "--help"],
        ["--ci", "build-1423", "--help"],
        ["--ci", ""],
        ["--ci", 123],
    ],
)
def test_invalid_ci_arguments(arguments):
    case = valid_case()

    case["arguments"] = arguments

    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--pod", "payments-api"],
        [
            "--namespace",
            "production",
            "--pod",
            "payments-api",
        ],
        [
            "--namespace",
            "staging",
            "--pod",
            "../outside",
        ],
        [
            "--namespace",
            "staging",
            "--pod",
            "--help",
        ],
        [
            "--namespace",
            "staging",
            "--pod",
            "payments-api",
            "--help",
        ],
    ],
)
def test_invalid_kubernetes_arguments(arguments):
    case = valid_case()

    case["category"] = "kubernetes"

    case["arguments"] = arguments

    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


def test_missing_case_field():
    case = valid_case()

    del case["expected_root_cause"]

    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


def test_unexpected_case_field():
    case = valid_case()

    case["unexpected"] = True

    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


@pytest.mark.parametrize(
    "case",
    [
        None,
        [],
        "invalid",
        123,
    ],
)
def test_invalid_case_type(case):
    with pytest.raises(EvaluationRunnerError):
        validate_case(case)


def test_load_valid_dataset(tmp_path):
    path = write_dataset(
        tmp_path / "cases.json",
        [valid_case()],
    )

    cases = load_cases(path)

    assert len(cases) == 1

    assert cases[0]["id"] == "ci-test-failure"


def test_duplicate_case_identifiers(tmp_path):
    path = write_dataset(
        tmp_path / "cases.json",
        [
            valid_case(),
            valid_case(),
        ],
    )

    with pytest.raises(EvaluationRunnerError):
        load_cases(path)


@pytest.mark.parametrize(
    "version",
    [
        0,
        2,
        "1",
        True,
        None,
    ],
)
def test_unsupported_schema_version(
    tmp_path,
    version,
):
    path = write_dataset(
        tmp_path / "cases.json",
        [valid_case()],
        schema_version=version,
    )

    with pytest.raises(EvaluationRunnerError):
        load_cases(path)


def test_empty_dataset(tmp_path):
    path = write_dataset(
        tmp_path / "cases.json",
        [],
    )

    with pytest.raises(EvaluationRunnerError):
        load_cases(path)


def test_excessive_case_count(tmp_path):
    cases = []

    for index in range(51):
        case = valid_case()

        case["id"] = f"case-{index}"

        cases.append(case)

    path = write_dataset(
        tmp_path / "cases.json",
        cases,
    )

    with pytest.raises(EvaluationRunnerError):
        load_cases(path)


def test_missing_dataset(tmp_path):
    with pytest.raises(EvaluationRunnerError):
        load_cases(tmp_path / "missing.json")


def test_malformed_json(tmp_path):
    path = tmp_path / "cases.json"

    path.write_text(
        "{invalid",
        encoding="utf-8",
    )

    with pytest.raises(EvaluationRunnerError):
        load_cases(path)


def test_invalid_utf8(tmp_path):
    path = tmp_path / "cases.json"

    path.write_bytes(b"\xff\xfe\xff")

    with pytest.raises(EvaluationRunnerError):
        load_cases(path)


def test_oversized_dataset(tmp_path):
    path = tmp_path / "cases.json"

    path.write_bytes(b"x" * (MAX_DATASET_BYTES + 1))

    with pytest.raises(EvaluationRunnerError):
        load_cases(path)
