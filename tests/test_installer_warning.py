"""What the uninstaller may and may not do about a licence.

Deleting the user data folder destroys the installation identity a Pro licence
is bound to, which does not free the activation slot — it makes it
unreclaimable. So the removal is worth a warning.

It cannot be more than a warning, and two separate limits say so.

It cannot run LumaBLE to do the work: ExecAsOriginalUser is documented as not
supported at uninstall time. A previous version of this script called it anyway,
and the tests then in place compared a command-line switch between two files and
found the two files agreeing about something that was never going to happen.

It cannot even tell whether a licence is active, because it runs elevated and
the user profile it can see is the administrator's rather than the one holding
the settings — which is the same reason the first point is true.

Read out of the Pascal with comments stripped. A test that reads a comment as
code can be satisfied by writing about the thing it forbids, which is how two
earlier versions of these passed.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "installer" / "LumaBLE.iss"


def _source() -> str:
    return INSTALLER.read_text(encoding="utf-8", errors="ignore")


def _code_without_comments() -> str:
    """The [Code] section with every brace comment removed, nesting included."""
    pascal = _source()
    pascal = pascal[pascal.index("[Code]") :]
    out: list[str] = []
    depth = 0
    for character in pascal:
        if character == "{":
            depth += 1
        elif character == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(character)
    return "".join(out)


def test_the_comment_stripper_actually_strips() -> None:
    """The instrument the rest of this page depends on. Checked directly,
    because the first version of it dropped only lines beginning with a brace
    and left the body of every multi-line comment in place."""
    stripped = _code_without_comments()

    assert "Result := RemoveUserData" in stripped, "it removed the code as well"
    assert "unreclaimable" not in stripped, "prose from a comment survived"


def test_the_uninstaller_does_not_try_to_run_anything() -> None:
    """ExecAsOriginalUser does not work at uninstall time, and an uninstaller
    that started the application elevated would be worse than one that did
    nothing: it would write somebody's settings as the administrator."""
    body = _code_without_comments()

    assert "ExecAsOriginalUser" not in body
    assert "Exec(" not in body
    assert "ShellExec" not in body
    assert "--prepare-uninstall" not in body


def test_it_warns_before_taking_the_identity_away() -> None:
    """The one honest thing available: say what is at stake, worded as a
    condition because it genuinely does not know, and let the person go and do
    it inside the application."""
    body = _code_without_comments()

    shown = [line for line in body.splitlines() if "LicenceBeforeRemoval" in line]
    assert shown, "nothing in the code shows the warning"

    # Stopping is the default, so somebody not reading closely does not lose a
    # purchase to a keypress. Asked of that call rather than of the file, where
    # the other prompt supplies the same flag.
    call = "\n".join(body[body.index(shown[0]) :].splitlines()[:3])
    assert "MB_DEFBUTTON2" in call, "the default answer on the warning is not the safe one"


def test_the_warning_is_only_asked_when_the_data_is_going() -> None:
    """Keeping the data keeps the identity, so a licence survives a reinstall
    and there is nothing at stake. Asking anyway would train people to click
    through it."""
    body = _code_without_comments()
    guard = body.index("if not RemoveUserData then")
    warning = body.index("LicenceBeforeRemoval")

    assert guard < warning, "the warning is shown even when nothing is being deleted"


def test_silent_uninstall_preserves_data_without_showing_a_dialog() -> None:
    """Automation cannot answer our custom prompts. A silent uninstall must
    therefore take the reversible choice and leave the installation identity
    and licence state in place."""
    body = _code_without_comments()
    silent = body.index("if UninstallSilent then")
    prompt = body.index("RemoveUserDataPrompt")
    branch = body[silent:prompt]

    assert silent < prompt, "the data prompt is reached before silent mode is handled"
    assert "RemoveUserData := False" in branch
    assert "Result := True" in branch
    assert "Exit" in branch


def test_the_warning_exists_in_both_languages_the_installer_speaks() -> None:
    """A missing CustomMessage raises at runtime rather than falling back to
    English, so a half-translated warning is a broken uninstaller."""
    source = _source()

    for language in ("english", "russian"):
        name = language + ".LicenceBeforeRemoval="
        assert name in source, f"{language} has no warning text"
        text = source.split(name, 1)[1].splitlines()[0]
        assert len(text) > 80, f"{language} warning says too little to be a warning"
