package cli

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

const hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

// fakePlatform implements the subset of the platform contract the CLI uses.
type fakePlatform struct {
	mu       sync.Mutex
	approved []string
	runs     map[string]map[string]any
}

func newFake() (*fakePlatform, *httptest.Server) {
	f := &fakePlatform{runs: map[string]map[string]any{}}
	mux := http.NewServeMux()
	writeJSON := func(w http.ResponseWriter, status int, v any) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(v)
	}
	authed := func(h http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("Authorization") != "Bearer good-token" {
				writeJSON(w, 401, map[string]string{"code": "UNAUTHENTICATED", "message": "invalid or expired token", "requestId": "req_x"})
				return
			}
			h(w, r)
		}
	}
	mux.HandleFunc("/api/v1/health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, 200, map[string]string{"status": "UP", "service": "fake", "version": "1"})
	})
	mux.HandleFunc("/api/v1/auth/dev-token", func(w http.ResponseWriter, r *http.Request) {
		var body map[string]string
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["subject"] != "alice" {
			writeJSON(w, 403, map[string]string{"code": "ACCESS_DENIED", "message": "unknown development user", "requestId": "req_y"})
			return
		}
		writeJSON(w, 200, map[string]any{"access_token": "good-token", "token_type": "Bearer", "expires_in": 3600})
	})
	mux.HandleFunc("/api/v1/me", authed(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, 200, map[string]any{"subject": "alice", "tenant_id": "acme", "roles": []string{"developer"}})
	}))
	mux.HandleFunc("/api/v1/apis/search", authed(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"results": []map[string]any{{
			"operation_id": "refundPayment", "api": "Payments", "method": "POST", "path": "/v1/payments/{payment_id}/refunds",
			"summary": "Refund a payment q=" + r.URL.Query().Get("q"), "scopes": []string{"refunds:write"}, "score": 0.03, "rank": 1,
		}}})
	}))
	mux.HandleFunc("/api/v1/runs", authed(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			status, pending := "COMPLETED", any(nil)
			if strings.Contains(body["query"], "Create") {
				status = "AWAITING_APPROVAL"
				pending = map[string]any{"step_id": "call", "skill_id": "api.call.write", "action_hash": hash, "environment": body["environment"], "summary": "POST /v1/payments in 'sandbox'"}
			}
			run := map[string]any{"run_id": "run_0123456789abcdef", "status": status, "environment": body["environment"], "message": "done: " + body["query"],
				"requested_by": "alice", "created_at": "2026-10-03T00:00:00Z", "evidence": []string{}, "missing_fields": []string{}, "tool_calls": 3,
				"pending_approval": pending, "timeline": []map[string]any{{"kind": "intent", "detail": map[string]any{"intent": "api_execution"}}}}
			f.mu.Lock()
			f.runs["run_0123456789abcdef"] = run
			f.mu.Unlock()
			writeJSON(w, 201, run)
			return
		}
		writeJSON(w, 200, map[string]any{"runs": []any{}})
	}))
	mux.HandleFunc("/api/v1/runs/", authed(func(w http.ResponseWriter, r *http.Request) {
		id := strings.Split(strings.TrimPrefix(r.URL.Path, "/api/v1/runs/"), "/")[0]
		f.mu.Lock()
		defer f.mu.Unlock()
		run, ok := f.runs[id]
		if !ok {
			writeJSON(w, 404, map[string]string{"code": "RESOURCE_NOT_FOUND", "message": "run not found", "requestId": "req_z"})
			return
		}
		if strings.HasSuffix(r.URL.Path, "/approve") {
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			f.approved = append(f.approved, body["action_hash"])
			run["status"], run["pending_approval"], run["message"] = "COMPLETED", nil, "HTTP 201"
		}
		writeJSON(w, 200, run)
	}))
	return f, httptest.NewServer(mux)
}

func run(t *testing.T, srv *httptest.Server, cfg string, stdin string, args ...string) (int, string, string) {
	t.Helper()
	var out, errOut bytes.Buffer
	full := append([]string{"--backend-url", srv.URL, "--config", cfg}, args...)
	code := Run(full, IO{In: strings.NewReader(stdin), Out: &out, Err: &errOut})
	return code, out.String(), errOut.String()
}

func setup(t *testing.T) (*fakePlatform, *httptest.Server, string) {
	t.Helper()
	t.Setenv("COPILOT_BACKEND_URL", "")
	t.Setenv("COPILOT_TOKEN", "")
	f, srv := newFake()
	t.Cleanup(srv.Close)
	return f, srv, filepath.Join(t.TempDir(), "config.json")
}

func TestUsageErrors(t *testing.T) {
	_, srv, cfg := setup(t)
	for _, args := range [][]string{{"bogus"}, {"api"}, {"api", "nope"}, {"api", "search"}, {"ask"}, {"--output", "xml", "version"}, {"login"}, {"api", "search", "x", "--limit", "99"}} {
		if code, _, stderr := run(t, srv, cfg, "", args...); code != ExitUsage || !strings.Contains(stderr, "error:") {
			t.Errorf("%v: code %d stderr %q", args, code, stderr)
		}
	}
	if code, out, _ := run(t, srv, cfg, ""); code != ExitOK || !strings.Contains(out, "Commands:") {
		t.Errorf("no-arg help failed: %d", code)
	}
}

