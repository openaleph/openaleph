import os
import shutil
import stat
import subprocess
from pathlib import Path


def run_start_local(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / "contrib").mkdir()
    shutil.copyfile(
        root / "contrib/start-local.sh", tmp_path / "contrib/start-local.sh"
    )
    shutil.copyfile(root / "aleph.env.tmpl", tmp_path / "aleph.env.tmpl")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        # Stop before starting services, after the real environment generation.
        "docker": 'if [ "$1" = compose ] && [ "$2" = version ]; then exit 0; fi\nexit 77',
        "openssl": "printf '%s\\n' " + "a" * 64,
        "curl": "exit 0",
    }
    for name, body in commands.items():
        command = bin_dir / name
        command.write_text("#!/bin/sh\n" + body + "\n")
        command.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    result = subprocess.run(
        ["sh", str(tmp_path / "contrib/start-local.sh")],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 77, result.stderr
    return tmp_path / "aleph.env"


def test_fresh_environment_uses_shared_queue(tmp_path, monkeypatch):
    env_file = run_start_local(tmp_path, monkeypatch)
    values = dict(
        line.split("=", 1)
        for line in env_file.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    database_uri = "postgresql://aleph:aleph@postgres/aleph"
    assert values.get("PROCRASTINATE_DB_URI") == database_uri
    assert values["FTM_FRAGMENTS_URI"] == database_uri
    assert values["ALEPH_SINGLE_USER"] == "true"
    assert values["ALEPH_SECRET_KEY"] == "a" * 64
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_existing_environment_is_preserved(tmp_path, monkeypatch):
    env_file = tmp_path / "aleph.env"
    original = (
        b"PROCRASTINATE_DB_URI=postgresql://other-db/custom\n"
        b"ALEPH_SINGLE_USER=false\n"
        b"ALEPH_SECRET_KEY=existing-secret\n"
    )
    env_file.write_bytes(original)
    env_file.chmod(0o600)
    run_start_local(tmp_path, monkeypatch)
    assert env_file.read_bytes() == original
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
