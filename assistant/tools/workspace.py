import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from assistant.config import Settings


WORKSPACE_INSTRUCTIONS_HEADER = "# Workspace Agent Instructions"
WORKSPACE_INSTRUCTIONS_VERSION = "2026-05-09.4"

DEFAULT_WORKSPACE_INSTRUCTIONS = f"""{WORKSPACE_INSTRUCTIONS_HEADER}

Reference date: 2026-05-09
Policy version: {WORKSPACE_INSTRUCTIONS_VERSION}

## Scope

This workspace is the only area where the Telegram AI assistant may create, edit, build, and run project files.

The agent must never intentionally read, write, delete, or modify files outside this workspace.

The root workspace path belongs to the runtime owner. Inside it, the agent may use:

- `projects/` for durable software projects.
- `scratch/` for temporary experiments, notes, generated examples, or disposable checks.

Do not treat the bot repository, host filesystem, Docker daemon, SSH configuration, or production secrets as part of this workspace.

## Working Style

- Keep durable projects under `projects/<project-name>/`.
- Use `scratch/` for temporary experiments.
- Prefer small, coherent project folders.
- Keep generated secrets out of the workspace.
- Use `.env.example` for templates and leave real secrets to deployment environments.
- When Gabriel asks for a broad objective, complete the natural workflow end to end inside the workspace: inspect, plan briefly, edit/create files, run verification, and summarize.
- If verification fails and another attempt is available, use the failure output to repair incrementally instead of restarting destructively.
- Avoid splitting normal implementation requests into many follow-up prompts. Use `/git`, `/run`, `/read`, and similar commands only when Gabriel asks for specific low-level control.
- After changing files, report only a high-level summary, touched files, commands run, and verification status.
- Do not paste full diffs or large patches into Telegram.

## Project And Git Policy

- For new applications, create or reuse a folder under `projects/`.
- If a project has no Git repository, initialize one with `git init -b main` when the task is implementation-oriented.
- Use one branch per meaningful feature or change, named `agent/<short-task-name>`.
- Branch names must be lowercase where practical, concise, and task-based, for example `agent/jwt-auth`, `agent/demo-fastapi-health`, or `agent/dockerize-api`.
- Before making changes in an existing Git project, inspect `git status --short --branch`.
- If currently on `main` and the task changes files, create or switch to a feature branch before editing unless Gabriel explicitly asks otherwise.
- If the working tree has unrelated user changes, preserve them and adapt around them.
- For a coherent implementation that passes verification, create a local commit with a concise English message unless Gabriel asked not to commit.
- If verification fails, do not hide it. Commit only when the repository remains coherent and the failure is documented in the response, otherwise leave changes uncommitted for diagnosis.
- Do not push to remotes unless Gabriel explicitly asks for push/publish.
- If Gabriel asks for GitHub publication, prepare the local branch and commit inside the project; the bot will use controlled GitHub project profiles for push/PR.
- Do not deploy to external infrastructure unless Gabriel explicitly asks for deployment.
- Prefer `git diff --stat` and `git status` for reporting; do not paste full patches into Telegram.
- If a task fails, leave the workspace in a diagnosable state and report touched files, failing command, and next recommended action.

## Autonomy Inside The Workspace

- You may create, edit, move, delete, install dependencies, initialize Git repositories, run tests, run build commands, and generate project files inside the workspace when related to Gabriel's task.
- You do not need to ask for every internal workspace step.
- You may create local Git repositories, branches, and commits inside workspace projects.
- You may add project-level docs such as `README.md`, `CHANGELOG.md`, `docs/`, `.env.example`, Dockerfiles, compose files, tests, and CI examples when useful for the requested project.
- You must ask or stop if the task requires secrets, credentials, external accounts, network publishing, host-level changes, Docker socket access, SSH keys, or paths outside the workspace.

## Safety

- Do not touch `/app/data`, bot runtime files, host system folders, Docker socket, SSH keys, or production secrets.
- Before destructive work, prefer moving files to a clearly named backup path inside the workspace.
- If a task needs external credentials, stop and ask Gabriel to configure them outside the workspace.
- Never run commands that intentionally escape the workspace through absolute host paths, parent-directory traversal, mounted sockets, or privileged system locations.

## Reporting Contract

Telegram responses must be concise and operational:

- What was built or changed.
- Files touched, grouped at a high level.
- Git branch and commit, when applicable.
- Verification commands and whether they passed.
- Any blocker or next action.

Do not include full patches, full file contents, long command logs, secrets, tokens, or noisy generated output.
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

        current_instructions = instructions.read_text(encoding="utf-8", errors="replace")
        if current_instructions != DEFAULT_WORKSPACE_INSTRUCTIONS:
            if current_instructions.startswith(WORKSPACE_INSTRUCTIONS_HEADER):
                instructions.write_text(DEFAULT_WORKSPACE_INSTRUCTIONS, encoding="utf-8")
                return "Workspace preparado. AGENTS.md actualizado; projects/ y scratch/ estan disponibles."

            generated_instructions = self.root / "AGENTS.generated.md"
            generated_instructions.write_text(DEFAULT_WORKSPACE_INSTRUCTIONS, encoding="utf-8")
            return (
                "Workspace preparado. AGENTS.md personalizado detectado; "
                "he creado AGENTS.generated.md con la politica recomendada."
            )

        return "Workspace preparado. AGENTS.md ya estaba actualizado; projects/ y scratch/ estan disponibles."

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
        try:
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
            exit_code = completed.returncode
            output = completed.stdout[-self.settings.workspace_max_output_chars :]
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            partial_output = exc.stdout or ""
            if isinstance(partial_output, bytes):
                partial_output = partial_output.decode("utf-8", errors="replace")
            output = (
                f"Comando agotó el timeout de {self.settings.workspace_command_timeout_seconds}s.\n"
                f"{partial_output}"
            )[-self.settings.workspace_max_output_chars :]
        after = self._snapshot()
        changed_files = self._changed_files(before, after)
        return CommandResult(
            command=command,
            exit_code=exit_code,
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
        command_to_scan = self._strip_heredoc_bodies(command)
        command_to_scan = self._allow_safe_special_paths(command_to_scan)
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
        for fragment in blocked_fragments:
            if fragment in command_to_scan:
                raise ValueError(
                    "Comando rechazado: referencia rutas fuera del workspace permitido "
                    f"({fragment})."
                )

    def _strip_heredoc_bodies(self, command: str) -> str:
        lines = command.splitlines()
        output_lines = []
        skip_until = None

        for line in lines:
            if skip_until is not None:
                if line.strip() == skip_until:
                    skip_until = None
                    output_lines.append(line)
                continue

            output_lines.append(line)
            match = re.search(r"<<-?\s*['\"]?([A-Za-z0-9_.-]+)['\"]?", line)
            if match:
                skip_until = match.group(1)

        return "\n".join(output_lines)

    def _allow_safe_special_paths(self, command: str) -> str:
        return re.sub(r"(?<![A-Za-z0-9_.-])/dev/null(?![A-Za-z0-9_.-])", "__DEV_NULL__", command)

    def _safe_env(self) -> dict[str, str]:
        allowed_names = {"PATH", "LANG", "LC_ALL", "HOME", "PYTHONPATH"}
        env = {name: value for name, value in os.environ.items() if name in allowed_names}
        env["HOME"] = str(self.root)
        env["PYTHONUNBUFFERED"] = "1"
        env["GIT_AUTHOR_NAME"] = self.settings.workspace_git_author_name
        env["GIT_AUTHOR_EMAIL"] = self.settings.workspace_git_author_email
        env["GIT_COMMITTER_NAME"] = self.settings.workspace_git_author_name
        env["GIT_COMMITTER_EMAIL"] = self.settings.workspace_git_author_email
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
