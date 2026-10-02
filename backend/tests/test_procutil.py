"""Starting programs from the built program: what a copy that goes on by itself must not inherit."""

from __future__ import annotations

from app.procutil import fresh_start_environment

BOOTLOADER = {
    "_PYI_APPLICATION_HOME_DIR": "C:\\Users\\a\\AppData\\Local\\Temp\\_MEI123456",
    "_PYI_ARCHIVE_FILE": "C:\\Users\\a\\AppData\\Local\\Programs\\CheapTrader\\CheapTrader.exe",
    "_PYI_PARENT_PROCESS_LEVEL": "1",
    "_PYI_SPLASH_IPC": "7",
    "_MEIPASS2": "C:\\Users\\a\\AppData\\Local\\Temp\\_MEI654321",  # an older bootloader's
}
ORDINARY = {"PATH": "C:\\Windows", "TEMP": "C:\\Temp", "CT_PORT": "8765", "SystemRoot": "C:\\Windows"}


def test_a_new_copy_does_not_inherit_what_the_bootloader_left_behind() -> None:
    assert fresh_start_environment({**ORDINARY, **BOOTLOADER}) == ORDINARY


def test_the_names_are_compared_without_regard_to_case() -> None:
    # Windows does not tell the cases apart, so neither does this
    assert fresh_start_environment({**ORDINARY, "_pyi_archive_file": "x", "_meipass2": "y"}) == ORDINARY


def test_the_environment_it_is_given_is_left_as_it_was() -> None:
    env = {**ORDINARY, **BOOTLOADER}
    fresh_start_environment(env)
    assert env == {**ORDINARY, **BOOTLOADER}


def test_without_an_argument_it_is_this_processs_environment(monkeypatch) -> None:
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:\\gone")
    monkeypatch.setenv("CT_SOMETHING_ELSE", "kept")
    fresh = fresh_start_environment()
    assert "_PYI_APPLICATION_HOME_DIR" not in fresh and fresh["CT_SOMETHING_ELSE"] == "kept"
