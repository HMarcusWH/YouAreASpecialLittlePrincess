# Documentation pass coverage and unresolved acceptance

The post-#72 documentation audit identified D01–D18. This page maps the implementation work to durable repository guides. It records documentation disposition, not product/gate completion.

| Finding | Documentation change | Remaining external or execution boundary |
|---|---|---|
| D01 stale root/mobile description | Root entry and current-state handover now describe T30A and native-first work | Native provider/device/store qualification still open |
| D02 API ambiguity | Generated current method/path/request inventory plus API semantics; future interfaces separately labelled | AST presence is not full runtime/provider qualification |
| D03 identity contradiction | Infrastructure and capability/environment references distinguish narrow staging verification from app login | T17 live evidence and lifecycle remain open |
| D04 setup gap | Complete source-derived host-specific local recipes and troubleshooting | Independent fresh-machine/recipient run must be recorded, not inferred |
| D05 stale tests | Existing test layers, commands, CI and proof limits documented | App-driving/device/provider/empirical evidence remains separate |
| D06 #72 reconciliation | Baseline, successful run IDs and unavailable Codex review recorded; backlog regenerated | No task or approval status is promoted |
| D07 completion-counter ambiguity | Operator docs explain completed versus remaining and require authoritative closure checks | New bounded pending-state CLI, if needed, is separate T24 implementation |
| D08 charge/credit wording | Payment, grant, reserve, spend, release and refund distinguished | Owner commercial policy remains pending |
| D09 destructive commands | Local reset/role/target/cleanup warnings and safe refusal tests | Live/production operations need their actual owner scope |
| D10 historical research conflict | Current wrapper navigation points to reviewed T26 source | Frozen research is unchanged |
| D11 temporal module comments | In-memory report-store introduction updated without behavior change | Existing fake/provider boundary remains |
| D12 limited doc coverage | Recursive maintained Markdown check and source-generated references with negative controls | No arbitrary fence execution or network validity claim |
| D13 local-data inventory | Signed upload URLs, journal/credential/files/preferences and purge limits documented | Device storage/reinstall behavior still needs real evidence |
| D14 generated-source discoverability | One source/generator/output/check map | No locks or policy hashes regenerated as a shortcut |
| D15 component navigation | Human docs home and component READMEs/index | Existing specialist guides remain authoritative in their scope |
| D16 external design dependency | Exact design hash and safe custody/access register | Durable delivery location and recipient hash check pending |
| D17 rights/reporting handover | Contributing/security guides and retrievable provenance index | No project license, contact SLA or external asset rights invented |
| D18 handover control | Current capability/approval separation and independent acceptance template | Actual access, custodians, devices, provider/store and release approval remain open |

## Scope preservation

The documentation preparation checks that task statuses, hard dependencies and production gates are unchanged; policy/schema/migration/lock/frozen research content is not edited. The current baseline and the fulfilled exact-head CI residual are reconciled separately from frozen witnesses. The only runtime-source edits are explanatory docstring/comment corrections, checked for unchanged Python AST where applicable.

The new maintained workflow has read-only repository permission. Documentation generators use local source/metadata and do not call providers or execute snippets. A temporary preparation branch, if used to produce the update, is not part of the handover PR's file diff.

See [acceptance](acceptance.md) for exact execution/recipient boundaries. A polished document is not an approved account, a passing device test or a finished mobile release.
