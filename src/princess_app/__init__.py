"""Product application layer: domain, use cases, connector ports and adapters.

Import directions (enforced by ``tests/test_architecture_boundaries.py``):

* ``princess_app.ports`` and ``princess_app.domain`` import only the standard
  library, ``princess_contracts`` and each other; never an SDK, SQL or HTTP
  framework, and never ``princess_app.adapters``.
* ``princess_app.application`` orchestrates domain objects through ports.
* ``princess_app.adapters`` implement ports; provider SDK imports live only in
  ``princess_app.adapters.<provider>``.

The numerical library ``princess_graphology`` never imports this package.
"""
