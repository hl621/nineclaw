#!/bin/bash
# Live API tests for nineclaw-manager
# Run this script after starting the service with: uv run run.py

set -e

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_PREFIX="/v1/container/nineclaw"
TENANT_ID="${TENANT_ID:-default}"

curl_api() {
  curl -s "$@" -H "X-Tenant-ID: ${TENANT_ID}" -H "Content-Type: application/json"
}

echo "=== Nineclaw Manager API Tests ==="
echo "Base URL: ${BASE_URL}${API_PREFIX}"
echo ""

# Test 1: Health Check
echo "Test 1: Health Check"
response=$(curl -s "${BASE_URL}/health")
if [ "$response" = '{"status":"ok"}' ]; then
  echo "  ✓ Health check passed"
else
  echo "  ✗ Health check failed: $response"
  exit 1
fi

# Test 2: List instances (should be empty or have items)
echo ""
echo "Test 2: List Instances"
response=$(curl_api "${BASE_URL}${API_PREFIX}")
if echo "$response" | grep -q '"items"'; then
  total=$(echo "$response" | grep -o '"total":[0-9]*' | grep -o '[0-9]*' | head -1)
  echo "  ✓ List instances passed (total: ${total:-0})"
else
  echo "  ✗ List instances failed: $response"
  exit 1
fi

# Test 3: Create instance
echo ""
echo "Test 3: Create Instance"
response=$(curl_api -X POST "${BASE_URL}${API_PREFIX}" \
  -d '{"name": "test-instance-api"}')
if echo "$response" | grep -q '"id"'; then
  instance_id=$(echo "$response" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
  echo "  ✓ Create instance passed (id: $instance_id)"
else
  echo "  ✗ Create instance failed: $response"
  if echo "$response" | grep -q "Docker operation failed"; then
    echo "  Note: This might be expected if nineclaw image is not available"
  fi
  instance_id=""
fi

# Test 4: Get instance (if created)
if [ -n "$instance_id" ]; then
  echo ""
  echo "Test 4: Get Instance"
  response=$(curl_api "${BASE_URL}${API_PREFIX}/${instance_id}")
  if echo "$response" | grep -q "$instance_id"; then
    echo "  ✓ Get instance passed"
  else
    echo "  ✗ Get instance failed: $response"
  fi

  # Test 5: List instances (should have 1+)
  echo ""
  echo "Test 5: List Instances (should have items)"
  response=$(curl_api "${BASE_URL}${API_PREFIX}")
  if echo "$response" | grep -q '"total":[1-9]'; then
    echo "  ✓ List instances passed (has items)"
  else
    echo "  ✗ List instances failed: $response"
  fi

  # Test 6: Stop instance
  echo ""
  echo "Test 6: Stop Instance"
  response=$(curl_api -X POST "${BASE_URL}${API_PREFIX}/${instance_id}/stop")
  if echo "$response" | grep -q '"id"'; then
    echo "  ✓ Stop instance passed"
  else
    echo "  ✗ Stop instance failed: $response"
  fi

  # Test 7: Start instance
  echo ""
  echo "Test 7: Start Instance"
  response=$(curl_api -X POST "${BASE_URL}${API_PREFIX}/${instance_id}/start")
  if echo "$response" | grep -q '"id"'; then
    echo "  ✓ Start instance passed"
  else
    echo "  ✗ Start instance failed: $response"
  fi

  # Test 8: Restart instance
  echo ""
  echo "Test 8: Restart Instance"
  response=$(curl_api -X POST "${BASE_URL}${API_PREFIX}/${instance_id}/restart")
  if echo "$response" | grep -q '"id"'; then
    echo "  ✓ Restart instance passed"
  else
    echo "  ✗ Restart instance failed: $response"
  fi

  # Test 9: Delete instance
  echo ""
  echo "Test 9: Delete Instance"
  response=$(curl_api -X DELETE "${BASE_URL}${API_PREFIX}/${instance_id}")
  if echo "$response" | grep -q '"deleted"'; then
    echo "  ✓ Delete instance passed"
  else
    echo "  ✗ Delete instance failed: $response"
  fi
fi

# Test 10: Get non-existent instance
echo ""
echo "Test 10: Get Non-existent Instance"
http_code=$(curl -s -o /tmp/nineclaw_test_resp.txt -w "%{http_code}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  "${BASE_URL}${API_PREFIX}/nonexistent-id-12345")
response=$(cat /tmp/nineclaw_test_resp.txt)
rm -f /tmp/nineclaw_test_resp.txt
if [ "$http_code" = "404" ] || echo "$response" | grep -qi 'not found'; then
  echo "  ✓ Get non-existent instance passed (returned 404)"
else
  echo "  Response (HTTP ${http_code}): $response"
fi

echo ""
echo "=== Tests Completed ==="
