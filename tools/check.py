"""离线检查源码与本次构建生成的分发物。"""

import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from email.parser import BytesParser
from pathlib import Path


def check_packages(root: Path, target: Path) -> None:
    project = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]
    output = target / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(output)],
        cwd=root,
        check=True,
    )

    (wheel,) = output.glob("*.whl")
    (sdist,) = output.glob("*.tar.gz")
    license_names = set(project["license-files"])
    with zipfile.ZipFile(wheel) as archive:
        (metadata_path,) = (
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        info_dir = metadata_path.removesuffix("/METADATA")
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
        assert metadata["Name"] == project["name"]
        assert metadata["Version"] == project["version"]
        assert metadata["License-Expression"] == project["license"]
        assert set(metadata.get_all("License-File", [])) == license_names
        for name in license_names:
            assert (
                archive.read(f"{info_dir}/licenses/{name}")
                == (root / name).read_bytes()
            )
        for name in ("py.typed", "_trading_days_2026.txt"):
            assert (
                archive.read(f"pyths/{name}")
                == (root / "src/pyths" / name).read_bytes()
            )

    with tarfile.open(sdist) as archive:
        (metadata_path,) = (
            name
            for name in archive.getnames()
            if name.count("/") == 1 and name.endswith("/PKG-INFO")
        )
        prefix = metadata_path.removesuffix("/PKG-INFO")
        metadata_file = archive.extractfile(metadata_path)
        assert metadata_file is not None
        metadata = BytesParser().parsebytes(metadata_file.read())
        assert metadata["Name"] == project["name"]
        assert metadata["Version"] == project["version"]
        for name in license_names | {
            "src/pyths/py.typed",
            "src/pyths/_trading_days_2026.txt",
        }:
            member = archive.extractfile(f"{prefix}/{name}")
            assert member is not None
            assert member.read() == (root / name).read_bytes()

    venv.create(target / "venv", with_pip=True)
    python = (
        target
        / "venv"
        / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
        cwd=target,
        check=True,
    )
    subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            (
                "from datetime import date; from importlib.metadata import version; "
                "from pyths import ths; from pyths._trading_calendar import previous_trade_date; "
                f"assert version('pyths') == {project['version']!r}; "
                "assert previous_trade_date(date(2026, 2, 24)) == date(2026, 2, 13); "
                "client = ths(); assert client.get_hot_boards(); client.close(); assert client.closed"
            ),
        ],
        cwd=target,
        check=True,
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp)
        for args in (
            ["pytest", "--basetemp", str(target / "pytest")],
            ["ruff", "check", "."],
            ["ruff", "format", "--check", "."],
            ["mypy", "src"],
        ):
            subprocess.run([sys.executable, "-m", *args], cwd=root, check=True)
        check_packages(root, target)


if __name__ == "__main__":
    main()
