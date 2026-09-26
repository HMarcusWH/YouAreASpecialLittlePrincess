# Collection content (T03 draft)

Original Swedish and English prompts and participant guidance for [collection protocol v1](../../docs/privacy/collection-protocol.md). Status: draft pending owner review. The pilot gate is `PENDING`, so none of this may be shown to participants yet.

- `v1/manifest.json`: protocol ID/version, tasks with prompt SHA-256 pins, guidance files, session plan, supported contexts and no-pooling rules.
- `v1/prompts/`: copy and free-writing prompts. Copy passages are inside a `text` fence.
- `v1/guidance/`: capture and author guidance per language.

Editing a prompt or guidance file requires a new version or a reviewed hash update in the manifest. `python tools/validate_consent_protocol.py` fails otherwise.
