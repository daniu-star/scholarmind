import urllib.request, json

# Test 1: Health check
try:
    r = urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=10)
    print("HEALTH:", json.loads(r.read()))
except Exception as e:
    print("HEALTH ERROR:", e)

# Test 2: Agent list
try:
    r = urllib.request.urlopen('http://localhost:8000/api/v1/agent/list', timeout=10)
    print("AGENT LIST:", json.loads(r.read()))
except Exception as e:
    print("AGENT LIST ERROR:", e)

# Test 3: Chat with researcher
try:
    data = json.dumps({"agent_id":"researcher","message":"你好","session_id":"test-001"}).encode()
    req = urllib.request.Request('http://localhost:8000/api/v1/agent/chat', data=data, headers={'Content-Type':'application/json'})
    r = urllib.request.urlopen(req, timeout=30)
    print("CHAT:", json.loads(r.read()))
except Exception as e:
    print("CHAT ERROR:", e)

# Test 4: Chat with invalid agent
try:
    data = json.dumps({"agent_id":"invalid","message":"你好","session_id":"test-002"}).encode()
    req = urllib.request.Request('http://localhost:8000/api/v1/agent/chat', data=data, headers={'Content-Type':'application/json'})
    r = urllib.request.urlopen(req, timeout=30)
    print("INVALID AGENT:", json.loads(r.read()))
except urllib.error.HTTPError as e:
    print("INVALID AGENT ERROR:", e.code, e.read().decode())
except Exception as e:
    print("INVALID AGENT ERROR:", e)

# Test 5: Chat with empty message
try:
    data = json.dumps({"agent_id":"researcher","message":"","session_id":"test-003"}).encode()
    req = urllib.request.Request('http://localhost:8000/api/v1/agent/chat', data=data, headers={'Content-Type':'application/json'})
    r = urllib.request.urlopen(req, timeout=30)
    print("EMPTY MSG:", json.loads(r.read()))
except urllib.error.HTTPError as e:
    print("EMPTY MSG ERROR:", e.code, e.read().decode())
except Exception as e:
    print("EMPTY MSG ERROR:", e)

# Test 6: Skills list
try:
    r = urllib.request.urlopen('http://localhost:8000/api/v1/skills', timeout=10)
    print("SKILLS:", json.loads(r.read()))
except Exception as e:
    print("SKILLS ERROR:", e)

# Test 7: Knowledge CNKI search
try:
    data = json.dumps({"query":"人工智能","count":3}).encode()
    req = urllib.request.Request('http://localhost:8000/api/v1/knowledge/cnki/search', data=data, headers={'Content-Type':'application/json'})
    r = urllib.request.urlopen(req, timeout=30)
    print("CNKI:", json.loads(r.read()))
except Exception as e:
    print("CNKI ERROR:", e)

# Test 8: Chart generate
try:
    data = json.dumps({"chart_type":"ribbon","title":"Test Chart","data":{"x":[1,2,3],"y":[4,5,6]}}).encode()
    req = urllib.request.Request('http://localhost:8000/api/v1/chart/generate', data=data, headers={'Content-Type':'application/json'})
    r = urllib.request.urlopen(req, timeout=30)
    ct = r.headers.get('content-type','')
    print("CHART:", ct, f"size={len(r.read())} bytes")
except Exception as e:
    print("CHART ERROR:", e)