# Documentation checker tests

Run `python -m unittest discover -s tests_docs -p 'test_*.py'`. These standard-library tests cover source-derived route inventories, broken links/anchors, missing paths/scripts, narrow frozen exclusions and reset refusal before external commands.

They do not import the application, execute arbitrary Markdown snippets, connect to a database, sign an app or call providers. The [documentation policy](../docs/documentation-policy.md) and read-only workflow describe exact scope.
