# AgentGuard real smoke test

This smoke environment starts only the components needed for the nono AgentGuard loop:

- Kafka
- PostgreSQL
- Redis
- MinIO
- baseline-adjudication
- ai-agent
- web-ui

It does not start dotCMS, OpenRASP, Falco, Suricata, or Elasticsearch app stacks.

## 1. Export LLM configuration

```bash
export OPENAI_MODEL=deepseek-v3-2-251201
export OPENAI_API_KEY='<your-api-key>'
export OPENAI_BASE_URL='https://ark.cn-beijing.volces.com/api/v3'
```

## 2. Start the real environment

```bash
docker compose -f deploy/docker-compose-agentguard.yml up -d --build
```

If your host uses the legacy Compose binary, replace `docker compose` with `docker-compose` in the commands below.

Wait until these services are up:

```bash
docker compose -f deploy/docker-compose-agentguard.yml ps
```

Useful URLs:

```text
Web UI:        http://localhost:30003
Backend API:   http://localhost:8000
MinIO Console: http://localhost:9001
MinIO login:   minioadmin / minioadmin
```

## 3. Prepare host-side nono shim dependencies

The nono command is executed on the host. The shim publishes to Kafka and writes diff evidence to MinIO, so the host Python environment needs:

```bash
python -m pip install boto3 aiokafka
```

If the real nono binary is not at `$HOME/.local/bin/nono`, set it explicitly:

```bash
export DEEPXDR_REAL_NONO=/path/to/real/nono
```

For the real known-agent smoke case, install OpenCode and its nono profile:

```bash
npm install -g opencode-ai --registry=https://registry.npmjs.org
nono pull always-further/opencode
```

## 4. Run real nono commands for all three strategies

```bash
./scripts/agentguard-smoke-nono.sh small
./scripts/agentguard-smoke-nono.sh medium
./scripts/agentguard-smoke-nono.sh large
./scripts/agentguard-smoke-nono.sh agent
```

The AgentGuard compose sets these planning thresholds so the smoke cases
exercise different context strategies:

```text
AGENT_GUARD_SMALL_DIFF_TOKEN_LIMIT=200
AGENT_GUARD_MEDIUM_DIFF_TOKEN_LIMIT=800
AGENT_GUARD_FILE_TOKEN_LIMIT=300
AGENT_GUARD_HUNK_TOKEN_LIMIT=80
```

Expected strategy coverage:

```text
small   README-only wording change              file_level
medium  service.py + policy.yaml medium diff    hunk_summary
large   generated_policy.json large diff        risk_only
agent   real opencode agent edits README.md     hunk_summary
```

The script prepares `.tmp/agentguard-smoke-workspace` for the selected case and
runs one of:

```bash
scripts/nono run --rollback --no-rollback-prompt --allow .tmp/agentguard-smoke-workspace -- /bin/sh -c "cp after/README.md README.md"
scripts/nono run --rollback --no-rollback-prompt --allow .tmp/agentguard-smoke-workspace -- /bin/sh -c "cp after/service.py service.py && cp after/policy.yaml policy.yaml"
scripts/nono run --rollback --no-rollback-prompt --allow .tmp/agentguard-smoke-workspace -- /bin/sh -c "cp after/generated_policy.json generated_policy.json"
scripts/nono run --profile always-further/opencode --rollback --no-rollback-prompt --allow .tmp/agentguard-smoke-workspace -- /bin/sh -c "opencode run --model deepxdr/deepseek-v3-2-251201 --auto ..."
```

The `agent` case installs/runs a real known coding agent, `opencode`, under
nono's registry-managed `always-further/opencode` profile. The smoke workspace
contains an `opencode.json` provider config for the OpenAI-compatible Ark
endpoint. The script requires `OPENAI_API_KEY` to be present in the shell for
this real-agent case.

Expected effects:

- real nono creates a rollback session
- the shim extracts `nono rollback show <session_id> --diff`
- the shim writes diff evidence to MinIO bucket `agent-diffs`
- the shim publishes an `agent_session` event to Kafka topic `events`
- baseline-adjudication routes it to `agent.session.finished`
- ai-agent AgentGuard consumes it, runs LangGraph adjudication, and stores the session in PostgreSQL
- Web UI shows the Agent Guard session

## 5. Confirm in Web UI and execute rollback

Open:

```text
http://localhost:30003
```

In `Agent Guard Sessions`:

1. Find the smoke run.
2. Confirm it has an adjudication summary.
3. Click `执行回退`.
4. Wait for rollback status to become completed.

After rollback, the host workspace file should return to its before-state content.
For the small case:

```bash
cat .tmp/agentguard-smoke-workspace/README.md
```

Expected:

```text
old title
```

## 6. Debug commands

Backend logs:

```bash
docker compose -f deploy/docker-compose-agentguard.yml logs -f ai-agent
```

Baseline logs:

```bash
docker compose -f deploy/docker-compose-agentguard.yml logs -f baseline-adjudication
```

Web UI logs:

```bash
docker compose -f deploy/docker-compose-agentguard.yml logs -f web-ui
```

Kafka topics:

```bash
docker compose -f deploy/docker-compose-agentguard.yml exec kafka \
  kafka-topics.sh --bootstrap-server kafka:9092 --list
```

Stop and remove the smoke environment:

```bash
docker compose -f deploy/docker-compose-agentguard.yml down
```
