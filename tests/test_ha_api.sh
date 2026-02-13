#!/bin/bash
# Home Assistant REST API tests

HA_TOKEN=$(cat /run/secrets/ha_access_token 2>/dev/null)

if [[ -z "$HA_TOKEN" ]]; then
    skip "HA API: no access token available"
else
    # Test API access
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -H "Authorization: Bearer $HA_TOKEN" \
        http://10.4.4.10:8123/api/ 2>/dev/null)

    if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
        pass "HA API: authenticated access (HTTP $http_code)"
    elif [[ "$http_code" == "401" ]]; then
        fail "HA API: authentication failed (HTTP 401) - token may be invalid"
    elif [[ "$http_code" == "000" ]]; then
        skip "HA API: host unreachable"
    else
        fail "HA API: unexpected response (HTTP $http_code)"
    fi
fi
