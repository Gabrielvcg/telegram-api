import json
import re
from dataclasses import dataclass

from assistant.config import Settings
from assistant.services.claude import ClaudeService
from assistant.tools.workspace import CommandResult, WorkspaceTools


WORKSPACE_AGENT_PROMPT = """
Actua como un agente de desarrollo de software ejecutando trabajo dentro de un workspace aislado.

Reglas:
- Solo puedes trabajar dentro del workspace actual.
- No generes ni uses secretos reales.
- No toques rutas absolutas del host, runtime del bot ni carpetas fuera del workspace.
- Si necesitas crear una app, crea una carpeta bajo projects/<nombre>.
- Usa scratch/ para pruebas temporales.
- Para peticiones amplias, ejecuta el flujo completo dentro del workspace: inspeccionar, crear o editar, verificar, y dejar Git ordenado cuando proceda.
- Puedes hacer lo necesario dentro del workspace si esta relacionado con la tarea.
- Si trabajas en un proyecto Git, revisa estado antes/despues.
- Si creas o implementas una unidad coherente y la verificacion pasa, puedes crear un commit local.
- Usa ramas por feature con nombre agent/<short-task-name> cuando el proyecto sea Git o inicialices Git.
- Si un proyecto esta en main y vas a tocar codigo, crea o usa una rama agent/<short-task-name> antes de editar.
- No hagas push, deploy, ni acciones externas salvo peticion explicita de Gabriel.
- No pegues patches ni diffs completos en la respuesta.
- Devuelve SOLO JSON valido, sin markdown.

Formato JSON:
{
  "summary": "Resumen corto del trabajo",
  "expected_flow": ["paso 1", "paso 2"],
  "script": "script POSIX sh para ejecutar dentro del workspace",
  "verification": ["comando o comprobacion esperada"],
  "git_policy": "que hiciste o esperas hacer con git"
}

El script debe ser autocontenido, prudente y ejecutable con /bin/sh desde la raiz del workspace.
"""


REPAIR_AGENT_PROMPT = """
El intento anterior de trabajo en workspace fallo o no termino correctamente.

Debes devolver un nuevo JSON valido con un script de reparacion incremental.

Reglas adicionales:
- No repitas trabajo destructivo si ya hay archivos creados.
- Conserva los cambios utiles del intento anterior.
- Usa la salida del comando anterior para corregir la causa raiz.
- Si no se puede reparar sin credenciales, red, secretos o acceso fuera del workspace, devuelve un script que solo inspeccione estado y documente el bloqueo en scratch/agent-blocker.txt.
- No hagas push, deploy ni acciones externas.
"""

REVIEW_AGENT_PROMPT = """
Actua como un senior engineer revisando un proyecto dentro de un workspace aislado.

Reglas:
- No ejecutes comandos ni propongas scripts.
- Analiza arquitectura, DX, seguridad, observabilidad, testabilidad y UX del bot.
- Entrega mejoras priorizadas, concretas y accionables.
- Usa espanol claro, tecnico y conciso.
- Si detectas huecos de informacion, dilo explicitamente.
"""

JSON_RECOVERY_PROMPT = """
Convierte la respuesta previa a JSON valido estricto.

Devuelve SOLO JSON con estas claves:
- summary (string)
- expected_flow (array de strings)
- script (string)
- verification (array de strings)
- git_policy (string)

No incluyas markdown, comentarios ni texto adicional.
"""


@dataclass(frozen=True)
class AgentAttempt:
    number: int
    plan: dict
    result: CommandResult


