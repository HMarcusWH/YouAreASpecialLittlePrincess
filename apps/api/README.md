# FastAPI application

Factory: `princess_api.compose:app_from_environment`. Routing is `princess_api/app.py`; operator commands are `princess_api/ops.py`. Run with the separately locked Python backend and source paths. HTTP authenticates the principal and invokes application services; it is not an entitlement engine of its own. The notice registry is a required packaged input.

Read [setup](../../docs/development/local-setup.md), [API semantics/routes](../../docs/reference/api.md), [configuration](../../docs/reference/configuration.md) and [operator output semantics](../../docs/reference/commands.md). Tests: `python -m pytest -q tests_app` with disposable PostgreSQL; default core pytest alone is not this suite. Narrow staging identity verification is not production login; non-fake storage/payment composition remains separately gated.
