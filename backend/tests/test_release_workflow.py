"""The release and CI workflows keep their promises (.github/workflows).

They cannot be run from the tests, so this checks what must hold in the files: nothing is published before the
Windows package has been installed, started, updated and removed; a pre-release is marked as one; no macOS or Linux
job can stop a Windows release; secrets only reach the step that uses them; and expensive jobs stay off pull requests.
"""

from __future__ import annotations

import re

from emneklar.config import REPO_DIR
from tests.script_loader import load_script

WORKFLOWS = REPO_DIR / ".github" / "workflows"
RELEASE = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
CI = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def job(text: str, name: str) -> str:
    """The text of one job (from its key at two spaces of indentation to the next job)."""
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, f"job {name} not found"
    return match.group(1)


def jobs(text: str) -> list[str]:
    return re.findall(r"^  ([A-Za-z0-9_-]+):\n", text.split("\njobs:\n", 1)[1], re.MULTILINE)


def test_nothing_is_published_before_the_windows_package_is_verified() -> None:
    windows = job(RELEASE, "windows")
    order = [windows.index(step) for step in (
        "The tag must match VERSION",
        "scripts/build_runtime.py build",
        "scripts/package_release.py",
        "scripts/build_installer.py",
        "scripts/verify_windows_installer.py",
        "scripts/local_update_test.py",
        "--break-new-version",
        "gh release create",
    )]
    assert order == sorted(order), "build → verify (install, update, rollback) → publish"
    assert RELEASE.count("gh release create") == 1 and "gh release upload" not in RELEASE
    assert "--verify-tag" in windows


def test_the_release_has_one_version_number_and_marks_pre_releases() -> None:
    windows = job(RELEASE, "windows")
    assert 'if [ "$GITHUB_REF_NAME" != "v$version" ]' in windows, "the tag is VERSION – nothing else names the version"
    for name in ("EmneKlar-$VERSION-setup.exe", "EmneKlar-$VERSION-setup.exe.sha256", "EmneKlar-$VERSION.zip",
                 "EmneKlar-$VERSION.zip.sha256", '"$RUNTIME" "$RUNTIME.sha256"'):
        assert name in windows, name
    assert 'case "$VERSION" in *-*) prerelease="--prerelease" ;; esac' in windows
    assert re.search(r"on:\n  push:\n    tags: \[\"v\*\"\]", RELEASE)


def test_only_windows_is_built_and_no_other_platform_can_stop_the_release() -> None:
    assert jobs(RELEASE) == ["windows"], "one job: there is no macOS or Linux package to wait for"
    assert "needs:" not in RELEASE
    assert "runs-on: windows-latest" in job(RELEASE, "windows")
    smoke = job(CI, "platform-smoke")
    assert "continue-on-error: true" in smoke and "github.event_name != 'pull_request'" in smoke
    assert "os: [ubuntu-latest, macos-latest, macos-15-intel]" in smoke
    assert "not a supported platform" in smoke
    for name in jobs(CI):
        assert "platform-smoke" not in re.findall(r"needs: *(.*)", job(CI, name)), name


def test_secrets_only_reach_the_step_that_uses_them_and_are_never_echoed() -> None:
    used = set(re.findall(r"\$\{\{ secrets\.([A-Z_]+) \}\}", RELEASE))
    assert used == {"WINDOWS_SIGN_COMMAND", "RELEASE_SIGNING_KEY"}
    assert "secrets." not in CI, "pull requests and main builds use no secret"
    for name in used:
        assert RELEASE.count(f"{name}: ${{{{ secrets.{name} }}}}") == 1, "passed through the environment of one step"
        assert not re.search(rf"echo[^\n]*\${name}", RELEASE), "never printed"
        assert f"${{{{ secrets.{name} }}}}" not in "\n".join(
            line for line in RELEASE.splitlines() if line.strip().startswith(("run:", "python", "gh ", "echo")))
    assert "set -x" not in RELEASE and "set -x" not in CI
    assert "--key-env RELEASE_SIGNING_KEY" in RELEASE, "the key is read from the environment, never from the command line"
    # Without the secrets the release is still made – unsigned, and it says so.
    assert RELEASE.count("::notice::") == 2 and 'if [ -n "$RELEASE_SIGNING_KEY" ]' in RELEASE
    assert "permissions:\n  contents: write" in RELEASE and "permissions:\n  contents: read" in CI


def test_expensive_jobs_stay_off_pull_requests() -> None:
    for name in ("e2e", "windows-package", "windows-install", "platform-smoke"):
        assert "if: github.event_name != 'pull_request'" in job(CI, name), name
    backend = job(CI, "backend")
    assert """github.event_name == 'pull_request'
        && '{"os":["ubuntu-latest"],"python":["3.13"]}'""" in backend, "a pull request: one Linux job"
    assert "macos" not in backend


def test_the_windows_package_is_built_with_the_python_version_of_the_runtime() -> None:
    build_runtime = load_script("build_runtime")
    series = ".".join(build_runtime.load_spec(REPO_DIR, "win-amd64").python.split(".")[:2])
    assert f'RUNTIME_PYTHON: "{series}"' in CI
    assert f'python-version: "{series}"' in job(RELEASE, "windows")
    assert f'"{series}"' in job(CI, "backend"), "the bundled Python version is in the test matrix"
    package = job(CI, "windows-package")
    for step in ("scripts/build_runtime.py build", "scripts/package_release.py", "scripts/build_installer.py",
                 "scripts/verify_windows_installer.py", "scripts/local_update_test.py", "--break-new-version"):
        assert step in package, step
    assert "pip_audit --requirement packaging/runtime-win-amd64.txt" in CI.replace("\n          ", " ")


def test_the_installer_check_knows_the_same_installations_as_the_installer_script() -> None:
    verify = load_script("verify_windows_installer")
    iss = (REPO_DIR / "packaging" / "windows" / "EmneKlar.iss").read_text(encoding="utf-8-sig")
    normal = re.search(r'#else\s+#define AppName "EmneKlar"\s+#define AppIdValue "\{\{([0-9A-F-]{36})\}"', iss)
    test = re.search(r'#ifdef TestBuild\s+#define AppName "EmneKlar \(test\)"\s+#define AppIdValue "\{\{([0-9A-F-]{36})\}"', iss)
    assert normal and test
    assert {False: f"{{{normal.group(1)}}}_is1", True: f"{{{test.group(1)}}}_is1"} == verify.APP_IDS