func TestCommandsRequireLogin(t *testing.T) {
	_, srv, cfg := setup(t)
	code, _, stderr := run(t, srv, cfg, "", "api", "search", "refund")
	if code != ExitError || !strings.Contains(stderr, "not logged in") {
		t.Fatalf("code %d stderr %q", code, stderr)
	}
}

func TestLoginWithDevUserAndTokenStdin(t *testing.T) {
	_, srv, cfg := setup(t)
	if code, _, stderr := run(t, srv, cfg, "", "login", "--user", "mallory"); code != ExitError || !strings.Contains(stderr, "ACCESS_DENIED") {
		t.Fatalf("unknown user: %d %q", code, stderr)
	}
	code, out, _ := run(t, srv, cfg, "", "login", "--user", "alice")
	if code != ExitOK || !strings.Contains(out, "Logged in as alice (tenant acme") {
		t.Fatalf("login: %d %q", code, out)
	}
	raw, _ := os.ReadFile(cfg)
	if !strings.Contains(string(raw), "good-token") {
		t.Fatal("token not stored")
	}
	if code, _, stderr := run(t, srv, cfg, "bad-token\n", "login", "--token-stdin"); code != ExitError || !strings.Contains(stderr, "token rejected") {
		t.Fatalf("bad stdin token accepted: %d %q", code, stderr)
	}
	if code, _, _ := run(t, srv, cfg, "good-token\n", "login", "--token-stdin"); code != ExitOK {
		t.Fatalf("stdin token rejected: %d", code)
	}
	if code, out, _ := run(t, srv, cfg, "", "logout"); code != ExitOK || !strings.Contains(out, "Logged out") {
		t.Fatal("logout failed")
	}
}

func TestSearchJSONAndPretty(t *testing.T) {
	_, srv, cfg := setup(t)
	run(t, srv, cfg, "", "login", "--user", "alice")
	code, out, _ := run(t, srv, cfg, "", "api", "search", "refund", "a", "payment", "--limit", "3")
	if code != ExitOK || !strings.Contains(out, "refundPayment") || !strings.Contains(out, "q=refund a payment") {
		t.Fatalf("pretty: %d %q", code, out)
	}
	code, out, _ = run(t, srv, cfg, "", "--output", "json", "api", "search", "refund")
	var hits []map[string]any
	if code != ExitOK || json.Unmarshal([]byte(out), &hits) != nil || hits[0]["operation_id"] != "refundPayment" {
		t.Fatalf("json: %d %q", code, out)
	}
}

func TestAskExitCodesAndApprovalFlow(t *testing.T) {
	f, srv, cfg := setup(t)
	run(t, srv, cfg, "", "login", "--user", "alice")
	if code, out, _ := run(t, srv, cfg, "", "ask", "which", "api", "lists", "customers"); code != ExitOK || !strings.Contains(out, "[COMPLETED]") {
		t.Fatalf("ask completed: %d %q", code, out)
	}
	code, out, _ := run(t, srv, cfg, "", "ask", "Create a payment", "--env", "sandbox")
	if code != ExitActionNeeded || !strings.Contains(out, "action hash: "+hash) || !strings.Contains(out, "copilot runs approve run_0123456789abcdef") {
		t.Fatalf("ask approval: %d %q", code, out)
	}
	// Declining at the prompt sends nothing.
	if code, _, _ := run(t, srv, cfg, "n\n", "runs", "approve", "run_0123456789abcdef"); code != ExitRunFailed || len(f.approved) != 0 {
		t.Fatalf("decline: %d approved=%v", code, f.approved)
	}
	code, out, _ = run(t, srv, cfg, "y\n", "runs", "approve", "run_0123456789abcdef")
	if code != ExitOK || !strings.Contains(out, "[COMPLETED]") || len(f.approved) != 1 || f.approved[0] != hash {
		t.Fatalf("approve: %d %q %v", code, out, f.approved)
	}
	if code, _, stderr := run(t, srv, cfg, "", "runs", "approve", "run_0123456789abcdef", "--yes"); code != ExitError || !strings.Contains(stderr, "not awaiting approval") {
		t.Fatalf("double approve: %d %q", code, stderr)
	}
	if code, out, _ := run(t, srv, cfg, "", "runs", "get", "run_0123456789abcdef"); code != ExitOK || !strings.Contains(out, "Timeline:") {
		t.Fatalf("get: %d %q", code, out)
	}
	if code, _, stderr := run(t, srv, cfg, "", "runs", "get", "run_ffffffffffffffff"); code != ExitError || !strings.Contains(stderr, "RESOURCE_NOT_FOUND") {
		t.Fatalf("missing run: %d %q", code, stderr)
	}
}

func TestDoctor(t *testing.T) {
	_, srv, cfg := setup(t)
	code, out, _ := run(t, srv, cfg, "", "doctor")
	if code != ExitError || !strings.Contains(out, "✓ backend health") || !strings.Contains(out, "✗ login") {
		t.Fatalf("doctor before login: %d %q", code, out)
	}
	run(t, srv, cfg, "", "login", "--user", "alice")
	if code, out, _ := run(t, srv, cfg, "", "doctor"); code != ExitOK || !strings.Contains(out, "alice @ acme") {
		t.Fatalf("doctor after login: %d %q", code, out)
	}
}

func TestEvalRunValidatesSuite(t *testing.T) {
	_, srv, cfg := setup(t)
	if code, _, _ := run(t, srv, cfg, "", "eval", "run", "--suite", "rm -rf /"); code != ExitUsage {
		t.Fatalf("expected usage error, got %d", code)
	}
}
