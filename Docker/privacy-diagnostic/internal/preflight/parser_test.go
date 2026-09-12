package preflight

import (
	"bytes"
	"errors"
	"strings"
	"testing"
)

const minimalUwsgi = "[uwsgi]\nmaster=true\ndie-on-term=true\nlog-format=" + UwsgiFormat + "\n"
const httpBase = "log_format privacy_counts '" + NginxFormat + "'; access_log /dev/stdout privacy_counts;"
const minimalNginx = "error_log stderr; worker_shutdown_timeout 2s; http { " + httpBase + " }"

func singleDump(body string) []byte {
	return []byte("# configuration file /etc/nginx/nginx.conf:\n" + body + "\n")
}

func TestRequiredBaselinesAndByteLimit(t *testing.T) {
	for _, check := range []struct {
		data []byte
		fn   func([]byte) error
	}{{[]byte(minimalUwsgi), ValidateUwsgi}, {singleDump(minimalNginx), ValidateNginx}} {
		if err := check.fn(check.data); err != nil {
			t.Fatal("positive baseline rejected")
		}
		boundary := append(bytes.Clone(check.data), []byte("#"+strings.Repeat("x", MaxBytes-len(check.data)-1))...)
		if err := check.fn(boundary); err != nil {
			t.Fatal("exact byte limit rejected")
		}
		for _, bad := range [][]byte{append(bytes.Clone(boundary), 'x'), {0xff}, append(bytes.Clone(check.data), 0)} {
			if !errors.Is(check.fn(bad), ErrConfig) {
				t.Fatal("invalid or oversized input accepted")
			}
		}
	}
	for _, required := range []string{"master=true\n", "die-on-term=true\n", "log-format=" + UwsgiFormat + "\n"} {
		if ValidateUwsgi([]byte(strings.Replace(minimalUwsgi, required, "", 1))) == nil {
			t.Fatal("missing uWSGI baseline accepted")
		}
	}
	for _, required := range []string{"error_log stderr;", "worker_shutdown_timeout 2s;", "access_log /dev/stdout privacy_counts;", "log_format privacy_counts '" + NginxFormat + "';"} {
		if ValidateNginx(singleDump(strings.Replace(minimalNginx, required, "", 1))) == nil {
			t.Fatal("missing nginx baseline accepted")
		}
	}
}

func TestUnicodeLinesAndQuotedData(t *testing.T) {
	for _, separator := range []string{"\n", "\r", "\r\n", "\u0085", "\u2028", "\u2029"} {
		if ValidateUwsgi([]byte(strings.ReplaceAll(minimalUwsgi, "\n", separator))) != nil {
			t.Fatalf("valid separator %q rejected", separator)
		}
	}
	quoted := "server { set $data \"begin\n# configuration file /fake:\nend\"; }"
	if ValidateNginx(singleDump(strings.Replace(minimalNginx, httpBase, httpBase+quoted, 1))) != nil {
		t.Fatal("quoted header was treated as a file")
	}
	for _, extra := range []string{`error_log "stderr"private;`, `error_log std"err";`, "access_log off#private;", "error_log /tmp/SYNTHETIC_PRIVATE;"} {
		body := strings.Replace(minimalNginx, httpBase, httpBase+" server {"+extra+"}", 1)
		if err := ValidateNginx(singleDump(body)); !errors.Is(err, ErrConfig) || strings.Contains(err.Error(), "SYNTHETIC_PRIVATE") {
			t.Fatal("unsafe override accepted or disclosed")
		}
	}
}

func TestTokenAndNestingBudgets(t *testing.T) {
	if _, err := parseNginx(strings.Repeat("x {", 63) + strings.Repeat("}", 63)); err != nil {
		t.Fatal("valid depth rejected")
	}
	if _, err := parseNginx(strings.Repeat("x {", 64) + strings.Repeat("}", 64)); err == nil {
		t.Fatal("excessive depth accepted")
	}
	if _, err := tokens(strings.Repeat("x;", 50000)); err != nil {
		t.Fatal("valid token budget rejected")
	}
	if _, err := tokens(strings.Repeat("x;", 50001)); err == nil {
		t.Fatal("excessive tokens accepted")
	}
}

func TestDescendingGlobRangeCanExposeNegation(t *testing.T) {
	pattern, err := componentGlob("[]-!![]")
	if err != nil || !pattern.MatchString("\n") || pattern.MatchString("[") {
		t.Fatal("fnmatch descending-range normalization changed")
	}
}

func FuzzParsersReturnOnlyFixedErrors(f *testing.F) {
	f.Add([]byte(minimalUwsgi))
	f.Add(singleDump(minimalNginx))
	f.Add([]byte("[!z-a]*[]]"))
	f.Fuzz(func(t *testing.T, data []byte) {
		// Exact 1 MiB limits are covered above; keep mutation work bounded.
		if len(data) > 64*1024 {
			data = data[:64*1024]
		}
		for _, fn := range []func([]byte) error{ValidateUwsgi, ValidateNginx} {
			err := fn(data)
			if err != nil && err != ErrConfig {
				t.Fatal("non-fixed parser error")
			}
		}
		// Exercise bracket/range normalization directly as well as via includes.
		glob, err := componentGlob(string(data[:min(len(data), 4096)]))
		if err != nil && err != ErrConfig {
			t.Fatal("non-fixed glob error")
		}
		if err == nil {
			glob.MatchString("synthetic.conf")
		}
	})
}
