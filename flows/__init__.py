"""Flows package: document review pipelines (local, OpenAI-compatible LLM).

The legacy Azure ML / PromptFlow assets (ai_doc_review/{flows,process}*.py,
agent_template/, *.yaml) are pending migration to legacy/ — see
docs/local-deployment-plan.md §6. The active pipeline entry point is
flows.ai_doc_review.engine.stream_review.
"""
