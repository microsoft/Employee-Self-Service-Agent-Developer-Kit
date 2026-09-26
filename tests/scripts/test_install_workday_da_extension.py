# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the PAC-based Workday package installer."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def _result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_parse_profiles_reads_cloud_and_active_marker():
    import install_workday_da_extension as m

    profiles = m._parse_profiles(
        "[1]   user@contoso.com Public\n"
        "[2] * user@contoso.com Preprod https://org.crm10.dynamics.com\n"
    )

    assert profiles == [
        {
            "index": "1",
            "active": False,
            "username": "user@contoso.com",
            "cloud": "Public",
            "environment_url": None,
        },
        {
            "index": "2",
            "active": True,
            "username": "user@contoso.com",
            "cloud": "Preprod",
            "environment_url": "https://org.crm10.dynamics.com",
        },
    ]


def test_runtime_install_uses_preprod_pac_profile_and_application():
    import install_workday_da_extension as m

    calls = []

    def runner(command, *, capture_output, timeout):
        calls.append(([str(part) for part in command], capture_output, timeout))
        if command[1:3] == ["auth", "list"]:
            return _result(
                stdout=(
                    "[1] * user@contoso.com Preprod "
                    "https://org.crm10.dynamics.com\n"
                )
            )
        return _result()

    schema = m.install_workday_package(
        "https://org.crm10.dynamics.com",
        "runtime",
        ring="preprod",
        pac_resolver=lambda: Path("pac.exe"),
        runner=runner,
    )

    assert schema == "msdyn_EssWorkdayRuntime"
    assert calls[-1][0] == [
        "pac.exe",
        "application",
        "install",
        "--environment",
        "https://org.crm10.dynamics.com",
        "--application-name",
        "msdyn_EssWorkdayRuntime",
    ]
    assert calls[-1][1] is False


def test_preprod_auth_uses_environment_anchor_when_profile_is_missing():
    import install_workday_da_extension as m

    calls = []

    def runner(command, *, capture_output, timeout):
        calls.append([str(part) for part in command])
        return _result()

    m.install_workday_package(
        "https://org.crm10.dynamics.com",
        "runtime",
        ring="preprod",
        pac_resolver=lambda: Path("pac.exe"),
        runner=runner,
    )

    assert calls[1] == [
        "pac.exe",
        "auth",
        "create",
        "--cloud",
        "Preprod",
        "--environment",
        "https://org.crm10.dynamics.com",
        "--deviceCode",
    ]


def test_preprod_auth_ignores_active_profile_for_another_environment():
    import install_workday_da_extension as m

    calls = []

    def runner(command, *, capture_output, timeout):
        calls.append([str(part) for part in command])
        if command[1:3] == ["auth", "list"]:
            return _result(
                stdout=(
                    "[1] * user@contoso.com Preprod "
                    "https://other.crm10.dynamics.com\n"
                )
            )
        return _result()

    m.ensure_pac_auth(
        Path("pac.exe"),
        ring="preprod",
        environment_url="https://target.crm10.dynamics.com/",
        runner=runner,
    )

    assert calls[-1] == [
        "pac.exe",
        "auth",
        "create",
        "--cloud",
        "Preprod",
        "--environment",
        "https://target.crm10.dynamics.com/",
        "--deviceCode",
    ]


def test_preprod_auth_selects_exact_environment_profile():
    import install_workday_da_extension as m

    calls = []

    def runner(command, *, capture_output, timeout):
        calls.append([str(part) for part in command])
        if command[1:3] == ["auth", "list"]:
            return _result(
                stdout=(
                    "[1] user@contoso.com Preprod "
                    "https://other.crm10.dynamics.com\n"
                    "[2] user@contoso.com Preprod "
                    "https://target.crm10.dynamics.com/\n"
                )
            )
        return _result()

    m.ensure_pac_auth(
        Path("pac.exe"),
        ring="preprod",
        environment_url="https://target.crm10.dynamics.com",
        runner=runner,
    )

    assert calls[-1] == [
        "pac.exe",
        "auth",
        "select",
        "--index",
        "2",
    ]


def test_selects_single_inactive_profile_for_requested_ring():
    import install_workday_da_extension as m

    calls = []

    def runner(command, *, capture_output, timeout):
        calls.append([str(part) for part in command])
        if command[1:3] == ["auth", "list"]:
            return _result(stdout="[4] user@contoso.com Public\n")
        return _result()

    m.ensure_pac_auth(
        Path("pac.exe"),
        ring="prod",
        environment_url="https://org.crm.dynamics.com",
        runner=runner,
    )

    assert calls[-1] == [
        "pac.exe",
        "auth",
        "select",
        "--index",
        "4",
    ]


