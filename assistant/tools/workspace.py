import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from assistant.config import Settings


DEFAULT_WORKSPACE_INSTRUCTIONS = """# Workspace Agent Instructions

Reference date: 2026-05-09

## Scope

This workspace is the only area where the Telegram AI assistant may create, edit, build, and run project files.

The agent must never intentionally read, write, delete, or modify files outside this workspace.

## Working Style

- Keep projects under `projects/`.
- Use `scratch/` for temporary experiments.
- Prefer small, coherent project folders.
- Keep generated secrets out of the workspace.
- Use `.env.example` for templates and leave real secrets to deployment environments.
- After changing files, report only a high-level summary, touched files, commands run, and verification status.
- Do not paste full diffs or large patches into Telegram.
- If a project is a Git repository, inspect status before and after meaningful changes.
- Do not commit automatically unless Gabriel explicitly asks for it.
- Prefer leaving changes reviewable with `git status` and `git diff --stat`.

## Safety

- Do not touch `/app/data`, bot runtime files, host system folders, Docker socket, SSH keys, or production secrets.
- Before destructive work, prefer moving files to a clearly named backup path inside the workspace.
- If a task needs external credentials, stop and ask Gabriel to configure them outside the workspace.
"""


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    output: str
    changed_files: list[str]


class WorkspaceTools:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.workspace_root.resolve()

    def list_files(self, relative_path: str = ".", limit: int = 80) -> str:
        if not self.settings.workspace_read_enabled:
            return "La lectura de workspace está desactivada."

        target = self._safe_path(relative_path)
        if not target.exists():
            return f"No existe: {relative_path}"
        if not target.is_dir():
            return f"No es un directorio: {relative_path}"

        entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        lines = []
        for entry in entries[:limit]:
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{self._display_path(entry)}{suffix}")

        if len(entries) > limit:
            lines.append(f"... {len(entries) - limit} entradas más")

        return "\n".join(lines) if lines else "Directorio vacío."

    def read_file(self, relative_path: str, max_chars: int = 12000) -> str:
        if not self.settings.workspace_read_enabled:
            return "La lectura de workspace está desactivada."

        target = self._safe_path(relative_path)
        if not target.exists():
            return f"No existe: {relative_path}"
        if not target.is_file():
            return f"No es un archivo: {relative_path}"

        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            return f"{content[:max_chars]}\n\n[Archivo truncado a {max_chars} caracteres]"
        return content

    def search_text(self, query: str, relative_path: str = ".", limit: int = 30) -> str:
        if not self.settings.workspace_read_enabled:
            return "La lectura de workspace está desactivada."

        target = self._safe_path(relative_path)
        if not target.exists():
            return f"No existe: {relative_path}"

        files = [target] if target.is_file() else [
            item for item in target.rglob("*") if item.is_file() and not self._is_ignored(item)
        ]
        matches = []
        lowered_query = query.lower()

        for file_path in files:
            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            for line_number, line in enumerate(lines, start=1):
                if lowered_query in line.lower():
                    matches.append(
                        f"{self._display_path(file_path)}:{line_number}: {line.strip()[:220]}"
                    )
                    if len(matches) >= limit:
                        return "\n".join(matches)

        return "\n".join(matches) if matches else "Sin coincidencias."

    def status(self) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        instructions = self.root / "AGENTS.md"
        projects = self.root / "projects"
        scratch = self.root / "scratch"
        lines = [
            f"Workspace: {self.root}",
            f"Lectura: {'activada' if self.settings.workspace_read_enabled else 'desactivada'}",
            f"Escritura: {'activada' if self.settings.workspace_write_enabled else 'desactivada'}",
            f"Comandos: {'activados' if self.settings.workspace_command_enabled else 'desactivados'}",
            f"Instrucciones: {'presentes' if instructions.exists() else 'no creadas'}",
            f"Projects: {'presente' if projects.exists() else 'no creado'}",
            f"Scratch: {'presente' if scratch.exists() else 'no creado'}",
        ]
        return "\n".join(lines)

    def bootstrap(self) -> str:
        self._require_write()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "projects").mkdir(exist_ok=True)
        (self.root / "scratch").mkdir(exist_ok=True)
        instructions = self.root / "AGENTS.md"
        if not instructions.exists():
            instructions.write_text(DEFAULT_WORKSPACE_INSTRUCTIONS, encoding="utf-8")
            return "Workspace preparado. Creado AGENTS.md, projects/ y scratch/."
        return "Workspace preparado. AGENTS.md ya existía; projects/ y scratch/ están disponibles."

    def write_file(self, relative_path: str, content: str) -> str:
        self._require_write()
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Archivo escrito: {self._display_path(target)} ({len(content)} caracteres)"

    def run_command(self, command: str) -> CommandResult:
        self._require_commands()
        self._validate_command(command)
        before = self._snapshot()
        completed = subprocess.run(
            command,
            shell=True,
            cwd=self.root,
            env=self._safe_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=self.settings.workspace_command_timeout_seconds,
        )
        after = self._snapshot()
        changed_files = self._changed_files(before, after)
        output = completed.stdout[-self.settings.workspace_max_output_chars :]
        return CommandResult(
            command=command,
            exit_code=completed.returncode,
            output=output.strip(),
            changed_files=changed_files,
        )

    def _safe_path(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and not candidate.is_relative_to(self.root):
            raise ValueError("Ruta fuera del workspace permitido.")
        return candidate

    def _display_path(self, path: Path) -> str:
        return str(path.relative_to(self.root)).replace("\\", "/")

    def _is_ignored(self, path: Path) -> bool:
        ignored_parts = {".git", "__pycache__", ".venv", "venv", "node_modules", "data"}
        return any(part in ignored_parts for part in path.relative_to(self.root).parts)

    def _require_write(self) -> None:
        if not self.settings.workspace_write_enabled:
            raise PermissionError("La escritura del workspace está desactivada.")

    def _require_commands(self) -> None:
        if not self.settings.workspace_command_enabled:
            raise PermissionError("La ejecución de comandos del workspace está desactivada.")
        self._require_write()

    def _validate_command(self, command: str) -> None:
        blocked_fragments = [
            "../",
            "..\\",
            "/app/data",
            "/app/.env",
            "/root",
            "/etc",
            "/opt",
            "/home",
            "/proc",
            "/sys",
            "/dev",
            "C:\\",
            "docker.sock",
        ]
        if any(fragment in command for fragment in blocked_fragments):
            raise ValueError("Comando rechazado: referencia rutas fuera del workspace permitido.")

    def _safe_env(self) -> dict[str, str]:
        allowed_names = {"PATH", "LANG", "LC_ALL", "HOME", "PYTHONPATH"}
        env = {name: value for name, value in os.environ.items() if name in allowed_names}
        env["HOME"] = str(self.root)
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _snapshot(self) -> dict[str, tuple[int, int]]:
        if not self.root.exists():
            return {}
        snapshot = {}
        for path in self.root.rglob("*"):
            if not path.is_file() or self._is_ignored(path):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[self._display_path(path)] = (stat.st_mtime_ns, stat.st_size)
            if len(snapshot) >= 2000:
                break
        return snapshot

    def _changed_files(
        self,
        before: dict[str, tuple[int, int]],
        after: dict[str, tuple[int, int]],
        limit: int = 80,
    ) -> list[str]:
        changed = [
            path
            for path, metadata in after.items()
            if before.get(path) != metadata
        ]
        deleted = [path for path in before if path not in after]
        result = sorted(changed + [f"{path} (deleted)" for path in deleted])
        if len(result) > limit:
            return result[:limit] + [f"... {len(result) - limit} ficheros más"]
        return result
