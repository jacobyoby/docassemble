package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/runner"
)

func mailCLI(t *testing.T, script string, args ...string) *exec.Cmd {
	t.Helper()
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	t.Cleanup(cancel)
	command := []string{"--component", "mail", "--", "/bin/sh", "-c", script, "synthetic-mail"}
	cmd := exec.CommandContext(ctx, self, append(command, args...)...)
	cmd.Env = append(os.Environ(), "PRIVACY_PROCESS_CLI_TEST=1")
	cmd.WaitDelay = time.Second
	t.Cleanup(func() {
		if cmd.Process != nil && cmd.ProcessState == nil {
			cmd.Process.Kill()
			cmd.Wait()
		}
	})
	return cmd
}

func temporaryMailExit(t *testing.T, err error) {
	t.Helper()
	var exit *exec.ExitError
	if !errors.As(err, &exit) || exit.ExitCode() != runner.TemporaryFailure {
		t.Fatalf("mail failure did not defer delivery: %v", err)
	}
}

func TestMailCountersHaveOneFinalRecordAcrossReportingIntervals(t *testing.T) {
	// More than 20 KiB of child output and multiple normal reporting intervals
	// must still produce one record below Exim's default total-output limit.
	cmd := mailCLI(t, `j=0; while [ "$j" -lt 3 ]; do
i=0; while [ "$i" -lt 1000 ]; do
printf 'SYNTHETIC_PRIVATE_MAIL\n'; i=$((i+1)); done
sleep 1; j=$((j+1)); done`)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	data, err := cmd.Output()
	if err != nil || stderr.Len() != 0 || len(data) > 8191 || bytes.Count(data, []byte{'\n'}) != 1 {
		t.Fatalf("mail output is not bounded to one record: exit=%v bytes=%d records=%d", err, len(data), bytes.Count(data, []byte{'\n'}))
	}
	var value aggregate.Snapshot
	if json.Unmarshal(data, &value) != nil || value.Component != "mail" || value.Unclassified != 3000 {
		t.Fatalf("mail final counters lost output: %q", data)
	}
	if _, err := json.Marshal(value); err != nil {
		t.Fatal(err)
	}
}

func TestMailChildSignalDefersDelivery(t *testing.T) {
	cmd := mailCLI(t, "kill -KILL $$")
	data, err := cmd.CombinedOutput()
	temporaryMailExit(t, err)
	var value aggregate.Snapshot
	if json.Unmarshal(data, &value) != nil || value.Component != "mail" {
		t.Fatal("child signal lost the fixed final counters")
	}
}

func TestMailInterruptedSuccessfulChildStillDefersDelivery(t *testing.T) {
	for _, stop := range []syscall.Signal{syscall.SIGINT, syscall.SIGTERM} {
		t.Run(stop.String(), func(t *testing.T) {
			ready := filepath.Join(t.TempDir(), "ready")
			cmd := mailCLI(t, `trap 'exit 0' TERM; : > "$1"; while :; do sleep 0.05; done`, ready)
			var output bytes.Buffer
			cmd.Stdout, cmd.Stderr = &output, &output
			if err := cmd.Start(); err != nil {
				t.Fatal(err)
			}
			deadline := time.Now().Add(2 * time.Second)
			for {
				if _, err := os.Stat(ready); err == nil {
					break
				}
				if time.Now().After(deadline) {
					t.Fatal("synthetic mail child did not become ready")
				}
				time.Sleep(5 * time.Millisecond)
			}
			if err := cmd.Process.Signal(stop); err != nil {
				t.Fatal(err)
			}
			temporaryMailExit(t, cmd.Wait())
			if bytes.Contains(output.Bytes(), []byte("SYNTHETIC_PRIVATE")) {
				t.Fatal("interruption exposed child output")
			}
		})
	}
}

func TestMailBrokenAndFullOutputPipesDeferWithinDeadline(t *testing.T) {
	for _, mode := range []string{"broken", "full"} {
		t.Run(mode, func(t *testing.T) {
			reader, writer, err := os.Pipe()
			if err != nil {
				t.Fatal(err)
			}
			defer reader.Close()
			defer writer.Close()
			if mode == "broken" {
				reader.Close()
			} else {
				fd := int(writer.Fd())
				if err := syscall.SetNonblock(fd, true); err != nil {
					t.Fatal(err)
				}
				for {
					_, err := syscall.Write(fd, bytes.Repeat([]byte{'x'}, 4096))
					if err == syscall.EAGAIN {
						break
					}
					if err != nil {
						t.Fatal(err)
					}
				}
				if err := syscall.SetNonblock(fd, false); err != nil {
					t.Fatal(err)
				}
			}
			cmd := mailCLI(t, "printf 'SYNTHETIC_PRIVATE_MAIL\\n'")
			var stderr bytes.Buffer
			cmd.Stdout, cmd.Stderr = writer, &stderr
			started := time.Now()
			temporaryMailExit(t, cmd.Run())
			if time.Since(started) > 7*time.Second || stderr.Len() != 0 {
				t.Fatal("mail output failure was unbounded or exposed diagnostics")
			}
		})
	}
}
