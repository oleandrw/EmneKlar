"""scripts/sign_release.py: Ed25519 signatures of a release's checksum file, and the key pair for them.

Only TEST keys are used here. No real key exists in the repository, and none is made by a build.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

from emneklar.config import REPO_DIR
from tests import ed25519_testkey as test_key
from tests.script_loader import load_script
from tests.test_update_script import RFC8032_VECTORS

update = load_script("update")
sign_release = load_script("sign_release")

#: RFC 8032 section 7.1: the secret keys of test 1 and test 2, in the order of RFC8032_VECTORS.
RFC_SECRETS = [
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
    "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
]


def checksum_file(folder: Path, version: str = "0.3.0") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"EmneKlar-{version}.zip.sha256"
    path.write_bytes(f"{'ab' * 32}  EmneKlar-{version}.zip\n".encode("ascii"))
    return path


def key_file(folder: Path, secret: bytes = test_key.TEST_SECRET) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "testnokkel.txt"
    path.write_text(sign_release.KEY_PREFIX + secret.hex() + "\n", encoding="ascii")
    return path


def test_signing_matches_the_rfc_test_vectors_and_the_independent_test_signer() -> None:
    assert len(RFC_SECRETS) == len(RFC8032_VECTORS)
    for secret_hex, (public, message, signature) in zip(RFC_SECRETS, RFC8032_VECTORS, strict=True):
        secret = bytes.fromhex(secret_hex)
        assert sign_release.public_key(secret).hex() == public
        assert sign_release.sign(bytes.fromhex(message), secret).hex() == signature
    message = b"en sjekksumfil"
    assert sign_release.sign(message, test_key.TEST_SECRET) == test_key.sign(message)
    assert sign_release.public_key(test_key.TEST_SECRET) == test_key.public_key()


def test_a_signed_checksum_file_is_what_the_updater_accepts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    checksum = checksum_file(tmp_path / "dist-release")
    key = key_file(tmp_path / "utenfor")
    assert sign_release.main(["sign", "--key", str(key), str(checksum)]) == 0
    signature = checksum.with_name(checksum.name + ".sig")
    assert signature.name == "EmneKlar-0.3.0.zip.sha256.sig", "the name update.py looks for in a release"
    text = signature.read_text(encoding="ascii")
    assert len(base64.b64decode(text.strip())) == 64
    public = test_key.public_key().hex()
    assert "gyldig" in update.verify_release_signature(checksum.read_bytes(), text, keys=[public], required=True)
    with pytest.raises(update.UpdateError, match="ugyldig"):
        update.verify_release_signature(checksum.read_bytes() + b" ", text, keys=[public], required=True)

    assert sign_release.main(["public-key", "--key", str(key)]) == 0
    assert sign_release.main(["verify", "--public-key", public, str(checksum)]) == 0
    out = capsys.readouterr().out
    assert public in out and "Signaturen er gyldig" in out
    assert test_key.TEST_SECRET.hex() not in out, "the private key is never printed"
    assert sign_release.main(["verify", "--public-key", "0" * 64, str(checksum)]) == 1


def test_the_key_can_come_from_the_environment_and_is_never_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    checksum = checksum_file(tmp_path)
    monkeypatch.setenv("TEST_SIGNING_KEY", sign_release.KEY_PREFIX + test_key.TEST_SECRET.hex())
    assert sign_release.main(["sign", "--key-env", "TEST_SIGNING_KEY", str(checksum)]) == 0
    assert checksum.with_name(checksum.name + ".sig").is_file()

    monkeypatch.setenv("TEST_SIGNING_KEY", "ikke-en-nokkel-" + "f" * 30)  # a mistake in the secret
    assert sign_release.main(["sign", "--key-env", "TEST_SIGNING_KEY", str(checksum)]) == 1
    monkeypatch.setenv("TEST_SIGNING_KEY", "")
    assert sign_release.main(["sign", "--key-env", "TEST_SIGNING_KEY", str(checksum)]) == 1
    captured = capsys.readouterr()
    assert "ikke vist her" in captured.err and "er tom" in captured.err
    assert "ikke-en-nokkel" not in captured.out + captured.err and test_key.TEST_SECRET.hex() not in captured.out


def test_only_the_checksum_file_of_a_package_is_signed(tmp_path: Path) -> None:
    key = key_file(tmp_path)
    other = tmp_path / "EmneKlar-0.3.0-setup.exe"
    other.write_bytes(b"MZ")
    assert sign_release.main(["sign", "--key", str(key), str(other)]) == 1
    wrong = tmp_path / "EmneKlar-0.3.0.zip.sha256"
    wrong.write_bytes(b"ikke en sjekksum\n")
    assert sign_release.main(["sign", "--key", str(key), str(wrong)]) == 1
    assert not list(tmp_path.glob("*.sig"))


def test_a_new_key_is_written_outside_the_repository_and_never_over_another(tmp_path: Path,
                                                                           capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "trygt-sted" / "utgivelsesnokkel.txt"
    assert sign_release.main(["generate", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    content = out.read_text(encoding="ascii").strip()
    assert re.fullmatch(r"emneklar-release-key:[0-9a-f]{64}", content)
    seed = sign_release.parse_key(content)
    public = sign_release.public_key(seed).hex()
    assert f"Offentlig nøkkel: {public}" in printed
    assert seed.hex() not in printed, "only the public key is shown"
    # The pair works: a file signed with the new key verifies against the public key that was shown.
    checksum = checksum_file(tmp_path)
    assert sign_release.main(["sign", "--key", str(out), str(checksum)]) == 0
    assert sign_release.main(["verify", "--public-key", public, str(checksum)]) == 0

    assert sign_release.main(["generate", "--out", str(out)]) == 1, "an existing key is never overwritten"
    assert out.read_text(encoding="ascii").strip() == content
    inside = REPO_DIR / "packaging" / "ikke-her.txt"
    assert sign_release.main(["generate", "--out", str(inside)]) == 1 and not inside.exists()
    assert "skal ikke ligge i repositoriet" in capsys.readouterr().err


def test_no_key_is_in_the_repository_and_signing_is_not_required_yet() -> None:
    assert update.RELEASE_SIGNING_KEYS == () and update.SIGNATURE_REQUIRED is False
    pattern = re.compile(r"emneklar-release-key:[0-9a-f]{64}")
    for folder in ("scripts", "packaging", ".github", "docs"):
        for path in (REPO_DIR / folder).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".yml", ".md", ".json", ".txt", ".iss"}:
                assert not pattern.search(path.read_text(encoding="utf-8", errors="replace")), path
