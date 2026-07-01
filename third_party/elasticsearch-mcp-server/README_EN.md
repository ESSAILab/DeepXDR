# Elasticsearch MCP Server - Secondary Development Notes

English | [中文](README.md)

## Original Project

This project is a secondary development based on the open-source project [cr7258/elasticsearch-mcp-server](https://github.com/cr7258/elasticsearch-mcp-server/tree/main).

For the complete feature documentation of the original project, please refer to [README_origin.md](README_origin.md).

The original project implements a Model Context Protocol (MCP) server for Elasticsearch/OpenSearch interaction, providing document search, index analysis, and cluster management capabilities. This project extends and enhances the original codebase for EQL query scenarios, AI model adaptation, and containerized deployment.

---

## Image Startup

This service is deployed on the app-side server to provide ES query tools for the AI-Agent threat analysis intelligent agent.

### 1. Docker Compose Configuration Example

The following demonstrates a sample Docker Compose configuration for this image:

```yaml
elasticsearch-mcp-server:
  image: essaigroup/deepxdr-es-mcp-server:v0.3.0-alpha
  container_name: app-elasticsearch-mcp-server
  environment:
    - ELASTICSEARCH_HOSTS=http://es-log-ip:port
    - VERIFY_CERTS=false
    - DISABLE_HIGH_RISK_OPERATIONS=true
    - EQL_MAX_FIELD_LENGTH=1000
    - EQL_MAX_LIST_ITEMS=5
  user: root
  ports:
    - "8000:8000"
  networks:
    - logging_net
  restart: always
  deploy:
    resources:
      limits:
        memory: 512M
      reservations:
        memory: 128M
```

### 2. Environment Variable Parameter Descriptions

| Environment Variable | Required | Default Value | Description |
|----------|------|--------|------|
| `ELASTICSEARCH_HOSTS` | Yes | — | App-side Elasticsearch database address. The `es-log-ip:port` placeholder should be replaced with the actual address |
| `VERIFY_CERTS` | No | `false` | Whether to verify SSL certificates. Recommended to set `false` for internal network environments |
| `DISABLE_HIGH_RISK_OPERATIONS` | No | `true` | Whether to disable high-risk write operations. Recommended to maintain `true` for production environments |
| `EQL_MAX_FIELD_LENGTH` | No | `1000` | Limits the maximum length of a single string in the query response; exceeding portions will be truncated and marked with a `"..."` suffix. Set to `0` to disable length truncation |
| `EQL_MAX_LIST_ITEMS` | No | `5` | Limits the maximum number of items retained in a string list in the query response; exceeding portions will be truncated. Set to `0` to disable list truncation |

### 3. Startup and Verification

Start the service:

```bash
docker-compose up -d elasticsearch-mcp-server
```

View logs:

```bash
docker logs -f app-elasticsearch-mcp-server
```

Verify service availability:

```bash
curl http://localhost:8000/mcp/
```

---

## Image Build

```bash
docker build -f Dockerfile -t essaigroup/deepxdr-es-mcp-server:v0.3.0-alpha .
```

If the image already exists in Docker Hub, this step may be skipped.

---

## Secondary Development Features

### 1. EQL Query Mode Refactoring

The `search_documents` tool has been refactored from the original generic `body` parameter passing to a dedicated **EQL (Event Query Language)** query mode. The client layer now includes EQL search parameter construction logic and directly invokes Elasticsearch's `eql.search` API, compatible with EQL query capabilities in Elasticsearch 7.9+.

**Key Changes:**
- Underlying invocation switched from `client.search()` to `client.eql.search()`
- Default integration of `@timestamp` timestamp field handling
- Support for custom event category mapping via the `event_category_field` parameter

### 2. Full EQL Parameter Support

The `search_documents` tool parameter list has been extended to support the complete EQL API parameter set.

### 3. AI Model Prompt Optimization

Structured usage guidance for AI models has been injected into the `search_documents` tool docstring to reduce parameter misuse rates during large language model invocations. The prompt content covers:

- **`fields` Parameter Format Specification**: Explicitly mandates the `dict` list format and prohibits DSL syntax misuse (e.g., `["*", "-field"]`)
- **Nested Field Access Patterns**: e.g., `{"field": "attack_params.query"}`
- **Event Category Mapping Guidance**: For cloud security probe data, indicates that `event_category_field="type"` should be configured
- **`filter_path` Filtering Techniques**: Supports path exclusion via negative prefix, e.g., `filter_path="-hits.events"`
- **EQL Query Syntax Reference**: Covers 15 core syntax rules including basic queries, sequence queries (`sequence`), span constraints (`maxspan`), correlation key binding (`by`), termination conditions (`until`), missing event queries (`!`), unordered sample matching (`sample`), and pipe operations (`|`)

### 4. Generic Field Truncation Processing

The `src/utils/field_truncate.py` module has been added to perform recursive truncation of string fields in Elasticsearch response results, preventing context window overflow caused by excessively long fields in AI models.

**Functional Characteristics:**
- Recursive traversal of nested dictionaries, lists, and string fields
- Simultaneous adaptation to both EQL response format (`hits.events._source`) and DSL response format (`hits.hits._source`)
- String list truncation support with truncation indicator appended at the end
- Truncation operation log output for debugging and tracing

**Environment Variable Configuration:**

| Environment Variable | Default Value | Description |
|----------|--------|------|
| `EQL_MAX_FIELD_LENGTH` | `1000` | Limits the maximum length of a single string in the query response; exceeding portions will be truncated and marked with a `"..."` suffix. Set to `0` to disable length truncation |
| `EQL_MAX_LIST_ITEMS` | `5` | Limits the maximum number of items retained in a string list in the query response; exceeding portions will be truncated. Set to `0` to disable list truncation |
| `EQL_TRUNCATION_SUFFIX` | `"..."` | Suffix string appended after truncation |

For detailed configuration instructions, please refer to [docs/FIELD_TRUNCATION_CONFIGURATION.md](docs/FIELD_TRUNCATION_CONFIGURATION.md).

### 5. Bug Fixes

- **`filter_path` Parameter Type Fix**: Resolved type compatibility issues triggered when `filter_path` is passed as a `str` type
- **Prompt Position Correction**: Fixed incorrect positioning of certain prompt text segments in the `search_documents` docstring

---

## License

This project inherits the [Apache License 2.0](LICENSE) open-source license from the original project.
