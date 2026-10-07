[![Tests](https://github.com/netascode/nac-artifacts/actions/workflows/test.yml/badge.svg)](https://github.com/netascode/nac-artifacts/actions/workflows/test.yml)
![Python Support](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-informational "Python Support: 3.10, 3.11, 3.12, 3.13, 3.14")

# nac-artifacts

A Python library to discover and layer the schema, rules and test artifacts
packaged with Network-as-Code modules and bundles. It is shared by
[`nac-validate`](https://github.com/netascode/nac-validate) and
[`nac-test`](https://github.com/netascode/nac-test).

> **Status:** early development; the API may still change.

## Overview

Schema, validation rules and test templates can come from three places. They
are layered, highest priority first:

1. **Local**: files and paths configured in the project itself
2. **Bundle**: an archive (or directory) dropped into the project, e.g. a
   set of rules and tests
3. **Module**: the `nac/` directory shipped inside the installed Terraform
   module, however the module was sourced (registry, git, archive, local path)

`nac-artifacts` resolves the bundle and module layers. The tools decide how to
merge what they find: for example, `nac-validate` replaces rules by rule ID and
`nac-test` replaces templates by relative path.

## Artifact layout

Modules and bundles use the same layout below their `nac/` directory:

```text
nac/
├── schema.yaml                 # schema for nac-validate
├── rules/                      # semantic validation rules for nac-validate
└── tests/
    ├── templates/              # test templates for nac-test
    ├── jinja_filters/          # Jinja filters for nac-test
    └── jinja_tests/            # Jinja tests for nac-test (optional)
```

## Bundles

A bundle is a `.zip` or `.tar.gz` archive (or an already extracted directory)
with a `manifest.yaml` at its root next to the `nac/` directory. An archive
made by zipping a single folder is accepted as well.

```yaml
# manifest.yaml
name: acme
version: "1.2.0"          # must be a string: quote it, an unquoted 1.10 is read as 1.1
module:                   # optional
  versions: ">=0.3,<0.4"  # PEP 440 specifier
```

- **Compatibility:** if `module.versions` is set, it is checked against the one
  installed module that has a `nac/` directory, whichever artifacts the caller
  asked for. A mismatch raises `BundleError`. The check is skipped, with a log
  message, when no module is installed, several are, or the module's version
  is unknown (local and git sources have none).
- **Location:** any `.zip`, `.tar.gz` or `.tgz` file directly in `.nac/`, or an
  extracted `.nac/bundle/` directory. The file name is free (it can carry a
  version or architecture, such as `acme-nxos-1.2.0.zip`) and is never parsed:
  name and version come from the manifest. If more than one bundle is found the
  library raises an error instead of picking one.
- **Safety:** archives are checked before extraction (no absolute or `..`
  paths, no symlinks or special files, limits on archive size, extracted size
  and file count). Extraction is atomic and cached by the archive's sha256;
  cache contents are trusted without being verified again.
- **Trust:** bundles usually contain code that the tools execute (validation
  rules, Jinja filters), so a bundle needs the same trust as code in your own
  repository.

## Usage

```python
from pathlib import Path

from nac_artifacts import resolve_artifact_layers

layers = resolve_artifact_layers(
    Path.cwd(),
    provides=("schema.yaml", "rules"),  # paths below nac/ this tool needs
)
for layer in layers:  # highest priority first: bundle, then module
    print(layer.origin, layer.version, layer.nac_dir)
```

- A layer is used only if it has at least one of the `provides` paths, so each
  tool picks the layers relevant to it. `provides` must be a non-empty sequence
  of paths relative to `nac/` (a plain string is rejected).
- Modules are found through the `modules.json` that `terraform init` and
  `tofu init` write (honouring `TF_DATA_DIR`). Only the root module and the
  modules it calls directly are considered. If several provide the requested
  paths, `AmbiguousModuleError` lists them; pass `module_dir` to select one.
- Explicit `module_dir` and `bundle` paths are returned as absolute paths.
- Bundles are found in `.nac/`, or pass `bundle`. Archives are
  extracted once into `.nac/cache/`, which ignores itself in git.
- Failures raise `ArtifactError` subclasses (`ModuleDiscoveryError`,
  `AmbiguousModuleError`, `BundleError`).

`nac_artifacts.testing` provides builders for tests of tools that use this
library: installed modules with a `modules.json`, and bundles as zip or tar.gz.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run pre-commit run --all-files
```

## License

MPL-2.0
