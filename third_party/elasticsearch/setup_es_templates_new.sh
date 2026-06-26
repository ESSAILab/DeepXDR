#!/bin/bash
ES_URL="http://localhost:9201"

# 使用数组定义需要处理的模块
modules=("openrasp" "falco" "suricata")

for mod in "${modules[@]}"; do
    echo "正在配置 ${mod} 模板..."
    curl -X PUT "$ES_URL/_index_template/${mod}_template" -H 'Content-Type: application/json' -d"
    {
      \"index_patterns\": [\"${mod}-alerts-*\"],
      \"template\": {
        \"aliases\": { \"${mod}-alerts\": {} },
        \"settings\": {
          \"number_of_shards\": 1,
          \"number_of_replicas\": 0
        }
      }
    }"
done

echo -e "\n正在刷新别名关联..."
curl -X POST "$ES_URL/_aliases" -H 'Content-Type: application/json' -d'
{
  "actions": [
    { "add": { "index": "openrasp-alerts-*", "alias": "openrasp-alerts" } },
    { "add": { "index": "falco-alerts-*", "alias": "falco-alerts" } },
    { "add": { "index": "suricata-alerts-*", "alias": "suricata-alerts" } }
  ]
}'
