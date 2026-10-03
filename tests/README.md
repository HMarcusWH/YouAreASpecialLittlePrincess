# Core and contract test suite

Default pytest discovery targets this directory through `pyproject.toml`. Use the reviewed interpreter/architecture lock and `python -m pytest -q tests`. These checks cover their implemented numerical/contracts/policy/research boundaries, not actual participant or native-device evidence.

PostgreSQL integration lives separately in [tests_app](../tests_app/README.md). Documentation regressions use [tests_docs](../tests_docs/README.md); JavaScript tests use workspace scripts. Read the complete [test matrix](../docs/development/testing.md) and preserve adversarial cases rather than only testing happy paths.
