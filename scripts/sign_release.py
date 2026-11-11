"""Sign the checksum file of a release (Ed25519), and make the key pair for it.

    python scripts/sign_release.py generate --out <fil UTENFOR repositoriet>
    python scripts/sign_release.py public-key (--key FIL | --key-env NAVN)
    python scripts/sign_release.py sign       (--key FIL | --key-env NAVN) dist-release/EmneKlar-<versjon>.zip.sha256
    python scripts/sign_release.py verify --public-key HEX dist-release/EmneKlar-<versjon>.zip.sha256

``scripts/update.py`` can check a signature of ``EmneKlar-<versjon>.zip.sha256``: the file
``EmneKlar-<versjon>.zip.sha256.sig`` (base64, 64 bytes) next to it in the release, verified against the public keys
in ``RELEASE_SIGNING_KEYS``. The checksum file names the package's SHA-256, and the package's install.json names
the runtime's SHA-256 – so one signature covers everything an update installs.

* ``generate`` makes a new key pair. The private key is written to the file you name – never inside this repository,
  never printed – and the public key (hex) is shown: that is what goes into ``RELEASE_SIGNING_KEYS``. Keep the
  private key somewhere safe and give it to the release workflow as the secret ``RELEASE_SIGNING_KEY``.
* ``sign`` writes the ``.sig`` file and checks it with the updater's own verification before it says it is done.
  In the release workflow the key comes from the environment (``--key-env``); it is never written to a log.

No key is stored in the repository, and none is made by the build. Turning signing on is done in steps – see
«Signerte utgivelser» in docs/UPDATING.md (the public key must reach the users in a release *before* signatures are
required, otherwise every update stops).

The signing is the reference algorithm of RFC 8032 in plain Python (no extra package); it is tested against the
RFC's test vectors and against the updater's verification.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import update  # noqa: E402 - the curve arithmetic and the verification the updater itself uses

KEY_PREFIX = "emneklar-release-key:"
KEY_RE = re.compile(r"^(?:emneklar-release-key:)?([0-9a-f]{64})$")


class SigningError(Exception):
    pass


def _compress(point: tuple[int, int, int, int]) -> bytes:
    p = update._ED_P
    zi = pow(point[2], p - 2, p)
    x, y = point[0] * zi % p, point[1] * zi % p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _expand(seed: bytes) -> tuple[int, bytes]:
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def public_key(seed: bytes) -> bytes:
    return _compress(update._ed_mul(_expand(seed)[0], update._ED_BASE))


def sign(message: bytes, seed: bytes) -> bytes:
    """The Ed25519 signature of ``message`` (RFC 8032 section 5.1.6)."""
    order = update._ED_L
    scalar, prefix = _expand(seed)
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % order
    big_r = _compress(update._ed_mul(r, update._ED_BASE))
    k = int.from_bytes(hashlib.sha512(big_r + public_key(seed) + message).digest(), "little") % order
    return big_r + int.to_bytes((r + k * scalar) % order, 32, "little")


def parse_key(text: str) -> bytes:
    match = KEY_RE.match(text.strip().lower())
    if not match:
        raise SigningError("Nøkkelen har ikke det ventede formatet (emneklar-release-key: fulgt av 64 heksadesimale "
                           "tegn). Den er ikke vist her.")
    return bytes.fromhex(match.group(1))


def load_key(args: argparse.Namespace) -> bytes:
    if args.key_env:
        value = os.environ.get(args.key_env, "")
        if not value.strip():
            raise SigningError(f"Miljøvariabelen {args.key_env} er tom – ingen nøkkel å signere med.")
        return parse_key(value)
    try:
        return parse_key(Path(args.key).read_text(encoding="ascii"))
    except OSError as exc:
        raise SigningError(f"Kan ikke lese nøkkelfilen {args.key}: {exc}") from exc


def signature_path(checksum: Path) -> Path:
    return checksum.with_name(checksum.name + update.SIGNATURE_SUFFIX)


def write_signature(checksum: Path, seed: bytes) -> Path:
    """Sign the exact bytes of the checksum file and verify the result the way the updater will."""
    if not checksum.name.endswith(".zip.sha256"):
        raise SigningError(f"{checksum.name} er ikke sjekksumfilen til en utgivelsespakke (EmneKlar-<versjon>.zip.sha256).")
    data = checksum.read_bytes()
    update.parse_checksum(data.decode("utf-8", "replace"), checksum.name.removesuffix(".sha256"))
    text = base64.b64encode(sign(data, seed)).decode("ascii") + "\n"
    update.verify_release_signature(data, text, keys=[public_key(seed).hex()], required=True)
    target = signature_path(checksum)
    target.write_bytes(text.encode("ascii"))
    return target


def generate(out: Path) -> str:
    """Write a new private key to ``out`` and return the public key (hex)."""
    out = out.resolve()
    if ROOT.resolve() == out or ROOT.resolve() in out.parents:
        raise SigningError("Den private nøkkelen skal ikke ligge i repositoriet. Velg en fil utenfor "
                           f"{ROOT} – for eksempel på en minnepinne eller i en passordbehandler.")
    if out.exists():
        raise SigningError(f"{out} finnes allerede. En nøkkel skrives aldri over.")
    seed = secrets.token_bytes(32)
    out.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(handle, "w", encoding="ascii") as file:
        file.write(KEY_PREFIX + seed.hex() + "\n")
    return public_key(seed).hex()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signerer sjekksumfilen til en utgivelse (Ed25519).")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("generate", help="lag et nytt nøkkelpar")
    make.add_argument("--out", type=Path, required=True, help="filen den private nøkkelen skrives til (utenfor repoet)")
    for name, text in (("public-key", "vis den offentlige nøkkelen"), ("sign", "signer en sjekksumfil")):
        sub = commands.add_parser(name, help=text)
        source = sub.add_mutually_exclusive_group(required=True)
        source.add_argument("--key", help="filen med den private nøkkelen")
        source.add_argument("--key-env", metavar="NAVN", help="miljøvariabelen som inneholder den private nøkkelen")
        if name == "sign":
            sub.add_argument("checksum", type=Path, help="EmneKlar-<versjon>.zip.sha256")
    check = commands.add_parser("verify", help="kontroller signaturen ved siden av en sjekksumfil")
    check.add_argument("--public-key", required=True, metavar="HEX", help="den offentlige nøkkelen (64 heks-tegn)")
    check.add_argument("checksum", type=Path, help="EmneKlar-<versjon>.zip.sha256")
    args = parser.parse_args(argv)
    update.configure_stdio()
    try:
        if args.command == "generate":
            key = generate(args.out)
            print(f"Privat nøkkel: {args.out.resolve()}  (vises ikke – oppbevar filen trygt, og aldri i repositoriet)")
            print(f"Offentlig nøkkel: {key}")
            print("Neste steg står under «Signerte utgivelser» i docs/UPDATING.md.")
        elif args.command == "public-key":
            print(public_key(load_key(args)).hex())
        elif args.command == "sign":
            target = write_signature(args.checksum, load_key(args))
            print(f"Signatur: {target}")
        else:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", args.public_key):
                raise SigningError("Den offentlige nøkkelen skal være 64 heksadesimale tegn.")
            try:
                signature = signature_path(args.checksum).read_text(encoding="ascii", errors="replace")
            except OSError as exc:
                raise SigningError(f"Fant ikke signaturfilen {signature_path(args.checksum).name}.") from exc
            print(update.verify_release_signature(args.checksum.read_bytes(), signature,
                                                  keys=[args.public_key.lower()], required=True))
    except (SigningError, update.UpdateError, OSError) as exc:
        print(f"Feil: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
