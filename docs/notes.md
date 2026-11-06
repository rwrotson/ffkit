# Notes

## Build Backend

`uv_build` loads the `ffkit` package from `src/`:

```toml
[tool.uv.build-backend]
module-name = "ffkit"
module-root = "src"
```

The wheel includes `py.typed`, so type checkers use the package's inline annotations.

## structlog Integration

`ffkit.utils.log.setup_logging()` connects [structlog](https://www.structlog.org/) to stdlib logging through `ProcessorFormatter`:

- Library modules use stdlib loggers; their records and structlog events share the same handlers.
- Console logs use colourised `ConsoleRenderer` output or JSON when `FFKIT_LOG__FORMAT=json`.
- File logs use JSON and are written only when `FFKIT_LOG__DIR` is set.
- Timestamps are ISO 8601 in UTC.
- `structlog.contextvars.bind_contextvars()` adds fields to subsequent logs in the current context.

The library never calls `setup_logging()` itself. An application that already configures logging or structlog should skip it.

## Documentation Toolchain

The site is built with [ProperDocs](https://properdocs.org/), a maintained continuation of MkDocs 1.x that reads the same configuration (`properdocs.yml`) and runs MkDocs themes and plugins unchanged. MkDocs 2.0 drops the plugin and theme system, and Material for MkDocs requires `mkdocs<2`, so the `mkdocs` package stays on 1.x as a library dependency of the plugins. Running `properdocs` instead of `mkdocs` also avoids the MkDocs 2.0 warnings printed by Material and the plugins.

[Zensical](https://zensical.org/), the successor to Material for MkDocs, does not support `mkdocs-gen-files` yet; the API reference and configuration pages depend on it.

## Commitizen & Versioning

[Commitizen](https://commitizen-tools.github.io/commitizen/) reads Conventional Commit messages to select the next version and update `CHANGELOG.md`. Its settings are in `pyproject.toml`:

```toml
version_provider = "uv"
update_changelog_on_bump = true
major_version_zero = true
```

The `commit-msg` hook checks Conventional Commit format.

## Releases

The release workflow runs CI, builds the distribution, and deploys documentation for version tags. Manual runs also build the package and deploy documentation. The build job remains available if package registry publishing is added later.

Install a tagged version from GitHub. GitHub Pages uses the `github-pages` environment and GitHub Actions as its source.
