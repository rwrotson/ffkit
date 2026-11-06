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

## Publishing

In a project created from this template, the release workflow publishes version tags to PyPI with [Trusted Publishing](https://docs.pypi.org/trusted-publishers/). On PyPI, add a trusted publisher with the repository owner and name, workflow `release.yml`, and environment `pypi`; for a project that does not exist on PyPI yet, add it as a pending publisher. Create the `pypi` environment in the GitHub repository settings, optionally with required reviewers.

The `publish` job is skipped when the workflow runs in `rwrotson/ffkit`, so release tags of the template deploy documentation only. The condition compares the repository name and needs no change after copying.

## Renaming the Template

Choose three names before editing: a distribution name (for example, `my-package`), an import
package (`my_package`), and an environment prefix (`MY_PACKAGE_`). Check that the distribution
name is free on PyPI.

1. Rename `src/ffkit/` to `src/my_package/`. Replace `ffkit` in imports throughout `src/`,
   `tests/`, and `docs/`, including logger names in tests. Update `module-name` under
   `[tool.uv.build-backend]`, `[tool.coverage.run].source`,
   `[tool.ruff.lint.isort].known-first-party`, and `[tool.importlinter]` in `pyproject.toml`.
2. Set `[project].name`, the description, authors, keywords, and `[project.urls]` in
   `pyproject.toml`. Rename `FFKitError` if the name should match the package.
3. Change `env_prefix` and the `env_fields()` default prefix in
   `src/my_package/config/settings.py`, and `PREFIX` in `docs/gen_config_page.py`. Adjust the
   default log file name in `LogSettings`. Update `.env.example`, README examples, and tests
   using `FFKIT_` variables.
4. Update `properdocs.yml` (`site_name`, repository links, and the source watch path) and
   `docs/gen_ref_pages.py`, which scans the import package for API pages. Update names and
   links in README, docs, `AGENTS.md`, and the PyPI URL in `.github/workflows/release.yml`.
5. Configure the PyPI trusted publisher and GitHub Pages as described above.
6. Regenerate the lockfile with `uv lock`, then run `uv sync --all-groups --locked`,
   `uv run poe check`, `uv build`, and `uv run --group docs properdocs build --strict`.
