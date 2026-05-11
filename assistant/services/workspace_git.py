import re

from assistant.tools.workspace import WorkspaceTools


class WorkspaceGitService:
    def __init__(self, workspace_tools: WorkspaceTools):
        self.workspace_tools = workspace_tools

    def handle(self, relative_project_path: str, action: str, args: list[str]) -> str:
        project_path = self._normalize_project_path(relative_project_path)
        action = action.lower()

        if action == "init":
            return self._init(project_path)
        if action == "status":
            return self._run_git(project_path, "git status --short --branch")
        if action == "log":
            return self._run_git(project_path, "git log --oneline --decorate -n 10")
        if action == "diff":
            return self._diff(project_path)
        if action == "branch":
            if not args:
                return "Usa: /git <proyecto> branch <nombre-rama>"
            branch_name = self._safe_branch_name(args[0])
            return self._run_git(project_path, f"git checkout -b {branch_name}")
        if action == "commit":
            message = " ".join(args).strip()
            if not message:
                return "Usa: /git <proyecto> commit <mensaje>"
            return self._commit(project_path, message)

        return (
            "Acción Git no soportada. Usa: init, status, log, diff, "
            "branch <nombre>, commit <mensaje>."
        )

    def _init(self, project_path: str) -> str:
        commands = [
            f"cd {self._quote(project_path)}",
            "git init -b main",
            "git status --short --branch",
        ]
        return self._run_shell(" && ".join(commands))

    def _commit(self, project_path: str, message: str) -> str:
        commands = [
            f"cd {self._quote(project_path)}",
            "git add .",
            f"git commit -m {self._quote(message)}",
            "git status --short --branch",
        ]
        return self._run_shell(" && ".join(commands))

    def _diff(self, project_path: str) -> str:
        commands = [
            f"cd {self._quote(project_path)}",
            "(git diff --stat && git diff --cached --stat && git status --short --branch)",
        ]
        return self._run_shell(" && ".join(commands))

    def _run_git(self, project_path: str, git_command: str) -> str:
        return self._run_shell(f"cd {self._quote(project_path)} && {git_command}")

    def _run_shell(self, command: str) -> str:
        result = self.workspace_tools.run_command(command)
        return (
            f"Git ejecutado.\n\n"
            f"Resultado: exit code {result.exit_code}\n\n"
            f"Ficheros tocados:\n{self._format_files(result.changed_files)}\n\n"
            f"Salida relevante:\n{result.output or 'Sin salida relevante.'}"
        )

    def _normalize_project_path(self, relative_project_path: str) -> str:
        project_path = relative_project_path.strip().strip("/")
        if not project_path:
            raise ValueError("Ruta de proyecto vacía.")
        self.workspace_tools._safe_path(project_path)
        return project_path

    def _safe_branch_name(self, branch_name: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", branch_name):
            raise ValueError("Nombre de rama no válido.")
        if branch_name.startswith("/") or ".." in branch_name:
            raise ValueError("Nombre de rama no válido.")
        return branch_name

    def _quote(self, value: str) -> str:
        return "'" + value.replace("'", "'\"'\"'") + "'"

    def _format_files(self, changed_files: list[str]) -> str:
        return "\n".join(f"- {path}" for path in changed_files) or "- Sin cambios detectados"
