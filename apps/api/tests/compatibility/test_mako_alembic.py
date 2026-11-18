"""Ordinary template compatibility; vulnerability reproduction is out of scope."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from mako.lookup import TemplateLookup
from mako.template import Template


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_template_filename_renders_from_directory_with_spaces(tmp_path: Path, separator: str) -> None:
    root = tmp_path / "ordinary templates"
    root.mkdir()
    source = root / "greeting.mako"
    source.write_text("Hello ${name}!", encoding="utf-8")
    if separator == "\\" and source.drive == "":
        pytest.skip("Native Windows filename syntax requires Windows")
    filename = str(source).replace("\\", "/").replace("/", separator)
    assert Template(filename=filename).render(name="Portal") == "Hello Portal!"


def test_lookup_renders_in_directory_template_and_include(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    root.mkdir()
    (root / "greeting.mako").write_text('Hello <%include file="name.mako"/>!', encoding="utf-8")
    (root / "name.mako").write_text("${name}", encoding="utf-8")
    lookup = TemplateLookup(directories=[str(root)])
    assert lookup.get_template("greeting.mako").render(name="Portal") == "Hello Portal!"


def test_alembic_generates_valid_revision_with_installed_generic_template(tmp_path: Path) -> None:
    config = Config(str(tmp_path / "alembic.ini"))
    environment = tmp_path / "ordinary migration environment"
    command.init(config, str(environment), template="generic")
    revision = command.revision(config, message="ordinary template compatibility", rev_id="741compat")
    assert revision is not None
    generated = Path(revision.path).read_text(encoding="utf-8")
    tree = ast.parse(generated)
    compile(tree, revision.path, "exec")
    assert ast.get_docstring(tree).startswith("ordinary template compatibility")
    assert revision.revision == "741compat"
    assert revision.down_revision is None
    assert revision.module.revision == "741compat"
    assert revision.module.down_revision is None
    assert revision.module.upgrade() is None
    assert revision.module.downgrade() is None
