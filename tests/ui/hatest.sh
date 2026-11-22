start_stack() {
  pkill -f "hass -c /tmp/haconfig" 2>/dev/null; pkill -f "http.server 8124" 2>/dev/null; sleep 1
  cd /tmp/frameserver && python3 -m http.server 8124 > /tmp/frameserver.log 2>&1 &
  FS=$!
  cd /tmp/haconfig && /tmp/havenv/bin/hass -c /tmp/haconfig > /tmp/hass.log 2>&1 &
  HASS=$!
  for i in $(seq 1 100); do curl -s -o /dev/null http://127.0.0.1:8123/api/ && break || sleep 1; done
  # wait until our integration has fully started, not just HTTP
  for j in $(seq 1 60); do grep -q "Recorder started" /tmp/hass.log && break || sleep 1; done
  FLOW=$(curl -s -X POST http://127.0.0.1:8123/auth/login_flow -H 'Content-Type: application/json' -d '{"client_id":"http://127.0.0.1:8123/","handler":["homeassistant",null],"redirect_uri":"http://127.0.0.1:8123/"}')
  FID=$(echo "$FLOW" | jq -r .flow_id)
  CODE=$(curl -s -X POST "http://127.0.0.1:8123/auth/login_flow/$FID" -H 'Content-Type: application/json' -d "{\"username\":\"$HA_TEST_USER\",\"password\":\"$HA_TEST_PASS\",\"client_id\":\"http://127.0.0.1:8123/\"}" | jq -r .result)
  TOK=$(curl -s -X POST http://127.0.0.1:8123/auth/token -d "grant_type=authorization_code&code=$CODE&client_id=http://127.0.0.1:8123/")
  AT=$(echo "$TOK" | jq -r .access_token)
  echo "$AT" > /tmp/at.txt
}
stop_stack() { kill -TERM $HASS 2>/dev/null; for k in $(seq 1 15); do kill -0 $HASS 2>/dev/null || break; sleep 1; done; kill -9 $HASS 2>/dev/null; kill $FS 2>/dev/null; wait $HASS $FS 2>/dev/null; }
