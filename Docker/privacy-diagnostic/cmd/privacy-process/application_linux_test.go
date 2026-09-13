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
)

func TestApplicationLaunchersReachGoCapture(t *testing.T) {
	for _, item := range []struct{ script, component string }{
		{"run-celery.sh", "celery"}, {"run-celery-single.sh", "celerysingle"},
		{"run-websockets.sh", "websockets"},
	} {
		t.Run(item.component, func(t *testing.T) {
			root := t.TempDir()
			for _, dir := range []string{"runtime/bin", "webapp"} {
				if err := os.MkdirAll(filepath.Join(root, dir), 0700); err != nil {
					t.Fatal(err)
				}
			}
			native := `printf '%s\n' 'SYNTHETIC_PRIVATE_NATIVE' 'PRIVACY_REQUEST status=200 msecs=0'
printf '%s\n' 'SYNTHETIC_PRIVATE_NATIVE' 'PRIVACY_REQUEST status=500 msecs=0' >&2
exit 17
`
			files := map[string]string{
				"runtime/bin/activate": "printf 'SYNTHETIC_PRIVATE_BOOTSTRAP\\n' >&2\n",
				"runtime/bin/python": `#!/bin/sh
if [ "$1" = "-m" ]; then
    printf '%s\n' 'export LOCALE="C.UTF-8 UTF-8"' 'DAMAXCELERYWORKERS=4' 'DACELERYWORKERS=3'
    printf 'SYNTHETIC_PRIVATE_BOOTSTRAP\n' >&2
    exit 0
fi
` + native,
				"runtime/bin/celery":        "#!/bin/sh\n" + native,
				"webapp/privacy-diagnostic": "#!/bin/sh\nexit 70\n",
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
			if err != nil || os.WriteFile(filepath.Join(root, "webapp/privacy-process"), binary, 0700) != nil {
				t.Fatal("cannot prepare actual Go CLI")
			}
			script, err := filepath.Abs("../../../../Docker/" + item.script)
			if err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, "bash", script)
			cmd.Env = append(os.Environ(), "PRIVACY_PROCESS_CLI_TEST=1", "DA_ROOT="+root, "DA_PYTHON="+root+"/runtime")
			cmd.WaitDelay = time.Second
			var stderr bytes.Buffer
			cmd.Stderr = &stderr
			data, err := cmd.Output()
			var exit *exec.ExitError
			if !errors.As(err, &exit) || exit.ExitCode() != 17 || stderr.Len() != 0 || bytes.Contains(data, []byte("SYNTHETIC_PRIVATE")) {
				t.Fatalf("application capture failed: %v stdout=%q stderr=%q", err, data, stderr.Bytes())
			}
			var last aggregate.Snapshot
			decoder := json.NewDecoder(bytes.NewReader(data))
			for {
				var value aggregate.Snapshot
				if err := decoder.Decode(&value); err != nil {
					if err == io.EOF {
						break
					}
					t.Fatal(err)
				}
				if _, err := json.Marshal(value); err != nil {
					t.Fatal(err)
				}
				last = value
			}
			if last.Component != item.component || last.Unclassified != 4 || last.Status2xx != 0 || last.Status5xx != 0 {
				t.Fatalf("wrong final application counters: %#v", last)
			}
		})
	}
}
