"""Optional ARM64 static CLI installer; never logs in, starts or publishes.
Run manually on the target: python server-ops/setup-tailscale.py --install
Trust: HTTPS official package origin + official SHA256; not a detached signature.
"""
import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

SOURCE = "https://pkgs.tailscale.com/stable/"


def download(name, limit):
    url = SOURCE + name
    with urllib.request.urlopen(url, timeout=90) as response:
        if not response.geturl().startswith(SOURCE):
            raise RuntimeError("Refusing redirect outside official stable source")
        content = response.read(limit + 1)
    if len(content) > limit:
        raise RuntimeError("Download exceeds size limit")
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="explicit download/install consent")
    args = parser.parse_args()
    if not args.install:
        parser.error("Requires --install; no changes performed")
    if platform.machine().lower() not in {"aarch64", "arm64"}:
        parser.error("This installer is only for ARM64/aarch64")
    os.umask(0o077)
    metadata = json.loads(download("?mode=json", 1024 * 1024))
    version = metadata["TarballsVersion"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("Invalid stable version")
    name = metadata["Tarballs"]["arm64"]
    if name != f"tailscale_{version}_arm64.tgz":
        raise RuntimeError("Unexpected ARM64 package name")
    digest = download(name + ".sha256", 4096).decode("ascii").split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("Invalid official SHA256")
    archive = download(name, 150 * 1024 * 1024)
    if hashlib.sha256(archive).hexdigest() != digest:
        raise RuntimeError("SHA256 mismatch; refusing installation")
    base = Path.home() / "nosotros-private" / "tailscale"
    target = base / "bin"
    base.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError(f"Refusing to overwrite {target}; preserve existing binaries/state")
    with tempfile.TemporaryDirectory(prefix="install-", dir=base) as temp:
        staging = Path(temp) / "bin"
        staging.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for executable in ("tailscale", "tailscaled"):
                member = tar.getmember(f"tailscale_{version}_arm64/{executable}")
                if not member.isfile() or member.size > 150 * 1024 * 1024:
                    raise RuntimeError("Unexpected executable member")
                # Never extract paths, links, services, or upstream config files.
                with tar.extractfile(member) as source, (staging / executable).open("xb") as out:
                    shutil.copyfileobj(source, out)
                (staging / executable).chmod(0o700)
        (staging / "SOURCE.txt").write_text(f"{SOURCE}{name}\nSHA256 {digest}\n", encoding="utf-8")
        staging.rename(target)
    print(f"Installed {version} in {target}; authentication and publication NOT performed.")


if __name__ == "__main__":
    main()
