"""Install this Windows release into its own environment. Never starts the lab."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OWNER = "vv-frontier-setup-v1"
MARKER = ".vv-frontier-environment.json"
VERSIONS = {"Pillow": "13.0.0", "imageio-ffmpeg": "0.6.0", "pypdf": "6.21.2"}


class SetupError(RuntimeError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runtime_check():
    if sys.platform != "win32" or platform.python_implementation() != "CPython":
        raise SetupError("This release installer supports Windows CPython only.")
    if sys.version_info[:2] not in {(3, 11), (3, 12), (3, 13)}:
        raise SetupError("Use CPython 3.11, 3.12 or 3.13 (64-bit).")
    if struct.calcsize("P") != 8 or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SetupError("This release requires Windows x64 Python, not ARM or 32-bit.")


def inside(root, path):
    root, path = Path(root).resolve(), Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise SetupError("Setup path points outside this project: " + str(path))
    return path


def marker(root):
    path = inside(root, Path(root) / ".venv" / MARKER)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetupError("Existing .venv is unmanaged or incomplete; use a fresh release folder.") from exc
    if not isinstance(data, dict) or data.get("owner") != OWNER or data.get("project") != str(Path(root).resolve()):
        raise SetupError("Existing .venv belongs to another installation; use a fresh folder.")
    return data


def write_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".setup-tmp")
    if temporary.is_symlink():
        raise SetupError("Setup temporary file is a symbolic link.")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def command(args, *, timeout=600):
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PYTHON", "PIP_", "IMAGEIO_"))}
    env["PIP_CONFIG_FILE"] = os.devnull
    result = subprocess.run(args, env=env, cwd=ROOT, timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise SetupError("Setup command failed with exit code " + str(result.returncode))


@contextmanager
def setup_lock(root):
    path = inside(root, Path(root) / ".lab-tools" / ".setup.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        import msvcrt
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise SetupError("Another setup is running; wait for it to finish.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def inactive_project(root):
    """Hold an existing server lock while changing the environment, without creating data."""
    path = Path(root) / ".lab-data" / ".instance.lock"
    if not path.exists():
        yield
        return
    inside(root, path)
    handle = path.open("r+b")
    try:
        import msvcrt
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise SetupError("Stop this laboratory before running setup.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()


def project_env(root):
    root = Path(root).resolve()
    venv = inside(root, root / ".venv")
    active = os.environ.get("VIRTUAL_ENV")
    if active and Path(active).resolve() != venv.resolve():
        raise SetupError("Deactivate the other virtual environment before setup.")
    if sys.prefix != sys.base_prefix and Path(sys.prefix).resolve() != venv.resolve():
        raise SetupError("Run setup with a base Python, not another virtual environment.")
    return venv


def verify_encoder(binary):
    outputs = {}
    for option in ["-version", "-encoders", "-L"]:
        check = subprocess.run([str(binary), "-hide_banner", option], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=20,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if check.returncode:
            raise SetupError("Installed FFmpeg verification failed.")
        outputs[option] = check.stdout + check.stderr
    if "ffmpeg version" not in outputs["-version"] or "libx264" not in outputs["-encoders"]:
        raise SetupError("The installed encoder does not support required H.264/libx264.")
    return outputs


def finalize(root):
    root = Path(root).resolve()
    data = marker(root)
    venv = inside(root, root / ".venv")
    if Path(sys.prefix).resolve() != venv.resolve():
        raise SetupError("Finalization must use this project's .venv Python.")
    for name, expected in VERSIONS.items():
        if importlib.metadata.version(name) != expected:
            raise SetupError("Unexpected installed dependency version: " + name)
    # Do not use get_ffmpeg_exe(): it accepts an environment override executable.
    package = importlib.metadata.distribution("imageio-ffmpeg")
    binaries = [inside(venv, package.locate_file(item)) for item in package.files or []
                if str(item).replace("\\", "/").startswith("imageio_ffmpeg/binaries/")
                and str(item).lower().endswith(".exe")]
    if len(binaries) != 1:
        raise SetupError("The pinned imageio-ffmpeg wheel must contain one Windows executable.")
    source = binaries[0]
    info = verify_encoder(source)
    media = inside(root, root / ".lab-tools" / "media")
    binary = inside(root, media / "ffmpeg.exe")
    receipt = inside(root, media / "encoder.json")
    if binary.exists() or receipt.exists():
        try:
            previous = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SetupError("Existing encoder is unmanaged; use a fresh release folder.") from exc
        if not isinstance(previous, dict) or previous.get("installed_by") != OWNER:
            raise SetupError("Existing encoder is unmanaged; it was left unchanged.")
    media.mkdir(parents=True, exist_ok=True)
    temporary = inside(root, binary.with_suffix(".setup-tmp"))
    shutil.copyfile(source, temporary)
    temporary.replace(binary)
    digest = sha(binary)
    if digest != sha(source):
        raise SetupError("Copied encoder checksum mismatch.")
    (media / "LICENSE-ffmpeg.txt").write_text(info["-L"], encoding="utf-8")
    write_json(receipt, {"sha256": digest, "installed_by": OWNER,
                        "source": "PyPI imageio-ffmpeg==0.6.0 Windows x64 wheel",
                        "version": info["-version"].splitlines()[0]})
    data.update(state="complete", requirements_sha256=sha(root / "requirements.txt"),
                dependencies=VERSIONS, encoder_sha256=digest)
    write_json(venv / MARKER, data)
    print("Verified Pillow, pypdf, FFmpeg H.264 and the project environment. No server was started.")


def check(root):
    root = Path(root).resolve()
    data = marker(root)
    if Path(sys.prefix).resolve() != (root / ".venv").resolve():
        raise SetupError("Launch with this project's .venv Python.")
    if data.get("state") != "complete" or data.get("requirements_sha256") != sha(root / "requirements.txt"):
        raise SetupError("Setup is incomplete or requirements changed; run Setup-Laboratory.cmd.")
    for name, version in VERSIONS.items():
        if importlib.metadata.version(name) != version:
            raise SetupError("Dependency mismatch; run Setup-Laboratory.cmd.")
    binary = inside(root, root / ".lab-tools/media/ffmpeg.exe")
    receipt_path = inside(root, binary.parent / "encoder.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or receipt.get("sha256") != data.get("encoder_sha256") or sha(binary) != receipt["sha256"]:
        raise SetupError("Encoder checksum mismatch; run Setup-Laboratory.cmd.")


def install(root):
    root = Path(root).resolve()
    venv = project_env(root)
    for path in [venv, root / ".lab-tools", root / ".lab-tools/media"]:
        inside(root, path)
    with setup_lock(root), inactive_project(root):
        if venv.exists():
            data = marker(root)
            data["state"] = "incomplete"
            write_json(venv / MARKER, data)
        else:
            command([sys.executable, "-I", "-m", "venv", str(venv)])
            write_json(venv / MARKER, {"owner": OWNER, "project": str(root), "state": "incomplete"})
        python = inside(root, venv / "Scripts/python.exe")
        if not python.is_file():
            raise SetupError("The existing .venv has no Windows Python; use a fresh folder.")
        command([str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
                 "install", "--require-virtualenv", "--require-hashes", "--only-binary=:all:",
                 "--no-deps", "--force-reinstall", "--no-cache-dir", "--retries", "1", "--timeout", "30",
                 "--index-url", "https://pypi.org/simple", "-r", str(root / "requirements.txt")])
        command([str(python), "-I", "-B", str(root / "tools/setup_local.py"), "--finalize"], timeout=90)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="Verify setup without network or execution")
    modes.add_argument("--probe", action="store_true", help="Check supported base Python only")
    modes.add_argument("--finalize", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        runtime_check()
        if args.probe:
            return 0
        if args.check:
            with setup_lock(ROOT):
                check(ROOT)
        elif args.finalize:
            finalize(ROOT)
        else:
            install(ROOT)
    except (SetupError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            importlib.metadata.PackageNotFoundError) as exc:
        print("Setup: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
