"""Demo source code: a small firmware repository whose commits mention the demo items.

Created as a local Git repository below ``<data_dir>/repos-local`` and connected to the demo project, so the Code
page, linked revisions, branches and the commit query work offline and in the tests.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from almlight.core.config import get_settings
from almlight.modules.identity.models import User
from almlight.modules.projects.models import Project

log = logging.getLogger("almlight.seed")

PEOPLE = {"alex": ("Alex Engineer", "alex@example.com"), "max": ("Max Manager", "max@example.com"),
          "rita": ("Rita Reviewer", "rita@example.com")}

PRESSURE_H = """#ifndef PRESSURE_H
#define PRESSURE_H
#include <stdint.h>

typedef enum { RANGE_10_BAR = 0, RANGE_100_BAR = 1 } pressure_range_t;

void pressure_init(pressure_range_t range);
int32_t pressure_read_mbar(void);
uint8_t pressure_in_range(int32_t mbar);

#endif
"""

PRESSURE_C = """#include "pressure.h"
#include "adc.h"

static pressure_range_t active_range = RANGE_10_BAR;
static const int32_t FULL_SCALE_MBAR[] = {10000, 100000};

void pressure_init(pressure_range_t range) { active_range = range; }

int32_t pressure_read_mbar(void) {
    int32_t raw = adc_read_bridge();
    return (raw * FULL_SCALE_MBAR[active_range]) / ADC_FULL_SCALE;
}

uint8_t pressure_in_range(int32_t mbar) {
    return mbar >= 0 && mbar <= FULL_SCALE_MBAR[active_range];
}
"""

COMP_C = """#include "compensation.h"

/* second-order polynomial over the sensor temperature, coefficients from the end-of-line calibration */
static float c0 = 0.0f, c1 = 1.0f, c2 = 0.0f;

void compensation_set(float a0, float a1, float a2) { c0 = a0; c1 = a1; c2 = a2; }

float compensate(float value, float temp_c) {
    float t = temp_c - 25.0f;
    return value * (c1 + c2 * t) + c0 * t;
}
"""

HART_C = """#include "hart.h"
#include "diagnostics.h"

/* HART command 48: read additional device status (NAMUR NE 107 categories) */
int hart_cmd48(uint8_t *buf, int len) {
    if (len < 6) return -1;
    diag_status_t s = diagnostics_status();
    buf[0] = s.category;     /* failure, check, out of spec, maintenance */
    buf[1] = s.code;
    buf[2] = s.sensor_ok;
    return 3;
}
"""

FILTER_C = """#include "afe.h"

/* EMC: second-order low-pass on the 4-20 mA loop feedback, fc = 30 Hz */
static float y1, y2;

float afe_filter(float x) {
    float y = 0.0201f * x + 1.561f * y1 - 0.6414f * y2;
    y2 = y1; y1 = y;
    return y;
}
"""

TEST_PY = """# Host-side unit tests (pytest + ctypes build of the firmware library)
from firmware import pressure


def test_full_scale_10_bar():
    pressure.init(0)
    assert pressure.in_range(10000)
    assert not pressure.in_range(10001)


def test_full_scale_100_bar():
    pressure.init(1)
    assert pressure.in_range(100000)
