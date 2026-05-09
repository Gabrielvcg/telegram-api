from pathlib import Path

from assistant.config import Settings


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
