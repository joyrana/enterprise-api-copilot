# JSON Schema Contracts

Shared payload schemas.


## ui-components.json

The generative-UI component contract: name, description, whether the model may select it, the
skills whose output it renders, and the JSON Schema of its props. It is **generated** from
`ai/agent/ui.py` (`python -m ai.agent.ui --write`); never edit it by hand. Tests fail when it is
stale, when the OpenAPI `UIComponent` enum differs from it, or when the web registry
(`apps/frontend/src/components/genui/registry.ts`) has a component the manifest lacks or vice versa.
The server validates every component's props against this schema before returning them.