"""


def _repository_path(project_key: str) -> Path:
    return get_settings().local_repos_dir / f"{project_key.lower()}-sensor-firmware"


def _build_repository(path: Path, keys: dict[str, str], anchor: datetime) -> None:
    """Write the repository with dates relative to ``anchor``. The same inputs give the same commit hashes, so a
    repository written again later matches the commits that are already indexed."""
    settings = get_settings()
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    base_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(settings.data_dir),
                "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C.UTF-8"}

    def git(*args: str, who: str = "alex", days_ago: float = 0) -> None:
        name, mail = PEOPLE[who]
        when = (anchor - timedelta(days=days_ago)).isoformat()
        env = {**base_env, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": mail, "GIT_AUTHOR_DATE": when,
               "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": mail, "GIT_COMMITTER_DATE": when}
        subprocess.run(["git", *args], cwd=path, env=env, check=True, capture_output=True, timeout=60)

    def commit(message: str, files: dict[str, str], who: str = "alex", days_ago: float = 0) -> None:
        for rel, content in files.items():
            target = path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        git("add", "-A", who=who, days_ago=days_ago)
        git("commit", "-q", "-m", message, who=who, days_ago=days_ago)

    git("init", "-q", "-b", "main")
    commit("Initial firmware skeleton", {
        "README.md": "# Sensor firmware\n\nFirmware of the smart pressure transmitter family (demo).\n",
        "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nproject(sensor_firmware C)\n"
                          "add_library(fw src/pressure.c)\n",
        "src/pressure.h": PRESSURE_H.replace("uint8_t pressure_in_range(int32_t mbar);\n", ""),
        "src/pressure.c": "#include \"pressure.h\"\n"}, who="max", days_ago=34)
    commit(f"Implement measuring ranges 0-10 bar and 0-100 bar ({keys['range']})\n\n"
           "Full-scale values per range; range is selected at start-up from the EEPROM.",
           {"src/pressure.h": PRESSURE_H, "src/pressure.c": PRESSURE_C}, days_ago=30)
    commit(f"Add polynomial temperature compensation ({keys['comp']}, {keys['temp']})",
           {"src/compensation.c": COMP_C, "src/compensation.h": "float compensate(float value, float temp_c);\n"},
           days_ago=24)
    commit(f"Unit tests for the range check — verifies {keys['tc_range']}",
           {"tests/test_range.py": TEST_PY}, who="rita", days_ago=21)
    commit(f"Improve accuracy at reference conditions: 18-bit ADC averaging ({keys['accuracy']})",
           {"src/adc.h": "#define ADC_FULL_SCALE 262143\nint32_t adc_read_bridge(void);\n"}, days_ago=16)
    git("tag", "-a", "v0.9.0", "-m", "B-sample firmware", who="max", days_ago=15)
    commit(f"EMC: low-pass filter on the loop feedback ({keys['emc']})", {"src/afe.c": FILTER_C}, days_ago=6)
    commit(f"Fix drift at -40 degC: second compensation coefficient set\n\nCloses {keys['defect']}.",
           {"src/compensation.c": COMP_C.replace("c2 = 0.0f", "c2 = -0.00042f")}, days_ago=3)
    commit("Update README with build instructions", {
        "README.md": "# Sensor firmware\n\nFirmware of the smart pressure transmitter family (demo).\n\n"
                     "```\ncmake -B build && cmake --build build\n```\n"}, who="max", days_ago=2)
    git("checkout", "-q", "-b", f"feature/{keys['hart']}-hart-diagnostics")
    commit(f"HART command 48 with NE 107 diagnostics ({keys['hart']})",
           {"src/hart.c": HART_C, "src/hart.h": "int hart_cmd48(unsigned char *buf, int len);\n"}, days_ago=1)
    git("checkout", "-q", "main")


def seed_firmware_repository(db: Session, project: Project, actor: User, keys: dict[str, str]) -> None:
    from almlight.modules.vcs import service as vcs

    if shutil.which("git") is None:
        log.warning("git is not installed: the demo firmware repository is skipped")
        return
    anchor = datetime.now(UTC).replace(microsecond=0)
    path = _repository_path(project.key)
    _build_repository(path, keys, anchor)
    repo = vcs.add_repository(db, project, actor, name="sensor-firmware", url=str(path))
    # what is needed to write the same repository again after a restart (see ensure_firmware_repository)
    repo.meta = {**(repo.meta or {}), "demo_seed": {"keys": keys, "anchor": anchor.isoformat()}}
    vcs.sync(db, repo)


def ensure_firmware_repository(db: Session) -> None:
    """Write the demo repository again when it is gone. It lives below the data directory, which a container
    platform may reset on every restart (Azure Container Apps keeps only the attachment share); without it the
    connected repository would report a fetch error."""
    from sqlalchemy import select

    from almlight.modules.vcs import service as vcs
    from almlight.modules.vcs.models import Repository

    if shutil.which("git") is None:
        return
    for repo in db.execute(select(Repository).where(Repository.name == "sensor-firmware")).scalars().all():
        seed = (repo.meta or {}).get("demo_seed")
        project = db.get(Project, repo.project_id)
        if not seed or project is None or (_repository_path(project.key) / "HEAD").exists() \
                or (_repository_path(project.key) / ".git").exists():
            continue
        _build_repository(_repository_path(project.key), seed["keys"], datetime.fromisoformat(seed["anchor"]))
        vcs.sync(db, repo)
        db.commit()
        log.warning("Demo repository of %s written again", project.key)
