"""One-time documentation materialization. Removed before the roadmap PR is opened."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
marker = "<!-- roadmap-v2-navigation -->"
notice = """<!-- roadmap-v2-navigation -->
> **Roadmap v2 navigation and scope:** [index](00-index.md) · [task briefs](06-agent-backlog.md) · [machine graph](tasks.json) · [build sequence](20-end-to-end-build-sequence.md).
> This chapter's technical content is retained. Its historical status/scope examples are superseded where explicitly listed in [v2 authority amendments](00-index.md): web, iOS and Android/native payments are main-programme scope; T00 and T26 are historically DONE; T00A is pending follow-up. T26 is reviewed but inactive, not an empty scaffold. Earlier model aliases/prices/API examples are dated research, not approved configuration; see [current source refresh](22-research-and-source-refresh.md). Required release/owner gates are not completed by this documentation.

"""
for name in (
    "01-data-architecture.md", "02-corpus-benchmarks.md", "03-premium-openai.md",
    "04-reports-design.md", "05-release-operations.md", "07-evidence-register.md",
):
    path = root / "docs/roadmap" / name
    content = path.read_text(encoding="utf-8")
    if marker not in content:
        path.write_text(notice + content, encoding="utf-8")
readme = root / "README.md"
content = readme.read_text(encoding="utf-8")
if marker not in content:
    notice = """<!-- roadmap-v2-navigation -->
> **Building the app:** [complete roadmap](ROADMAP.md) · [coding-agent entry](AGENTS.md) · [documentation index](docs/roadmap/00-index.md) · [detailed task briefs](docs/roadmap/06-agent-backlog.md).
> The web/iOS/Android product is planned in the linked roadmap. The library documentation below describes the existing measurement core, not a claim that the full consumer app is already implemented.

"""
    readme.write_text(notice + content, encoding="utf-8")