def test_preprod_auth_creates_anchored_profile_when_existing_profiles_lack_urls():
    import install_workday_da_extension as m

    calls = []

    def runner(command, *, capture_output, timeout):
        calls.append([str(part) for part in command])
        if command[1:3] != ["auth", "list"]:
            return _result()
        return _result(
            stdout=(
                "[1] user1@contoso.com Preprod\n"
                "[2] user2@contoso.com Preprod\n"
            )
        )

    m.ensure_pac_auth(
        Path("pac.exe"),
        ring="preprod",
        environment_url="https://org.crm10.dynamics.com",
        runner=runner,
    )

    assert calls[-1] == [
        "pac.exe",
        "auth",
        "create",
        "--cloud",
        "Preprod",
        "--environment",
        "https://org.crm10.dynamics.com",
        "--deviceCode",
    ]


def test_rejects_multiple_profiles_for_exact_preprod_environment():
    import install_workday_da_extension as m

    def runner(command, *, capture_output, timeout):
        return _result(
            stdout=(
                "[1] user1@contoso.com Preprod "
                "https://org.crm10.dynamics.com\n"
                "[2] user2@contoso.com Preprod "
                "https://org.crm10.dynamics.com/\n"
            )
        )

    with pytest.raises(m.PacCliError, match="Multiple PAC profiles"):
        m.ensure_pac_auth(
            Path("pac.exe"),
            ring="preprod",
            environment_url="https://org.crm10.dynamics.com",
            runner=runner,
        )


def test_preprod_auth_selects_exact_environment_and_username():
    import install_workday_da_extension as m

    calls = []

    def runner(command, *, capture_output, timeout):
        calls.append([str(part) for part in command])
        if command[1:3] == ["auth", "list"]:
            return _result(
                stdout=(
                    "[1] user1@contoso.com Preprod "
                    "https://org.crm10.dynamics.com\n"
                    "[2] user2@contoso.com Preprod "
                    "https://org.crm10.dynamics.com/\n"
                )
            )
        return _result()

    m.ensure_pac_auth(
        Path("pac.exe"),
        ring="preprod",
        environment_url="https://org.crm10.dynamics.com",
        preferred_username="user2@contoso.com",
        runner=runner,
    )

    assert calls[-1] == [
        "pac.exe",
        "auth",
        "select",
        "--index",
        "2",
    ]


def test_preprod_auth_rejects_wrong_account_after_profile_creation():
    import install_workday_da_extension as m

    auth_lists = iter(
        [
            "",
            (
                "[1] * wrong@contoso.com Preprod "
                "https://org.crm10.dynamics.com\n"
            ),
        ]
    )

    def runner(command, *, capture_output, timeout):
        if command[1:3] == ["auth", "list"]:
            return _result(stdout=next(auth_lists))
        return _result()

    with pytest.raises(m.PacCliError, match="does not match the requested"):
        m.ensure_pac_auth(
            Path("pac.exe"),
            ring="preprod",
            environment_url="https://org.crm10.dynamics.com",
            preferred_username="maker@contoso.com",
            runner=runner,
        )


def test_legacy_da_uses_targeted_appsource_application():
    import install_workday_da_extension as m

    calls = []

    def runner(command, *, capture_output, timeout):
        calls.append([str(part) for part in command])
        if command[1:3] == ["auth", "list"]:
            return _result(stdout="[1] * user@contoso.com Public\n")
        return _result()

    schema = m.install_workday_package(
        "https://org.crm.dynamics.com",
        "legacy-da",
        ring="prod",
        pac_resolver=lambda: Path("pac.exe"),
        runner=runner,
    )

    assert schema == "msdyn_EssDAHRWorkday"
    assert calls[-1][-1] == "msdyn_EssDAHRWorkdayHCM"


def test_surfaces_pac_install_failure():
    import install_workday_da_extension as m

    def runner(command, *, capture_output, timeout):
        if command[1:3] == ["auth", "list"]:
            return _result(stdout="[1] * user@contoso.com Public\n")
        return _result(returncode=1)

    with pytest.raises(m.PacCliError, match="could not install"):
        m.install_workday_package(
            "https://org.crm.dynamics.com",
            "runtime",
            ring="prod",
            pac_resolver=lambda: Path("pac.exe"),
            runner=runner,
        )


def test_rejects_non_https_environment_url():
    import install_workday_da_extension as m

    with pytest.raises(ValueError, match="must use HTTPS"):
        m.install_workday_package(
            "http://org.crm.dynamics.com",
            "runtime",
            ring="prod",
        )


def test_resolve_pac_reports_missing_cli(monkeypatch):
    import install_workday_da_extension as m

    monkeypatch.setattr(m.shutil, "which", lambda _candidate: None)

    with pytest.raises(m.PacCliError, match="PAC CLI is not installed"):
        m.resolve_pac_executable(environ={})
