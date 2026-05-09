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
            plan = self._parse_plan(raw_plan)
            result = self.workspace_tools.run_command(plan["script"])
            attempt = AgentAttempt(number=attempt_number, plan=plan, result=result)
            attempts.append(attempt)

            if result.exit_code == 0:
                return self._format_result(objective, attempts, completed=True)

            if attempt_number < self.settings.workspace_agent_max_attempts:
                context = self._build_repair_context(objective, attempts)

        return self._format_result(objective, attempts, completed=False)

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
