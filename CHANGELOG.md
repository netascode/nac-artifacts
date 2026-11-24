## 0.3.0

- Add `severity.rules` to `overrides.yaml` to change the severity (`HIGH`, `MEDIUM` or `LOW`) of rules of lower layers, exposed as `Overrides.rule_severities` and `LayerOverrides.rule_severities` (`SeverityEntry`). Peer bundles setting different severities for the same rule are an error unless the project sets it
- Add `override_kinds` to `resolve_artifact_layers()` and `find_bundle_layers()`, so a bundle whose `overrides.yaml` only has entries for another tool is skipped like one without artifacts for the calling tool
- Rename `DisableMatcher` to `EntryMatcher` (it also matches severity entries), `LayerDisables` to `LayerOverrides`, `layer_disables()` to `layer_overrides()` and `disables_by_layer()` to `overrides_by_layer()`; the old names remain as aliases
- Log only the non-zero counts in the summary of an `overrides.yaml`

## 0.2.0

- Drop support for Python 3.10
- BREAKING CHANGE: Move project bundles from `.nac/` to `nac/bundles/` (any archive or directory there is a bundle, an archive of an unsupported type is an error), the bundle cache to `nac/bundles/.cache/` and project overrides to `nac/overrides.yaml`; `.nac/` is no longer read
- BREAKING CHANGE: Bundles hold their artifacts at their root instead of in a `nac/` directory

## 0.1.0

- Initial release
