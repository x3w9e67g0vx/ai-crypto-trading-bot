import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup.sh"
DAY = 86_400


def test_backup_keeps_14_days(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "pg_dump"
    fake.write_text('#!/bin/sh\nfor last; do :; done\necho dump > "$last"\n')
    fake.chmod(0o755)

    out = tmp_path / "backups"
    out.mkdir()
    now = time.time()
    for name, age_days in (("veydranox-old13.dump", 13), ("veydranox-old15.dump", 15), ("other.dump", 30)):
        path = out / name
        path.write_text("x")
        os.utime(path, (now - age_days * DAY, now - age_days * DAY))

    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "BACKUP_DIR": str(out), "BACKUP_ONCE": "1"}
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, timeout=30)

    today = out / f"veydranox-{datetime.now(timezone.utc):%Y-%m-%d}.dump"
    assert today.stat().st_size > 0
    assert (out / "veydranox-old13.dump").exists()
    assert not (out / "veydranox-old15.dump").exists()
    assert (out / "other.dump").exists()
