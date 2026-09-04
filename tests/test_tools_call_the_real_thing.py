"""The scripts in tools/ are called by hand, so nothing else notices them rotting.

`tools/test_license_activation.py` went on calling `activate_license_key(key,
settings)` for a whole release after the function grew a required
`installation_hash`. Nothing failed, because nothing ran it: it is a manual tool
that wants a real licence key and writes to the real settings file, which is
exactly why no test may execute it.

So it is read instead. Every call to something the script imports out of `app`
is bound against the real signature, without calling anything — which is enough
to catch an argument that no longer exists, one that is now required, or one
that stopped being positional.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _scripts() -> list[Path]:
    return sorted(path for path in TOOLS.glob("*.py") if not path.name.startswith("_"))


def _imported_from_app(tree: ast.Module) -> dict[str, str]:
    """Name as the script uses it -> the module it came out of."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
            for alias in node.names:
                found[alias.asname or alias.name] = node.module
    return found


class _Anything:
    """Stands in for an argument whose value cannot be known from source."""


def _bind(function, call: ast.Call) -> None:
    positional = [_Anything() for arg in call.args if not isinstance(arg, ast.Starred)]
    keywords = {kw.arg: _Anything() for kw in call.keywords if kw.arg is not None}
    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(
        kw.arg is None for kw in call.keywords
    ):
        # Unpacking hides the shape, so there is nothing here to check.
        return
    inspect.signature(function).bind(*positional, **keywords)


def _check(tree: ast.Module, name: str) -> tuple[list[str], int]:
    """Bind every call to something imported out of app.

    Returns the complaints and how many calls were looked at, rather than
    failing outright, so this can be pointed at a deliberately broken script to
    show that it does catch anything. A checker nothing has ever seen fail is a
    checker nobody knows works.
    """
    origins = _imported_from_app(tree)
    problems: list[str] = []
    checked = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        module_name = origins.get(node.func.id)
        if module_name is None:
            continue
        target = getattr(importlib.import_module(module_name), node.func.id, None)
        if not callable(target) or isinstance(target, type):
            continue
        try:
            _bind(target, node)
        except TypeError as mismatch:
            problems.append(
                f"{name}:{node.lineno} calls {node.func.id}() in a way it no longer "
                f"accepts: {mismatch}"
            )
        checked += 1
    return problems, checked


@pytest.mark.parametrize("script", _scripts(), ids=lambda path: path.name)
def test_a_tool_still_calls_the_functions_it_imports(script: Path) -> None:
    # Zero calls is a fine answer here: some tools import nothing out of app.
    # The test that the checking works at all is below, on one that does.
    problems, _ = _check(ast.parse(script.read_text(encoding="utf-8")), script.name)

    assert not problems, str(problems)


def test_the_activation_tool_is_actually_being_checked() -> None:
    """The one that broke, and the one this page exists for. If the count ever
    falls to zero the parametrised test above passes by looking at nothing."""
    source = (TOOLS / "test_license_activation.py").read_text(encoding="utf-8")

    _, checked = _check(ast.parse(source), "test_license_activation.py")

    assert checked >= 5


def test_a_call_that_no_longer_fits_is_caught() -> None:
    """The exact breakage this was written after: two positional arguments to a
    function whose third is required and keyword-only. Checked by running the
    checker over it, so the machinery is proven rather than assumed."""
    broken = ast.parse(
        "\n".join(
            [
                "from app.license import activate_license_key",
                "activate_license_key(key, settings)",
            ]
        )
    )

    problems, checked = _check(broken, "pretend.py")

    assert checked == 1
    assert len(problems) == 1
    assert "installation_hash" in problems[0]


def test_the_activation_tool_asks_for_a_receipt_and_not_only_an_activation() -> None:
    """Activation stopped being enough in 0.4.2: a key buys an instance, and Pro
    comes from a signed receipt about it. A tool that stops after activating
    would report success on a machine where Pro is still off."""
    source = (TOOLS / "test_license_activation.py").read_text(encoding="utf-8")

    assert "obtain_receipt" in source
    assert "installation_hash" in source


def test_the_key_is_never_printed() -> None:
    """It is read with getpass so it does not appear on screen, and it must not
    reappear in anything the tool writes out."""
    source = (TOOLS / "test_license_activation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            printed = ast.dump(node)
            assert "'key'" not in printed, f"line {node.lineno} prints the licence key"
