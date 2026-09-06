package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"testing"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
)

func TestCronReportsOnlyAtExitWithoutMailInputOrRetrySemantics(t *testing.T) {
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, self, "--component", "cron", "--", "/bin/sh", "-c",
		"read value && exit 99; printf 'SYNTHETIC_PRIVATE_CRON\\n'; printf 'SYNTHETIC_PRIVATE_CRON\\n' >&2; sleep 1.2; exit 17")
	cmd.Env = append(os.Environ(), "PRIVACY_PROCESS_CLI_TEST=1")
	cmd.Stdin = bytes.NewBufferString("must not reach the cron child\n")
	cmd.WaitDelay = time.Second
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	output, err := cmd.Output()
	var failure *exec.ExitError
	if !errors.As(err, &failure) || failure.ExitCode() != 17 || stderr.Len() != 0 {
		t.Fatalf("cron exit/input semantics changed: %v %q", err, stderr.Bytes())
	}
	if bytes.Count(output, []byte("\n")) != 1 || bytes.Contains(output, []byte("SYNTHETIC_PRIVATE")) {
		t.Fatalf("cron emitted periodic or raw output: %q", output)
	}
	var record aggregate.Snapshot
	if err := json.Unmarshal(output, &record); err != nil {
		t.Fatal(err)
	}
	if _, err := json.Marshal(record); err != nil || record.Component != "cron" || record.Unclassified != 2 {
		t.Fatalf("cron counter contract changed: %#v %v", record, err)
	}
}
