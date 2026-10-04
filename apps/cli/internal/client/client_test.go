package client

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestNewRejectsTokenOverPlainHTTPToRemoteHost(t *testing.T) {
	if _, err := New("http://api.example.com", "tok", "t", time.Second); err == nil {
		t.Fatal("expected refusal for plain HTTP + token to non-loopback host")
	}
	for _, ok := range []string{"http://localhost:8080", "http://127.0.0.1:8080", "https://api.example.com"} {
		if _, err := New(ok, "tok", "t", time.Second); err != nil {
			t.Fatalf("%s: unexpected error %v", ok, err)
		}
	}
	for _, bad := range []string{"ftp://x", "not a url", "https://user:pw@host"} {
		if _, err := New(bad, "", "t", time.Second); err == nil {
			t.Fatalf("%s: expected error", bad)
		}
	}
}

func TestRequestHeadersAndAPIError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer tok" || !strings.HasPrefix(r.Header.Get("X-Request-Id"), "req_") {
			t.Errorf("missing auth or request id headers: %v", r.Header)
		}
		if r.URL.Query().Get("q") != "refund a payment" {
			t.Errorf("query not encoded: %s", r.URL.RawQuery)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(`{"code":"ACCESS_DENIED","message":"nope","requestId":"req_1","path":"/x","timestamp":"t"}`))
	}))
	defer srv.Close()
	c, err := New(srv.URL, "tok", "test", time.Second)
	if err != nil {
		t.Fatal(err)
	}
	_, err = c.SearchAPIs(context.Background(), "refund a payment", 3)
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.Status != 403 || apiErr.Code != "ACCESS_DENIED" || apiErr.RequestID != "req_1" {
		t.Fatalf("unexpected error: %#v", err)
	}
}

func TestNonJSONErrorsAndRedirectsAreNotFollowed(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/me" {
			http.Redirect(w, r, "http://169.254.169.254/latest", http.StatusFound)
			return
		}
		http.Error(w, "gateway exploded", http.StatusBadGateway)
	}))
	defer srv.Close()
	c, _ := New(srv.URL, "tok", "test", time.Second)
	_, err := c.Health(context.Background())
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.Code != "HTTP_502" || !strings.Contains(apiErr.Message, "exploded") {
		t.Fatalf("unexpected: %v", err)
	}
	_, err = c.Me(context.Background())
	if !errors.As(err, &apiErr) || apiErr.Status != http.StatusFound {
		t.Fatalf("redirect should surface as an error, got %v", err)
	}
}

func TestResponseSizeLimit(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(strings.Repeat("x", maxResponseBytes+10)))
	}))
	defer srv.Close()
	c, _ := New(srv.URL, "", "test", 5*time.Second)
	if _, err := c.Health(context.Background()); err == nil || !strings.Contains(err.Error(), "size limit") {
		t.Fatalf("expected size-limit error, got %v", err)
	}
}

func TestPathParametersAreEscaped(t *testing.T) {
	var seen string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.URL.EscapedPath()
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv.Close()
	c, _ := New(srv.URL, "", "test", time.Second)
	_, _ = c.DescribeAPI(context.Background(), "../runs")
	if seen != "/api/v1/apis/..%2Fruns" {
		t.Fatalf("path not escaped: %s", seen)
	}
}
