## Start MCP Client

```bash
export OPENAI_API_KEY=<your-openai-api-key>
export OPENAI_BASE_URL=<your-openai-base-url>
./gradlew bootRun
```

## Ask Questions

```bash
USER: List the indices in the cluster.
ASSISTANT: Here are the indices currently present in the cluster:

1. `.internal.alerts-default.alerts-default-000001`
2. `.internal.alerts-observability.threshold.alerts-default-000001`
3. `.internal.alerts-ml.anomaly-detection-health.alerts-default-000001`
4. `.internal.alerts-observability.metrics.alerts-default-000001`
5. `.internal.alerts-stack.alerts-default-000001`
6. `.internal.alerts-security.alerts-default-000001`
7. `.internal.alerts-observability.slo.alerts-default-000001`
8. `.internal.alerts-ml.anomaly-detection.alerts-default-000001`
9. `.internal.alerts-transform.health.alerts-default-000001`
10. `student`
11. `.internal.alerts-observability.logs.alerts-default-000001`
12. `.internal.alerts-observability.uptime.alerts-default-000001`
13. `.internal.alerts-observability.apm.alerts-default-000001`

If you need more information about any specific index, feel free to ask!

USER: Get student index's mapping.
ASSISTANT: The mapping for the `student` index is as follows:

- **Mappings:**
  - **Properties:**
    - **age:** Type is `long`
    - **major:** Type is `text` with a sub-field `keyword` of type `keyword`, and `ignore_above` set to 256.
    - **name:** Type is `text` with a sub-field `keyword` of type `keyword`, and `ignore_above` set to 256.

- **Settings:**
  - **Index:**
    - Routing:
      - Allocation:
        - Include:
          - `_tier_preference`: `data_content`
    - Number of shards: `1`
    - Provided name: `student`
    - Creation date: `1745300793755`
    - Number of replicas: `1`
    - UUID: `RIsbajmcSwKr8DGFjL0sMQ`
    - Version created: `8521000`

If you need further details or have any other questions, feel free to ask!
```