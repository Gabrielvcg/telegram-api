import json
import re

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


class WorkspaceAgentService:
    def __init__(self, claude: ClaudeService, workspace_tools: WorkspaceTools):
        self.claude = claude
        self.workspace_tools = workspace_tools

    def execute_objective(self, objective: str) -> str:
        self.workspace_tools.bootstrap()
        context = self._build_context(objective)
        raw_plan = self.claude.create_message(
            messages=[{"role": "user", "content": context}],
            extra_system_prompt=WORKSPACE_AGENT_PROMPT,
            max_tokens=2200,
        )
        plan = self._parse_plan(raw_plan)
        result = self.workspace_tools.run_command(plan["script"])
        return self._format_result(plan, result)

    def _build_context(self, objective: str) -> str:
        instructions = self.workspace_tools.read_file("AGENTS.md", max_chars=6000)
        files = self.workspace_tools.list_files(".", limit=120)
        return (
            f"Objetivo del usuario:\n{objective}\n\n"
            f"Instrucciones del workspace:\n{instructions}\n\n"
            f"Arbol visible del workspace:\n{files}\n"
        )

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

    def _format_result(self, plan: dict, result: CommandResult) -> str:
        changed_files = "\n".join(f"- {path}" for path in result.changed_files) or "- Sin cambios detectados"
        expected_flow = "\n".join(f"- {step}" for step in plan.get("expected_flow", []))
        verification = "\n".join(f"- {step}" for step in plan.get("verification", []))
        git_policy = plan.get("git_policy", "Sin accion Git declarada.")
        output = result.output or "Sin salida relevante."

        return (
            f"Trabajo ejecutado en workspace.\n\n"
            f"Resumen:\n{plan['summary']}\n\n"
            f"Flujo esperado:\n{expected_flow}\n\n"
            f"Ficheros tocados:\n{changed_files}\n\n"
            f"Git:\n{git_policy}\n\n"
            f"Verificacion esperada:\n{verification}\n\n"
            f"Resultado del comando: exit code {result.exit_code}\n"
            f"Salida relevante:\n{output}"
        )
