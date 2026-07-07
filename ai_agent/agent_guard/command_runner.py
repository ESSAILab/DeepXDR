from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Mapping


class SubprocessCommandRunner:
    """Async command runner used by nono wrapper and rollback worker."""

    async def run(
        self,
        command: list[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> dict:
        process_env = os.environ.copy()
        if env:
            process_env.update({key: str(value) for key, value in env.items()})
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=process_env,
            cwd=str(cwd) if cwd is not None else None,
        )
        stdout, stderr = await process.communicate()
        return {
            "exit_code": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
