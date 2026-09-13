package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/preflight"
	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/runner"
)

func TestMain(m *testing.M) {
	if os.Getenv("PRIVACY_PROCESS_CLI_TEST") == "1" {
		if filepath.Base(os.Args[0]) == "privacy-preflight" {
			os.Exit(preflight.Run(os.Args[1:]))
		}
		main()
		os.Exit(99)
	}
	os.Exit(m.Run())
}

func TestLaunchersReachGoPreflightAndCapture(t *testing.T) {
	for _, item := range []struct{ name, mode, ini, fault string }{
		{"run-uwsgi.sh", "nginx", "docassemble.ini", ""},
		{"run-uwsgi.sh", "none", "docassemble-expose-uwsgi.ini", ""},
		{"run-uwsgilog.sh", "nginx", "docassemblelog.ini", ""},
		{"run-uwsgi.sh", "nginx", "docassemble.ini", "unsafe"},
		{"run-uwsgilog.sh", "nginx", "docassemblelog.ini", "unsafe"},
		{"run-uwsgi.sh", "nginx", "docassemble.ini", "missing-preflight"},
		{"run-uwsgilog.sh", "nginx", "docassemblelog.ini", "missing-preflight"},
	} {
		t.Run(item.name+"/"+item.mode+"/"+item.fault, func(t *testing.T) {
			root := t.TempDir()
			for _, dir := range []string{"runtime/bin", "webapp", "config"} {
				if err := os.MkdirAll(filepath.Join(root, dir), 0700); err != nil {
					t.Fatal(err)
				}
			}
			files := map[string]string{
				"runtime/bin/activate": "true\n",
				"runtime/bin/python": `#!/bin/sh
if [ "$1" = "-m" ]; then
    printf '%s\n' 'export LOCALE="C.UTF-8 UTF-8"' 'export DAREADONLYFILESYSTEM="true"'
    exit 0
fi
exit 99
`,
				"runtime/bin/uwsgi": `#!/bin/sh
printf 'started\n' > "$DA_ROOT/native-started" || exit 98
printf '%s\n' 'SYNTHETIC_PRIVATE_NATIVE' 'PRIVACY_REQUEST status=200 msecs=99'
printf '%s\n' 'PRIVACY_REQUEST status=503 msecs=30000' 'SYNTHETIC_PRIVATE_NATIVE' >&2
exit 17
`,
				"webapp/privacy-diagnostic": "#!/bin/sh\nprintf '%s:%s\\n' \"$1\" \"$2\"\nexit 70\n",
			}
			base := "[uwsgi]\nmaster=true\ndie-on-term=true\nlog-format=" + preflight.UwsgiFormat + "\n"
			for _, ini := range []string{"docassemble.ini", "docassemble-expose-uwsgi.ini", "docassemblelog.ini"} {
				files["config/"+ini] = base + "logto=/tmp/SYNTHETIC_PRIVATE\n"
			}
			if item.fault != "unsafe" {
				files["config/"+item.ini] = base
			}
			for path, content := range files {
				if err := os.WriteFile(filepath.Join(root, path), []byte(content), 0700); err != nil {
					t.Fatal(err)
				}
			}
			self, err := os.Executable()
			if err != nil {
				t.Fatal(err)
			}
			binary, err := os.ReadFile(self)
			if err != nil {
				t.Fatal(err)
			}
			for _, executable := range []string{"privacy-process", "privacy-preflight"} {
				if executable == "privacy-preflight" && item.fault == "missing-preflight" {
					continue
				}
				if os.WriteFile(filepath.Join(root, "webapp/"+executable), binary, 0700) != nil {
					t.Fatal("cannot install Go CLI fixture")
				}
			}
			script, err := filepath.Abs("../../../../Docker/" + item.name)
			if err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, "bash", script)
			cmd.Env = append(os.Environ(), "PRIVACY_PROCESS_CLI_TEST=1", "DA_ROOT="+root, "DA_PYTHON="+root+"/runtime", "DAWEBSERVER="+item.mode)
			cmd.WaitDelay = time.Second
			var stderr bytes.Buffer
			cmd.Stderr = &stderr
			data, err := cmd.Output()
			var exit *exec.ExitError
			if item.fault != "" {
				component := "uwsgi"
				if item.name == "run-uwsgilog.sh" {
					component = "uwsgilog"
				}
				if !errors.As(err, &exit) || exit.ExitCode() != 70 || string(data) != component+":preflight\n" || stderr.Len() != 0 {
					t.Fatalf("unsafe setup did not fail at preflight: %v stdout=%q stderr=%q", err, data, stderr.Bytes())
				}
				if _, err := os.Stat(filepath.Join(root, "native-started")); !errors.Is(err, os.ErrNotExist) {
					t.Fatal("native service started after rejected preflight")
				}
				return
			}
			if !errors.As(err, &exit) || exit.ExitCode() != 17 || stderr.Len() != 0 || bytes.Contains(data, []byte("SYNTHETIC_PRIVATE")) {
				t.Fatalf("handoff/capture failed: %v stdout=%q stderr=%q", err, data, stderr.Bytes())
			}
			decoder := json.NewDecoder(bytes.NewReader(data))
			var last aggregate.Snapshot
			for {
				var value aggregate.Snapshot
				if err := decoder.Decode(&value); err != nil {
					if err == io.EOF {
						break
					}
					t.Fatal(err)
				}
				last = value
			}
			if last.Component != "uwsgi" || last.Status2xx != 1 || last.Status5xx != 1 || last.Unclassified != 2 {
				t.Fatalf("final native counters missing: %#v", last)
			}
		})
	}
}

func TestCLIRejectsInvalidInvocation(t *testing.T) {
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(self, "SYNTHETIC_PRIVATE_NATIVE")
	cmd.Env = append(os.Environ(), "PRIVACY_PROCESS_CLI_TEST=1")
	data, err := cmd.CombinedOutput()
	var exit *exec.ExitError
	if !errors.As(err, &exit) || exit.ExitCode() != runner.UsageFailure || len(data) != 0 {
		t.Fatalf("invalid CLI did not fail closed: %v %q", err, data)
	}
}
