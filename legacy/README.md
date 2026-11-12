# Legacy Azure Assets (deprecated)

Everything in this directory belonged to the original **Azure-based
deployment** of the AI Document Review accelerator and is **no longer part of
the running application**. The application now runs as a single local
container with an OpenAI-compatible LLM endpoint — see
[docs/local_deployment.md](../docs/local_deployment.md) and the migration plan
[docs/local-deployment-plan.md](../docs/local-deployment-plan.md).

These files are kept only for historical reference and for teams that still
need to tear down or audit the old Azure infrastructure. They are **not
maintained**, do not build, and their Azure SDK dependencies are no longer
declared in any requirements file.

| Path | Former purpose | Replaced by |
|---|---|---|
| `infra/` | Terraform (azurerm/azapi) for App Service, Cosmos DB, Storage, Entra, AML | root `Dockerfile` + `docker-compose.yml` |
| `task/` | Old Taskfile includes (`az`, `terraform`, `pfazure`, `mkcert`) | root `Taskfile.yml` (local tasks) |
| `github/` | CI workflow that deployed to Azure via Terraform | none (local builds) |
| `devcontainer/` | Dev container wired to the Azure toolchain | local venv (`task api-install`) |
| `docs/promptflow/` | PromptFlow agent/eval design guides | `flows/ai_doc_review/prompts/` + `docs/architecture.md` |
| `flows/ai_doc_review_eval/` | PromptFlow evaluation flow | `eval/` (reads local SQLite) |
| `flows/ai_doc_review/{flows,process,process_streaming}.py`, `flow.dag.yaml`, `flow.meta.yaml`, `deployment.yaml`, `model.yaml`, `Dockerfile`, `agent_template/` | PromptFlow DAG + Azure ML online-endpoint packaging | `flows/ai_doc_review/{engine,pipeline,llm,text}.py` |

Do not add new code here. If an asset becomes fully obsolete, delete it in a
dedicated commit instead.
