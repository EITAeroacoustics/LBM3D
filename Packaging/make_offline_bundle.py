"""Pack fixed project, upstream and build-tool archives for an offline workstation."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


AMREX_SHA256 = "c270730e16d8a2bc718879db80caba33c81c7fe5470bf761ec0be26099a13b1c"
CMAKE_SHA256 = "9114e33358a9efc93d6ea658805280fc3201b882b944a4d946edd9472fd1eec7"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--amrex-source", type=Path, required=True)
    parser.add_argument("--cmake-package", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    project_commit = git(repo, "rev-parse", "HEAD")
    upstream_commit = git(repo / "iLBMReX", "rev-parse", "HEAD")
    if sha256(args.amrex_source) != AMREX_SHA256 or sha256(args.cmake_package) != CMAKE_SHA256:
        raise ValueError("AMReX or CMake archive differs from the frozen P1 dependency")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lbm3d-bundle-") as temporary:
        root = Path(temporary) / "LBM3D-offline"
        root.mkdir()
        subprocess.run(["git", "-C", str(repo), "archive", "--format=tar.gz",
                        "--prefix=LBM3D/", "-o", str(root / "project.tar.gz"),
                        project_commit], check=True)
        subprocess.run(["git", "-C", str(repo / "iLBMReX"), "archive",
                        "--format=tar.gz", "--prefix=LBM3D/iLBMReX/",
                        "-o", str(root / "ilbmrex-upstream.tar.gz"),
                        upstream_commit], check=True)
        shutil.copy2(args.amrex_source, root / "amrex-26.11-source.tar.gz")
        shutil.copy2(args.cmake_package, root / "cmake-3.30.9-linux-x86_64.tar.gz")
        shutil.copy2(repo / "Packaging" / "offline_build.sh", root / "offline_build.sh")
        shutil.copy2(repo / "Packaging" / "BUNDLE_README.md", root / "README.md")
        files = sorted(path for path in root.iterdir() if path.is_file())
        (root / "SHA256SUMS").write_text("".join(
            f"{sha256(path)}  {path.name}\n" for path in files))
        manifest = {
            "project_commit": project_commit,
            "upstream_commit": upstream_commit,
            "amrex_version": "26.11",
            "files": {path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
                      for path in files},
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        with tarfile.open(args.output, "w:gz") as archive:
            archive.add(root, arcname=root.name)
    print(f"bundle={args.output} sha256={sha256(args.output)}")


if __name__ == "__main__":
    main()
