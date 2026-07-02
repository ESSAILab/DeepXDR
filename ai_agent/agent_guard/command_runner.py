from __future__ import annotations

import asyncio


class SubprocessCommandRunner:
    """Async command runner used by nono wrapper and rollback worker."""

    async def run(self, command: list[str]) -> dict:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return {
            "exit_code": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
