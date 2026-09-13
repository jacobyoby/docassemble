package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/runner"
)

func TestMailLauncherStreamsInputAndReportsProcessingFailures(t *testing.T) {
	root, err := filepath.Abs("../../../..")
	if err != nil {
		t.Fatal(err)
	}
	python, err := exec.LookPath("python3.14")
	if err != nil {
		t.Fatal(err)
	}
	inputCommand := exec.Command(python, "-B", "-c", "from mail_support import MESSAGE; import sys; sys.stdout.buffer.write(MESSAGE)")
	inputCommand.Env = append(os.Environ(), "PYTHONPATH="+root+"/tests/privacy_native")
	message, err := inputCommand.Output()
	if err != nil {
		t.Fatal("cannot load synthetic message", err)
	}
	for _, item := range []struct {
		mode, nativeExit string
		want             int
		input            []byte
	}{
		{"input", "0", 0, bytes.Repeat([]byte{0, 255, '\r', '\n', 'x'}, 256*1024)},
		{"input", "17", 75, message},
		{"success", "0", 0, message},
		{"read", "0", 75, message},
		{"unknown", "0", 75, message},
		{"database", "0", 75, message},
		{"broker", "0", 75, message},
	} {
		t.Run(item.mode+"/"+item.nativeExit, func(t *testing.T) {
			directory := t.TempDir()
			for _, path := range []string{"runtime/bin", "webapp", "message-files"} {
				if err := os.MkdirAll(filepath.Join(directory, path), 0700); err != nil {
					t.Fatal(err)
				}
			}
			if err := os.WriteFile(directory+"/runtime/bin/activate", []byte("printf 'SYNTHETIC_PRIVATE_BOOTSTRAP\\n' >&2\n"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(root+"/tests/privacy_native/fixtures/mail-runtime.py", directory+"/runtime/bin/python"); err != nil {
				t.Fatal(err)
			}
			self, err := os.Executable()
			if err != nil {
				t.Fatal(err)
			}
			binary, err := os.ReadFile(self)
			if err != nil || os.WriteFile(directory+"/webapp/privacy-process", binary, 0700) != nil {
				t.Fatal("cannot prepare actual Go capture CLI")
			}
			if err := os.WriteFile(directory+"/webapp/privacy-diagnostic", []byte("#!/bin/sh\nexit 70\n"), 0700); err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, "bash", root+"/Docker/process-email.sh")
			digest := sha256.Sum256(item.input)
			cmd.Env = append(os.Environ(), "PRIVACY_PROCESS_CLI_TEST=1", "DA_ROOT="+directory, "DA_PYTHON="+directory+"/runtime",
				"SYNTHETIC_MAIL_MODE="+item.mode, "SYNTHETIC_MAIL_EXIT="+item.nativeExit,
				"SYNTHETIC_MAIL_SHA256="+hex.EncodeToString(digest[:]), "SYNTHETIC_MAIL_DIRECTORY="+directory+"/message-files")
			cmd.Stdin = bytes.NewReader(item.input)
			cmd.WaitDelay = time.Second
			var stderr bytes.Buffer
			cmd.Stderr = &stderr
			data, err := cmd.Output()
			code := 0
			if err != nil {
				var exit *exec.ExitError
				if !errors.As(err, &exit) {
					t.Fatal(err)
				}
				code = exit.ExitCode()
			}
			if code != item.want || stderr.Len() != 0 || bytes.Contains(data, []byte("SYNTHETIC_PRIVATE")) {
				t.Fatalf("mail capture/exit failed: code=%d stdout=%q stderr=%q", code, data, stderr.Bytes())
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
			if last.Component != "mail" || last.Unclassified == 0 {
				t.Fatal("missing mail counters")
			}
			if (item.mode == "input" || item.mode == "success") && last.Unclassified != 3 {
				t.Fatalf("mail output lost or became request metrics: %#v", last)
			}
			entries, err := os.ReadDir(directory + "/message-files")
			if err != nil || len(entries) != 0 {
				t.Fatal("mail processor created an independent message/log file")
			}
		})
	}
}

func TestMailSetupFailuresDeferDelivery(t *testing.T) {
	for _, args := range [][]string{
		{"--component", "mail"},
		{"--component", "mail", "--", "relative"},
		{"--component", "mail", "--", "/missing-synthetic-mail-runtime"},
		{"--component", "mail", "--", "/bin/true"}, // Unsupported regular-file sink.
	} {
		self, err := os.Executable()
		if err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command(self, args...)
		cmd.Env = append(os.Environ(), "PRIVACY_PROCESS_CLI_TEST=1")
		output, err := os.CreateTemp(t.TempDir(), "sink")
		if err != nil {
			t.Fatal(err)
		}
		cmd.Stdout, cmd.Stderr = output, output
		err = cmd.Run()
		output.Close()
		var exit *exec.ExitError
		if !errors.As(err, &exit) || exit.ExitCode() != runner.TemporaryFailure {
			t.Fatalf("mail setup did not defer: %v", err)
		}
		data, err := os.ReadFile(output.Name())
		if err != nil || len(data) != 0 {
			t.Fatal("mail setup emitted raw diagnostics")
		}
	}
}
