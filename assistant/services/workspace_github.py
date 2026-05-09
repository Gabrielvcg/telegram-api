import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from assistant.config import GitHubProjectSettings, Settings
from assistant.tools.workspace import WorkspaceTools


class WorkspaceGitHubService:
    def __init__(self, settings: Settings, workspace_tools: WorkspaceTools):
        self.settings = settings
        self.workspace_tools = workspace_tools

    def handle(self, profile_name: str | None, action: str | None, args: list[str]) -> str:
        if action is None:
            return self.list_projects()

        action = action.lower()
        if action == "list":
            return self.list_projects()

        if not profile_name:
            return self._usage()

        project = self._project(profile_name)
        if action == "clone":
            return self.clone(project)
        if action == "status":
            return self.status(project)
        if action == "push-pr":
            title = " ".join(args).strip()
            if not title:
                return "Usa: /github <perfil> push-pr <titulo>"
            return self.push_pr(project, title)

        return self._usage()

    def list_projects(self) -> str:
        if not self.settings.github_projects:
            return (
                "No hay perfiles GitHub configurados. Define PROJECT_<NOMBRE>_PATH, "
                "PROJECT_<NOMBRE>_REPO y PROJECT_<NOMBRE>_TOKEN."
            )

        lines = ["Perfiles GitHub configurados:"]
        for project in sorted(self.settings.github_projects.values(), key=lambda item: item.name):
            lines.append(f"- {project.name}: {project.repo} -> {project.path}")
        return "\n".join(lines)

    def clone(self, project: GitHubProjectSettings) -> str:
        target = self._project_path(project)
        if target.exists() and any(target.iterdir()):
            if not (target / ".git").exists():
                return f"La ruta ya existe pero no es un repositorio Git: {project.path}"
            return (
                "El proyecto ya existe en el workspace.\n\n"
                f"{self.status(project)}"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        result = self._run_git(
            project=project,
            args=["clone", self._repo_url(project), str(target)],
            cwd=self.workspace_tools.root,
            authenticated=True,
        )
        if result.returncode != 0:
            return self._format_git_output("Clone GitHub fallido", result)

        self._run_git(
            project=project,
            args=["remote", "set-url", "origin", self._repo_url(project)],
            cwd=target,
            authenticated=False,
        )
        return self._format_git_output("Repositorio clonado en workspace", result)

    def status(self, project: GitHubProjectSettings) -> str:
        target = self._require_project_repo(project)
        branch = self._run_git(project, ["branch", "--show-current"], target, authenticated=False)
        status = self._run_git(project, ["status", "--short", "--branch"], target, authenticated=False)
        remote = self._run_git(project, ["remote", "get-url", "origin"], target, authenticated=False)
        return (
            f"GitHub project: {project.name}\n"
            f"Repo: {project.repo}\n"
            f"Path: {project.path}\n"
            f"Base branch: {project.base_branch}\n"
            f"Current branch: {branch.stdout.strip() or 'desconocida'}\n\n"
            f"Remote:\n{self._sanitize(remote.stdout.strip(), project) or 'sin remote'}\n\n"
            f"Status:\n{status.stdout.strip() or 'working tree limpio'}"
        )

    def push_pr(self, project: GitHubProjectSettings, title: str) -> str:
        target = self._require_project_repo(project)
        branch = self._current_branch(project, target)
        if branch in {project.base_branch, "main", "master"}:
            return (
                "No hago push-pr desde la rama principal. Crea o usa una rama agent/<feature> "
                "y vuelve a intentarlo."
            )

        dirty = self._run_git(project, ["status", "--porcelain"], target, authenticated=False)
        if dirty.stdout.strip():
            return (
                "No hago push-pr porque hay cambios sin commit.\n\n"
                "Estado:\n"
                f"{dirty.stdout.strip()}"
            )

        push = self._run_git(
            project=project,
            args=["push", self._repo_url(project), branch],
            cwd=target,
            authenticated=True,
        )
        if push.returncode != 0:
            return self._format_git_output("Push GitHub fallido", push)

        pr = self._create_or_get_pull_request(project, branch, title)
        return (
            "Push y PR preparados.\n\n"
            f"Proyecto: {project.name}\n"
            f"Repo: {project.repo}\n"
            f"Rama: {branch}\n"
            f"Base: {project.base_branch}\n"
            f"PR: {pr['html_url']}\n\n"
            "No he hecho merge ni deploy directo."
        )

    def _project(self, profile_name: str) -> GitHubProjectSettings:
        project = self.settings.github_projects.get(profile_name.lower())
        if not project:
            available = ", ".join(sorted(self.settings.github_projects)) or "ninguno"
            raise ValueError(f"Perfil GitHub no configurado: {profile_name}. Disponibles: {available}")
        return project

    def _project_path(self, project: GitHubProjectSettings) -> Path:
        if project.path.startswith("/") or ".." in Path(project.path).parts:
            raise ValueError("Ruta de proyecto GitHub no valida.")
        return self.workspace_tools._safe_path(project.path)

    def _require_project_repo(self, project: GitHubProjectSettings) -> Path:
        target = self._project_path(project)
        if not (target / ".git").exists():
            raise ValueError(f"El proyecto no esta clonado como Git repo: {project.path}")
        return target

    def _current_branch(self, project: GitHubProjectSettings, target: Path) -> str:
        result = self._run_git(project, ["branch", "--show-current"], target, authenticated=False)
        branch = result.stdout.strip()
        if not branch:
            raise ValueError("No he podido detectar la rama actual.")
        return branch

    def _repo_url(self, project: GitHubProjectSettings) -> str:
        return f"https://github.com/{project.repo}.git"

    def _run_git(
        self,
        project: GitHubProjectSettings,
        args: list[str],
        cwd: Path,
        authenticated: bool,
    ) -> subprocess.CompletedProcess:
        env = self._safe_env()
        context = self._git_auth(project.token, env) if authenticated else _null_context(env)
        with context as command_env:
            return subprocess.run(
                ["git", *args],
                cwd=cwd,
                env=command_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.settings.workspace_command_timeout_seconds,
                check=False,
            )

    def _safe_env(self) -> dict[str, str]:
        env = {
            name: value
            for name, value in os.environ.items()
            if name in {"PATH", "LANG", "LC_ALL"}
        }
        env["HOME"] = str(self.workspace_tools.root)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_AUTHOR_NAME"] = self.settings.workspace_git_author_name
        env["GIT_AUTHOR_EMAIL"] = self.settings.workspace_git_author_email
        env["GIT_COMMITTER_NAME"] = self.settings.workspace_git_author_name
        env["GIT_COMMITTER_EMAIL"] = self.settings.workspace_git_author_email
        return env

    @contextmanager
    def _git_auth(self, token: str, env: dict[str, str]):
        with tempfile.TemporaryDirectory(prefix="github-askpass-") as temp_dir:
            askpass_path = Path(temp_dir) / "askpass.py"
            askpass_path.write_text(
                "\n".join(
                    [
                        f"#!{sys.executable}",
                        "import os",
                        "import sys",
                        "prompt = sys.argv[1].lower() if len(sys.argv) > 1 else ''",
                        "if 'username' in prompt:",
                        "    print('x-access-token')",
                        "else:",
                        "    print(os.environ['PROJECT_GIT_TOKEN'])",
                    ]
                ),
                encoding="utf-8",
            )
            askpass_path.chmod(0o700)
            command_env = dict(env)
            command_env["GIT_ASKPASS"] = str(askpass_path)
            command_env["PROJECT_GIT_TOKEN"] = token
            yield command_env

    def _create_or_get_pull_request(
        self,
        project: GitHubProjectSettings,
        branch: str,
        title: str,
    ) -> dict:
        try:
            return self._github_request(
                project=project,
                method="POST",
                path=f"/repos/{project.repo}/pulls",
                payload={
                    "title": title,
                    "head": branch,
                    "base": project.base_branch,
                    "body": "Created by Telegram AI Assistant.",
                    "maintainer_can_modify": True,
                },
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 422:
                raise
            existing = self._find_open_pull_request(project, branch)
            if existing:
                return existing
            raise

    def _find_open_pull_request(self, project: GitHubProjectSettings, branch: str) -> dict | None:
        owner = project.repo.split("/", 1)[0]
        query = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open"})
        pulls = self._github_request(
            project=project,
            method="GET",
            path=f"/repos/{project.repo}/pulls?{query}",
            payload=None,
        )
        return pulls[0] if pulls else None

    def _github_request(
        self,
        project: GitHubProjectSettings,
        method: str,
        path: str,
        payload: dict | None,
    ):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url=f"https://api.github.com{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {project.token}",
                "Content-Type": "application/json",
                "User-Agent": "telegram-ai-assistant",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}

    def _format_git_output(self, title: str, result: subprocess.CompletedProcess) -> str:
        output = self._sanitize_known_secrets(result.stdout.strip()) or "Sin salida relevante."
        return (
            f"{title}.\n\n"
            f"Resultado: exit code {result.returncode}\n\n"
            f"Salida relevante:\n{output[-self.settings.workspace_max_output_chars:]}"
        )

    def _sanitize(self, value: str, project: GitHubProjectSettings) -> str:
        return value.replace(project.token, "***")

    def _sanitize_known_secrets(self, value: str) -> str:
        sanitized = value
        for project in self.settings.github_projects.values():
            sanitized = sanitized.replace(project.token, "***")
        return sanitized

    def _usage(self) -> str:
        return (
            "Usa:\n"
            "/github list\n"
            "/github <perfil> clone\n"
            "/github <perfil> status\n"
            "/github <perfil> push-pr <titulo>"
        )


@contextmanager
def _null_context(value):
    yield value
