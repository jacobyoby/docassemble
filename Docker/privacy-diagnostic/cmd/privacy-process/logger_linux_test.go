package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
)

func TestApplicationLoggerUsesOnlyCapturedStreams(t *testing.T) {
	python, err := exec.LookPath("python3.14")
	if err != nil {
		t.Fatal("Python 3.14 required for real application logger fixture")
	}
	root, err := filepath.Abs("../../../..")
	if err != nil {
		t.Fatal(err)
	}
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, profile := range []string{"uwsgi", "celery", "celerysingle", "websockets", "mail"} {
		for _, appContext := range []string{"web", "std", "celery", "cron"} {
			for _, server := range []string{"none", "synthetic"} {
				for _, debug := range []string{"info", "debug"} {
					t.Run(profile+"/"+appContext+"/"+server+"/"+debug, func(t *testing.T) {
						ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
						defer cancel()
						directory := t.TempDir()
						cmd := exec.CommandContext(ctx, self, "--component", profile, "--", python,
							"-B", root+"/tests/privacy_native/fixtures/application-logger.py", root,
							directory, appContext, server, debug, "--die-on-term")
						cmd.Env = append(os.Environ(), "PRIVACY_PROCESS_CLI_TEST=1", "PYTHONDONTWRITEBYTECODE=1")
						cmd.WaitDelay = time.Second
						var stderr bytes.Buffer
						cmd.Stderr = &stderr
						data, err := cmd.Output()
						if err != nil || stderr.Len() != 0 || bytes.Contains(data, []byte("SYNTHETIC_PRIVATE")) {
							t.Fatalf("application logger capture failed: %v stdout=%q stderr=%q", err, data, stderr.Bytes())
						}
						entries, err := os.ReadDir(directory)
						if err != nil || len(entries) != 0 {
							t.Fatal("application logger opened an independent retained file")
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
							if _, err := json.Marshal(value); err != nil {
								t.Fatal(err)
							}
							last = value
						}
						if last.Component != profile || last.Unclassified != 6 || last.Rejected != 0 || last.Dropped != 0 {
							t.Fatalf("application lines did not reach capture: %#v", last)
						}
					})
				}
			}
		}
	}
}
