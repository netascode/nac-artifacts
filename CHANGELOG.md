## 0.2.0

- Drop support for Python 3.10
- BREAKING CHANGE: Move project bundles from `.nac/` to `nac/bundles/` (any archive or directory there is a bundle, an archive of an unsupported type is an error), the bundle cache to `nac/bundles/.cache/` and project overrides to `nac/overrides.yaml`; `.nac/` is no longer read
- BREAKING CHANGE: Bundles hold their artifacts at their root instead of in a `nac/` directory

## 0.1.0

- Initial release