class WorkspaceAgentService:
    def __init__(self, settings: Settings, claude: ClaudeService, workspace_tools: WorkspaceTools):
        self.settings = settings
        self.claude = claude
        self.workspace_tools = workspace_tools

    def execute_objective(self, objective: str) -> str:
        self.workspace_tools.bootstrap()
        context = self._build_initial_context(objective)
        attempts: list[AgentAttempt] = []

        for attempt_number in range(1, self.settings.workspace_agent_max_attempts + 1):
            raw_plan = self.claude.create_message(
                messages=[{"role": "user", "content": context}],
                extra_system_prompt=self._system_prompt_for_attempt(attempt_number),
                max_tokens=self.settings.plan_max_tokens,
            )
            plan = self._parse_plan_with_recovery(raw_plan, context, attempt_number)
            result = self.workspace_tools.run_command(plan["script"])
            attempt = AgentAttempt(number=attempt_number, plan=plan, result=result)
            attempts.append(attempt)

            if result.exit_code == 0:
                return self._format_result(objective, attempts, completed=True)

            if attempt_number < self.settings.workspace_agent_max_attempts:
                context = self._build_repair_context(objective, attempts)

        return self._format_result(objective, attempts, completed=False)

    def review_objective(self, objective: str) -> str:
        self.workspace_tools.bootstrap()
        instructions = self.workspace_tools.read_file("AGENTS.md", max_chars=6000)
        files = self.workspace_tools.list_files(".", limit=180)
        path_evidence = self._build_review_path_evidence(objective)
        file_evidence = self._build_review_file_evidence(objective)
        deterministic_facts = self._build_review_facts(objective)
        fact_matrix = self._build_review_fact_matrix(objective)
        review_context = (
            f"Objetivo de revision:\n{objective}\n\n"
            f"Instrucciones del workspace:\n{instructions}\n\n"
            f"Arbol visible del workspace:\n{files}\n\n"
            f"Evidencia de rutas objetivo:\n{path_evidence}\n\n"
            f"Evidencia de archivos clave:\n{file_evidence}\n\n"
            f"Hechos deterministas detectados:\n{deterministic_facts}\n\n"
            f"Matriz de hechos verificables:\n{fact_matrix}\n\n"
            "Regla critica:\n"
            "- No afirmes que un proyecto o ruta no existe si la evidencia anterior muestra que existe.\n"
            "- Usa la evidencia de archivos para evitar sugerencias genericas sin base.\n"
            "- Si un riesgo depende de un hecho no comprobado, marcalo como hipotesis y no como hecho.\n"
            "- Cada riesgo o mejora debe citar al menos una evidencia (archivo o matriz).\n"
            "- Si no hay evidencia concreta, usa etiqueta [HIPOTESIS].\n"
            "- Si falta informacion, pide inspeccion adicional concreta, no inventes estado.\n\n"
            "Devuelve una revision con este formato:\n"
            "1) Estado actual\n"
            "2) Riesgos y fricciones\n"
            "3) Mejoras priorizadas (P0/P1/P2)\n"
            "4) Siguiente paso concreto"
        )
        answer = self.claude.create_message(
            messages=[{"role": "user", "content": review_context}],
            extra_system_prompt=REVIEW_AGENT_PROMPT,
            max_tokens=self.settings.plan_max_tokens,
        )
        return f"Revision completada.\n\n{answer}"

    def _build_review_path_evidence(self, objective: str) -> str:
        candidates = self._extract_workspace_paths(objective)
        if not candidates:
            return "Sin rutas explicitas en el objetivo."

        blocks: list[str] = []
        for candidate in candidates[:6]:
            normalized = candidate.strip().strip(".,;:()[]{}")
            if not normalized:
                continue

            path = self.workspace_tools.root / normalized
            try:
                resolved = path.resolve()
            except OSError:
                blocks.append(f"[{normalized}] no resolvible.")
                continue

            if resolved != self.workspace_tools.root and not resolved.is_relative_to(self.workspace_tools.root):
                blocks.append(f"[{normalized}] fuera del workspace permitido.")
                continue

            if not resolved.exists():
                blocks.append(f"[{normalized}] no existe.")
                continue

            display = str(resolved.relative_to(self.workspace_tools.root)).replace("\\", "/")
            kind = "directorio" if resolved.is_dir() else "archivo"
            listing = ""
            if resolved.is_dir():
                listing = self.workspace_tools.list_files(display, limit=40)
            else:
                preview = self.workspace_tools.read_file(display, max_chars=800)
                listing = f"Preview:\n{preview}"
            blocks.append(
                f"[{normalized}] existe ({kind}) -> {display}\n"
                f"{listing}"
            )

        return "\n\n".join(blocks) if blocks else "Sin evidencia concreta de rutas objetivo."

    def _extract_workspace_paths(self, objective: str) -> list[str]:
        matches = re.findall(r"(projects/[^\s`\"']+|scratch/[^\s`\"']+)", objective)
        ordered_unique: list[str] = []
        for value in matches:
            if value not in ordered_unique:
                ordered_unique.append(value)
        return ordered_unique

    def _build_review_file_evidence(self, objective: str) -> str:
        targets = [
            "README.md",
            ".env.example",
            "requirements.txt",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "bot.py",
            "assistant/app.py",
            "assistant/handlers.py",
            "assistant/services/agent.py",
            "assistant/services/workspace_agent.py",
            ".github/workflows/ci.yml",
            ".github/workflows/deploy.yml",
        ]
        paths = self._extract_workspace_paths(objective)
        if not paths:
            paths = ["projects/telegram-ai-assistant"]

        blocks: list[str] = []
        for base in paths[:3]:
            cleaned_base = base.strip().strip(".,;:()[]{}")
            if not cleaned_base:
                continue
            resolved_base = self.workspace_tools.root / cleaned_base
            try:
                resolved_base = resolved_base.resolve()
            except OSError:
                continue
            if (
                resolved_base != self.workspace_tools.root
                and not resolved_base.is_relative_to(self.workspace_tools.root)
            ) or not resolved_base.exists() or not resolved_base.is_dir():
                continue

            existing_files = []
            for relative_file in targets:
                candidate = resolved_base / relative_file
                if candidate.exists() and candidate.is_file():
                    display = str(candidate.relative_to(self.workspace_tools.root)).replace("\\", "/")
                    excerpt = self.workspace_tools.read_file(display, max_chars=900)
                    existing_files.append(
                        f"### {display}\n{excerpt}"
                    )
                if len(existing_files) >= 8:
                    break

            if existing_files:
                blocks.append(
                    f"Proyecto: {cleaned_base}\n"
                    + "\n\n".join(existing_files)
                )

        return "\n\n".join(blocks) if blocks else "No se detectaron archivos clave legibles para este objetivo."

    def _build_review_facts(self, objective: str) -> str:
        paths = self._extract_workspace_paths(objective)
        if not paths:
            paths = ["projects/telegram-ai-assistant"]

        project_root = None
        for raw_base in paths:
            cleaned_base = raw_base.strip().strip(".,;:()[]{}")
            if not cleaned_base:
                continue
            candidate = (self.workspace_tools.root / cleaned_base).resolve()
            if (
                candidate.exists()
                and candidate.is_dir()
                and (
                    candidate == self.workspace_tools.root
                    or candidate.is_relative_to(self.workspace_tools.root)
                )
            ):
                project_root = candidate
                break

        if project_root is None:
            return "- Proyecto objetivo no resoluble en workspace."

        facts: list[str] = []
        rel = lambda path: str(path.relative_to(self.workspace_tools.root)).replace("\\", "/")

        required_markers = [
            "README.md",
            "requirements.txt",
            "Dockerfile",
            "docker-compose.yml",
            ".env.example",
        ]
        for marker in required_markers:
            marker_path = project_root / marker
            facts.append(
                f"- {'OK' if marker_path.exists() else 'MISSING'}: {rel(marker_path)}"
            )

        workflows_dir = project_root / ".github" / "workflows"
        if workflows_dir.exists() and workflows_dir.is_dir():
            workflow_files = sorted(item.name for item in workflows_dir.glob("*.yml"))
            facts.append(
                f"- CI workflows: {', '.join(workflow_files) if workflow_files else 'none'}"
            )
        else:
            facts.append("- CI workflows: directory missing")

        requirements_path = project_root / "requirements.txt"
        if requirements_path.exists():
            content = requirements_path.read_text(encoding="utf-8", errors="replace")
            non_empty = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            unpinned = [
                line
                for line in non_empty
                if "==" not in line and line.startswith("-e ") is False
            ]
            facts.append(f"- requirements entries: {len(non_empty)}")
            facts.append(f"- requirements non pinned entries: {len(unpinned)}")

        workspace_tool_path = project_root / "assistant" / "tools" / "workspace.py"
        if workspace_tool_path.exists():
            ws_content = workspace_tool_path.read_text(encoding="utf-8", errors="replace")
            has_safe_path = "_safe_path(" in ws_content
            has_relative_check = "is_relative_to" in ws_content
            has_validate_command = "_validate_command(" in ws_content
            facts.append(f"- workspace path guard (_safe_path): {'yes' if has_safe_path else 'no'}")
            facts.append(f"- workspace relative guard (is_relative_to): {'yes' if has_relative_check else 'no'}")
            facts.append(f"- workspace command validation: {'yes' if has_validate_command else 'no'}")
        else:
            facts.append("- workspace tools file not found for command/path guard checks")

        tests_dir = project_root / "tests"
        if tests_dir.exists() and tests_dir.is_dir():
            test_files = [path for path in tests_dir.rglob("test_*.py")]
            facts.append(f"- tests directory: yes ({len(test_files)} test files)")
        else:
            facts.append("- tests directory: no")

        logging_cfg = project_root / "assistant" / "logging_config.py"
        if logging_cfg.exists():
            log_content = logging_cfg.read_text(encoding="utf-8", errors="replace")
            looks_json = "json" in log_content.lower() and "formatter" in log_content.lower()
            facts.append(f"- structured logging hint: {'yes' if looks_json else 'no/unknown'}")
        else:
            facts.append("- logging config file: missing")

        return "\n".join(facts)

    def _build_review_fact_matrix(self, objective: str) -> str:
        paths = self._extract_workspace_paths(objective)
        if not paths:
            paths = ["projects/telegram-ai-assistant"]

        root = None
        for raw_base in paths:
            cleaned_base = raw_base.strip().strip(".,;:()[]{}")
            if not cleaned_base:
                continue
            candidate = (self.workspace_tools.root / cleaned_base).resolve()
            if (
                candidate.exists()
                and candidate.is_dir()
                and (
                    candidate == self.workspace_tools.root
                    or candidate.is_relative_to(self.workspace_tools.root)
                )
            ):
                root = candidate
                break

        if root is None:
            return "- FACT: project root not resolved | EVIDENCE: objective path missing in workspace"

        def rel(path):
            return str(path.relative_to(self.workspace_tools.root)).replace("\\", "/")

        lines: list[str] = []
        handlers_path = root / "assistant" / "handlers.py"
        if handlers_path.exists():
            handlers_content = handlers_path.read_text(encoding="utf-8", errors="replace")
            command_checks = [
                "CommandHandler(\"status\"",
                "CommandHandler(\"reset\"",
                "CommandHandler(\"help\"",
                "CommandHandler(\"agent\"",
                "CommandHandler(\"review\"",
            ]
            for marker in command_checks:
                status = "YES" if marker in handlers_content else "NO"
                lines.append(
                    f"- FACT: command {marker} registered={status} | EVIDENCE: {rel(handlers_path)}"
                )
        else:
            lines.append("- FACT: handlers file missing | EVIDENCE: assistant/handlers.py not found")

        workspace_tool_path = root / "assistant" / "tools" / "workspace.py"
        if workspace_tool_path.exists():
            content = workspace_tool_path.read_text(encoding="utf-8", errors="replace")
            checks = [
                ("_safe_path(", "workspace path guard"),
                ("is_relative_to", "workspace relative guard"),
                ("_validate_command(", "workspace command validator"),
            ]
            for marker, label in checks:
                status = "YES" if marker in content else "NO"
                lines.append(
                    f"- FACT: {label}={status} | EVIDENCE: {rel(workspace_tool_path)}"
                )
        else:
            lines.append("- FACT: workspace guards unknown | EVIDENCE: assistant/tools/workspace.py missing")

        tests_dir = root / "tests"
        tests_count = len(list(tests_dir.rglob("test_*.py"))) if tests_dir.exists() else 0
        lines.append(
            f"- FACT: tests_present={'YES' if tests_count > 0 else 'NO'} count={tests_count} | EVIDENCE: {rel(tests_dir) if tests_dir.exists() else 'tests/ missing'}"
        )

        workflows_dir = root / ".github" / "workflows"
        workflow_count = len(list(workflows_dir.glob("*.yml"))) if workflows_dir.exists() else 0
        lines.append(
            f"- FACT: workflows_present={'YES' if workflow_count > 0 else 'NO'} count={workflow_count} | EVIDENCE: {rel(workflows_dir) if workflows_dir.exists() else '.github/workflows missing'}"
        )

        requirements_path = root / "requirements.txt"
        if requirements_path.exists():
            req = requirements_path.read_text(encoding="utf-8", errors="replace")
            rows = [line.strip() for line in req.splitlines() if line.strip() and not line.strip().startswith("#")]
            pinned = [line for line in rows if "==" in line]
            lines.append(
                f"- FACT: requirements_pinned={len(pinned)}/{len(rows)} | EVIDENCE: {rel(requirements_path)}"
            )
        else:
            lines.append("- FACT: requirements file missing | EVIDENCE: requirements.txt not found")

        return "\n".join(lines)

    def _build_initial_context(self, objective: str) -> str:
        instructions = self.workspace_tools.read_file("AGENTS.md", max_chars=6000)
        files = self.workspace_tools.list_files(".", limit=120)
        return (
            f"Objetivo del usuario:\n{objective}\n\n"
            f"Instrucciones del workspace:\n{instructions}\n\n"
            f"Arbol visible del workspace:\n{files}\n"
        )

    def _build_repair_context(self, objective: str, attempts: list[AgentAttempt]) -> str:
        latest_attempt = attempts[-1]
        files = self.workspace_tools.list_files(".", limit=160)
        return (
            f"Objetivo original del usuario:\n{objective}\n\n"
            f"El intento #{latest_attempt.number} fallo con exit code {latest_attempt.result.exit_code}.\n\n"
            f"Resumen del plan fallido:\n{latest_attempt.plan.get('summary', '')}\n\n"
            f"Flujo esperado del plan fallido:\n{self._format_sequence(latest_attempt.plan.get('expected_flow', []))}\n\n"
            f"Politica Git declarada:\n{latest_attempt.plan.get('git_policy', '')}\n\n"
            f"Ficheros tocados por el intento fallido:\n{self._format_files(latest_attempt.result.changed_files)}\n\n"
            f"Salida relevante del comando fallido:\n{latest_attempt.result.output or 'Sin salida relevante.'}\n\n"
            f"Arbol visible actual del workspace:\n{files}\n\n"
            "Devuelve un nuevo plan JSON con un script de reparacion incremental."
        )

    def _system_prompt_for_attempt(self, attempt_number: int) -> str:
        if attempt_number == 1:
            return WORKSPACE_AGENT_PROMPT
        return f"{WORKSPACE_AGENT_PROMPT}\n\n{REPAIR_AGENT_PROMPT}"

    def _parse_plan(self, raw_plan: str) -> dict:
        text = raw_plan.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()
        try:
            plan = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Claude no devolvio un plan JSON ejecutable.") from exc

        required_keys = {"summary", "expected_flow", "script", "verification"}
        missing = required_keys - set(plan)
        if missing:
            raise ValueError(f"Plan incompleto. Faltan claves: {', '.join(sorted(missing))}")
        if not isinstance(plan["script"], str) or not plan["script"].strip():
            raise ValueError("Plan sin script ejecutable.")
        return plan

    def _parse_plan_with_recovery(self, raw_plan: str, context: str, attempt_number: int) -> dict:
        try:
            return self._parse_plan(raw_plan)
        except ValueError:
            recovery_input = (
                f"Contexto original:\n{context}\n\n"
                f"Intento de respuesta no valido:\n{raw_plan}\n\n"
                "Reescribe a JSON valido."
            )
            repaired = self.claude.create_message(
                messages=[{"role": "user", "content": recovery_input}],
                extra_system_prompt=JSON_RECOVERY_PROMPT,
                max_tokens=self.settings.plan_max_tokens,
            )
            try:
                return self._parse_plan(repaired)
            except ValueError as exc:
                raise ValueError(
                    f"Claude no devolvio un plan JSON ejecutable en el intento {attempt_number}."
                ) from exc

    def _format_result(self, objective: str, attempts: list[AgentAttempt], completed: bool) -> str:
        latest_attempt = attempts[-1]
        latest_plan = latest_attempt.plan
        latest_result = latest_attempt.result
        status = "completado" if completed else "terminado con errores"
        changed_files = self._format_all_changed_files(attempts)
        expected_flow = self._format_sequence(latest_plan.get("expected_flow", []))
        verification = self._format_sequence(latest_plan.get("verification", []))
        git_policy = latest_plan.get("git_policy", "Sin accion Git declarada.")
        attempt_summary = self._format_attempt_summary(attempts)
        output = latest_result.output or "Sin salida relevante."

        return (
            f"Trabajo de agente {status}.\n\n"
            f"Objetivo:\n{objective}\n\n"
            f"Resumen:\n{latest_plan['summary']}\n\n"
            f"Intentos:\n{attempt_summary}\n\n"
            f"Flujo aplicado:\n{expected_flow}\n\n"
            f"Ficheros tocados:\n{changed_files}\n\n"
            f"Git:\n{git_policy}\n\n"
            f"Verificacion:\n{verification}\n\n"
            f"Resultado final: exit code {latest_result.exit_code}\n"
            f"Salida relevante:\n{output}"
        )

    def _format_attempt_summary(self, attempts: list[AgentAttempt]) -> str:
        return "\n".join(
            f"- Intento {attempt.number}: exit code {attempt.result.exit_code} - "
            f"{attempt.plan.get('summary', 'Sin resumen')}"
            for attempt in attempts
        )

    def _format_all_changed_files(self, attempts: list[AgentAttempt]) -> str:
        changed_files = sorted({
            path
            for attempt in attempts
            for path in attempt.result.changed_files
        })
        return self._format_files(changed_files)

    def _format_files(self, changed_files: list[str]) -> str:
        return "\n".join(f"- {path}" for path in changed_files) or "- Sin cambios detectados"

    def _format_sequence(self, items: object) -> str:
        if isinstance(items, str):
            normalized_items = [items]
        elif isinstance(items, list):
            normalized_items = [str(item) for item in items]
        else:
            normalized_items = []
        return "\n".join(f"- {item}" for item in normalized_items) or "- Sin pasos declarados"
