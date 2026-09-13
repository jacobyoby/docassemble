package preflight

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"
	"testing"
	"time"
)

func TestBoundedNativeCapture(t *testing.T) {
	t.Setenv("PRIVACY_PREFLIGHT_CAPTURE", "1")
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"success", "exit", "timeout", "stdout-overflow", "stderr-overflow", "combined-overflow"} {
		t.Run(mode, func(t *testing.T) {
			start := time.Now()
			data, err := capture([]string{self, "-test.run=^TestCaptureFixture$", "--", mode}, 200*time.Millisecond)
			if mode == "success" {
				if err != nil || !bytes.Equal(data, singleDump(minimalNginx)) || ValidateNginx(data) != nil {
					t.Fatal("successful stdout capture changed", err)
				}
			} else if err != ErrConfig || len(data) != 0 {
				t.Fatal("failed capture returned data or a non-fixed error")
			}
			if time.Since(start) > 2*time.Second {
				t.Fatal("capture exceeded bounded shutdown")
			}
		})
	}
}

func TestCaptureKillsOrphansAfterLeaderExit(t *testing.T) {
	t.Setenv("PRIVACY_PREFLIGHT_CAPTURE", "1")
	pidPath := filepath.Join(t.TempDir(), "leaf.pid")
	t.Setenv("PRIVACY_PREFLIGHT_PID", pidPath)
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	start := time.Now()
	data, err := capture([]string{self, "-test.run=^TestCaptureFixture$", "--", "orphan"}, 3*time.Second)
	if err != ErrConfig || len(data) != 0 || time.Since(start) > 2*time.Second {
		t.Fatal("orphan pipe retention was not bounded")
	}
	pidBytes, err := os.ReadFile(pidPath)
	if err != nil {
		t.Fatal("orphan did not start")
	}
	pid, err := strconv.Atoi(string(pidBytes))
	if err != nil || pid <= 1 {
		t.Fatal("invalid orphan PID")
	}
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if syscall.Kill(pid, 0) == syscall.ESRCH {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("orphan survived group cleanup")
}

func TestCaptureCombinedExactLimit(t *testing.T) {
	t.Setenv("PRIVACY_PREFLIGHT_CAPTURE", "1")
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	data, err := capture([]string{self, "-test.run=^TestCaptureFixture$", "--", "exact-limit"}, time.Second)
	if err != nil || !bytes.Equal(data, singleDump(minimalNginx)) {
		t.Fatal("exact combined byte limit was rejected", err)
	}
}

func TestCaptureFixture(t *testing.T) {
	if os.Getenv("PRIVACY_PREFLIGHT_CAPTURE") != "1" {
		return
	}
	switch os.Args[len(os.Args)-1] {
	case "success":
		os.Stdout.Write(singleDump(minimalNginx))
		fmt.Fprint(os.Stderr, "SYNTHETIC_PRIVATE_CONFIG")
	case "exact-limit":
		data := singleDump(minimalNginx)
		os.Stdout.Write(data)
		os.Stderr.Write(bytes.Repeat([]byte("x"), MaxBytes-len(data)))
	case "exit":
		fmt.Fprint(os.Stderr, "SYNTHETIC_PRIVATE_CONFIG")
		os.Exit(7)
	case "timeout", "leaf":
		if os.Args[len(os.Args)-1] == "leaf" {
			if os.WriteFile(os.Getenv("PRIVACY_PREFLIGHT_PID"), []byte(strconv.Itoa(os.Getpid())), 0600) != nil {
				os.Exit(98)
			}
		}
		time.Sleep(10 * time.Second)
	case "stdout-overflow":
		os.Stdout.Write(bytes.Repeat([]byte("x"), MaxBytes+1))
	case "stderr-overflow":
		os.Stderr.Write(bytes.Repeat([]byte("x"), MaxBytes+1))
	case "combined-overflow":
		os.Stdout.Write(bytes.Repeat([]byte("x"), 700000))
		os.Stderr.Write(bytes.Repeat([]byte("x"), 400000))
	case "orphan":
		self, _ := os.Executable()
		leaf := exec.Command(self, "-test.run=^TestCaptureFixture$", "--", "leaf")
		leaf.Stdout, leaf.Stderr = os.Stdout, os.Stderr
		if leaf.Start() != nil {
			os.Exit(98)
		}
		for i := 0; i < 100; i++ {
			if _, err := os.Stat(os.Getenv("PRIVACY_PREFLIGHT_PID")); err == nil {
				os.Exit(0)
			}
			time.Sleep(5 * time.Millisecond)
		}
		os.Exit(98)
	default:
		os.Exit(98)
	}
	os.Exit(0)
}
