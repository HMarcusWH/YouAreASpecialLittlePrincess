# Tools, generators and operator safety

The [generated command inventory](../docs/reference/command-inventory.md) lists tool paths and source descriptions; [command safety](../docs/reference/commands.md) distinguishes read-only, generating, mutating, destructive and protected operations. A script inventory is not permission to run every entry.

Use [generated assets](../docs/reference/generated-assets.md) to find editable sources. Web/native journey scripts, including the packaged Android handoff journey, reset a loopback disposable database only with explicit opt-in. The Android handoff build/verify/journey tools are described in [testing](../docs/development/testing.md#standalone-android-packaged-ui). Provider evidence scripts require protected inputs and their own runbook. Documentation checks never execute arbitrary Markdown code fences.
