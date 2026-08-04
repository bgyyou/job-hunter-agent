from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class DraftUpgradeMeasurement:
    old_ref: str
    new_ref: str
    old_schema_version: int
    new_schema_version: int
    sample_count: int
    preserved_count: int
    lost_draft_ids: tuple[str, ...]
    score: float


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _read_ref_file(repo_root: Path, ref: str, path: str) -> str:
    return _git(repo_root, "show", f"{ref}:{path}")


def _migration_paths(repo_root: Path, ref: str) -> list[str]:
    output = _git(
        repo_root,
        "ls-tree",
        "-r",
        "--name-only",
        ref,
        "--",
        "database/migrations",
    )
    return sorted(path for path in output.splitlines() if path.endswith(".sql"))


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
    except (ImportError, sqlite3.Error):
        pass
    finally:
        try:
            conn.enable_load_extension(False)
        except sqlite3.Error:
            pass


def _apply_ref_schema(
    conn: sqlite3.Connection,
    repo_root: Path,
    ref: str,
    *,
    after_version: int = 0,
) -> int:
    if after_version == 0:
        conn.executescript(_read_ref_file(repo_root, ref, "data/schema.sql"))

    for path in _migration_paths(repo_root, ref):
        version = int(Path(path).name.split("_", 1)[0])
        if version <= after_version:
            continue
        if version == 4:
            jd_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(jds)").fetchall()
            }
            if "requirements" not in jd_columns:
                conn.execute(
                    "UPDATE schema_version SET version = 4, "
                    "description = 'JD schema already converged', "
                    "applied_at = datetime('now') WHERE id = 1"
                )
                continue
        conn.executescript(_read_ref_file(repo_root, ref, path))

    row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError(f"schema_version missing after applying {ref}")
    return int(row[0])


def _insert_sample_drafts(conn: sqlite3.Connection, sample_count: int) -> None:
    for index in range(sample_count):
        draft_id = f"r9-p3-draft-{index + 1}"
        conn.execute(
            """
            INSERT INTO flow_a_drafts (
                id, user_id, status, industry, function, position,
                current_step, current_section, section_data,
                section_messages, section_status, generation_state,
                last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id,
                f"r9-p3-user-{index + 1}",
                "failed" if index == sample_count - 1 else "draft",
                "互联网/软件",
                "产品",
                f"AI 产品经理 {index + 1}",
                "generate" if index == sample_count - 1 else "collect",
                "experience",
                json.dumps({"header": {"name": f"候选人{index + 1}"}}, ensure_ascii=False),
                json.dumps(
                    {"experience": [{"role": "user", "content": f"第{index + 1}份草稿"}]},
                    ensure_ascii=False,
                ),
                json.dumps({"experience": "done"}, ensure_ascii=False),
                json.dumps(
                    {"skeleton": {"status": "done", "result": {"index": index + 1}}},
                    ensure_ascii=False,
                ),
                "timeout" if index == sample_count - 1 else None,
                "2026-08-04T00:00:00",
                f"2026-08-04T00:00:{index:02d}",
            ),
        )
    conn.commit()


def _draft_snapshot(conn: sqlite3.Connection, draft_ids: Sequence[str]) -> dict[str, tuple]:
    placeholders = ",".join("?" for _ in draft_ids)
    rows = conn.execute(
        f"SELECT * FROM flow_a_drafts WHERE id IN ({placeholders}) ORDER BY id",
        tuple(draft_ids),
    ).fetchall()
    return {str(row[0]): tuple(row) for row in rows}


def measure_draft_upgrade(
    *,
    repo_root: Path,
    old_ref: str,
    new_ref: str,
    sample_count: int = 5,
) -> DraftUpgradeMeasurement:
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")

    repo_root = repo_root.resolve()
    _git(repo_root, "rev-parse", "--verify", f"{old_ref}^{{commit}}")
    _git(repo_root, "rev-parse", "--verify", f"{new_ref}^{{commit}}")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", old_ref, new_ref],
        cwd=repo_root,
        check=False,
        capture_output=True,
    ).returncode != 0:
        raise ValueError(f"{old_ref} is not an ancestor of {new_ref}")

    with tempfile.TemporaryDirectory(prefix="jobhunter-r9-p3-") as temp_dir:
        db_path = Path(temp_dir) / "upgrade.db"
        conn = sqlite3.connect(db_path)
        try:
            _load_sqlite_vec(conn)
            old_schema_version = _apply_ref_schema(conn, repo_root, old_ref)
            _insert_sample_drafts(conn, sample_count)
            draft_ids = tuple(f"r9-p3-draft-{index + 1}" for index in range(sample_count))
            before = _draft_snapshot(conn, draft_ids)

            new_schema_version = _apply_ref_schema(
                conn,
                repo_root,
                new_ref,
                after_version=old_schema_version,
            )
            after = _draft_snapshot(conn, draft_ids)
        finally:
            conn.close()

    lost_draft_ids = tuple(
        draft_id for draft_id in draft_ids if before.get(draft_id) != after.get(draft_id)
    )
    preserved_count = sample_count - len(lost_draft_ids)
    score = max(0.0, 10.0 - 2.0 * len(lost_draft_ids))
    return DraftUpgradeMeasurement(
        old_ref=old_ref,
        new_ref=new_ref,
        old_schema_version=old_schema_version,
        new_schema_version=new_schema_version,
        sample_count=sample_count,
        preserved_count=preserved_count,
        lost_draft_ids=lost_draft_ids,
        score=score,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure Flow A draft preservation across releases")
    parser.add_argument("--old-ref", required=True)
    parser.add_argument("--new-ref", required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    result = measure_draft_upgrade(
        repo_root=args.repo_root,
        old_ref=args.old_ref,
        new_ref=args.new_ref,
        sample_count=args.samples,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
