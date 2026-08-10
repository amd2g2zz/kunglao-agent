# Spec Delta — cleanup-routing-module

## REMOVED Requirements

### Requirement: Method routing (Dijkstra path selection)

The orchestrator selected analysis methods for each action via a Dijkstra path search over a method-graph (nodes = skills/tools/MCPs, edges = alternative/sequence), routing around downed tools with zero LLM calls, escalating to LLM graph-growth only on graph break. Supported by `scripts/method_router.py`, `scripts/method_topk.py`, `scripts/method_router_register.py`, and `data/method-graph.yaml`.

**Removed because**: experimentally refuted. In real worker dispatch (gate-telemetry experiment on C-401/C-402), LLM workers self-selected and self-swapped tools throughout (pefile -> xxd -> capstone -> bcrypt_hook); the routing layer added approximately zero value. `kunglao-decide.decide()` now emits `top_actions[].skill = None`; workers self-select tools.

#### Scenario: tool health failure swaps alternative path (REMOVED)
- WHEN a skill is marked "down" in tool_health and an action is routed
- THEN the router previously found an alternative path via Dijkstra over the executable subgraph with zero LLM calls
- THIS BEHAVIOR IS REMOVED; workers now self-select tools with no central routing

#### Scenario: graph break escalates to LLM graph-growth (REMOVED)
- WHEN no reachable executable node exists in the method-graph
- THEN the router previously returned escalated=True for the orchestrator to grow the graph via LLM
- THIS BEHAVIOR IS REMOVED; there is no method-graph and no escalation path

#### Scenario: dynamic registration from environment (REMOVED)
- WHEN method_router_register scanned skills/MCPs/scripts at init time
- THEN it produced data/method-graph.yaml with nodes from the environment
- THIS BEHAVIOR IS REMOVED; the register and graph are deleted
