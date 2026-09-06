package main

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/preflight"
)

func TestMain(m *testing.M) {
	if os.Getenv("PRIVACY_PREFLIGHT_CLI_TEST") == "1" {
		main()
		os.Exit(99)
	}
	os.Exit(m.Run())
}

func TestFileChecksAndInvalidArgumentsRemainSilent(t *testing.T) {
	root := t.TempDir()
	valid := filepath.Join(root, "valid.ini")
	invalid := filepath.Join(root, "SYNTHETIC_PRIVATE.ini")
	large := filepath.Join(root, "large.ini")
	fifo := filepath.Join(root, "fifo")
	base := "[uwsgi]\nmaster=true\ndie-on-term=true\nlog-format=" + preflight.UwsgiFormat + "\n"
	for path, data := range map[string]string{valid: base, invalid: base + "logto=/tmp/private\n", large: strings.Repeat("#", preflight.MaxBytes+1)} {
		if os.WriteFile(path, []byte(data), 0600) != nil {
			t.Fatal("fixture creation failed")
		}
	}
	if err := syscall.Mkfifo(fifo, 0600); err != nil {
		t.Fatal(err)
	}
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, item := range []struct {
		args []string
		code int
	}{{[]string{"uwsgi", valid}, 0}, {[]string{"uwsgi", invalid}, 70},
		{[]string{"uwsgi", large}, 70}, {[]string{"uwsgi", fifo}, 70},
		{[]string{"uwsgi", root}, 70}, {[]string{"uwsgi", valid + ".missing"}, 70},
		{nil, 70}, {[]string{"nginx", "extra"}, 70}, {[]string{"uwsgi"}, 70},
		{[]string{"SYNTHETIC_PRIVATE"}, 70}} {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		cmd := exec.CommandContext(ctx, self, item.args...)
		cmd.Env = append(os.Environ(), "PRIVACY_PREFLIGHT_CLI_TEST=1")
		output, err := cmd.CombinedOutput()
		cancel()
		code := 0
		if err != nil {
			var exit *exec.ExitError
			if !errors.As(err, &exit) {
				t.Fatal(err)
			}
			code = exit.ExitCode()
		}
		if code != item.code || len(output) != 0 {
			t.Fatalf("preflight leaked or returned wrong exit: got=%d want=%d output=%q", code, item.code, output)
		}
	}
}
