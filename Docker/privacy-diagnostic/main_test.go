package main

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"strings"
	"syscall"
	"testing"
	"time"
)

func pipe(t *testing.T) (*os.File, *os.File) {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { r.Close(); w.Close() })
	return r, w
}

func flags(t *testing.T, fd int) uintptr {
	t.Helper()
	value, _, errno := syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_GETFL, 0)
	if errno != 0 {
		t.Fatal(errno)
	}
	return value
}

func capture(t *testing.T, args []string) (int, []byte) {
	t.Helper()
	r, w := pipe(t)
	fd := int(w.Fd())
	// Darwin records that a pipe was written in F_GETFL even for plain write(2).
	// Prime and drain it before taking the full flag-preservation baseline.
	if _, err := syscall.Write(fd, []byte("x")); err != nil {
		t.Fatal(err)
	}
	if _, err := io.ReadFull(r, make([]byte, 1)); err != nil {
		t.Fatal(err)
	}
	before := flags(t, fd)
	code := report(args, fd, 100*time.Millisecond)
	if after := flags(t, fd); after != before {
		t.Fatalf("descriptor flags changed: %d -> %d", before, after)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	return code, data
}

func TestEveryAllowedComponentAndPhase(t *testing.T) {
	for _, comp := range []string{"nginx", "uwsgi", "uwsgilog", "celery", "celerysingle", "websockets", "mail", "cron", "initialize", "maintenance"} {
		for _, stage := range []string{"activation", "config", "config_eval", "preflight", "launch"} {
			t.Run(comp+"/"+stage, func(t *testing.T) {
				code, data := capture(t, []string{comp, stage})
				if code != startupFailure {
					t.Fatalf("exit %d", code)
				}
				if len(data) >= 256 || bytes.Count(data, []byte("\n")) != 1 {
					t.Fatalf("invalid record framing: %q", data)
				}
				var record map[string]any
				if err := json.Unmarshal(data, &record); err != nil {
					t.Fatal(err)
				}
				if len(record) != 4 || record["schema"] != float64(1) || record["component"] != comp || record["event"] != "startup_failed" || record["phase"] != stage {
					t.Fatalf("wrong record: %#v", record)
				}
			})
		}
	}
}

func TestInvalidArgumentsCannotEnterOutput(t *testing.T) {
	marker := "SYNTHETIC_PRIVATE\n\"config\":true"
	cases := [][]string{nil, {"uwsgi"}, {"uwsgi", "config", marker}, {marker, "config"}, {"uwsgi", marker}, {"uwsgi", strings.Repeat(marker, 10000)}}
	for _, args := range cases {
		code, data := capture(t, args)
		if code != usageFailure {
			t.Fatalf("exit %d", code)
		}
		want := "{\"schema\":1,\"component\":\"launcher\",\"event\":\"startup_failed\",\"phase\":\"invocation\"}\n"
		if string(data) != want {
			t.Fatalf("nonconstant invalid-input record: %q", data)
		}
	}
}

func TestCronExecutionFailureUsesAGenericFixedEvent(t *testing.T) {
	code, data := capture(t, []string{"cron", "execution"})
	want := "{\"schema\":1,\"component\":\"cron\",\"event\":\"command_failed\",\"phase\":\"execution\"}\n"
	if code != startupFailure || string(data) != want {
		t.Fatalf("cron execution failure changed: %d %q", code, data)
	}
	code, _ = capture(t, []string{"mail", "execution"})
	if code != usageFailure {
		t.Fatal("cron-only execution phase escaped its component")
	}
}

func TestInvalidEnumBecomesFixedInvocationRecord(t *testing.T) {
	data, err := encode(failure{component(255), phase(255)})
	if err != nil || !bytes.Contains(data, []byte(`"phase":"invocation"`)) {
		t.Fatalf("invalid enum: %q %v", data, err)
	}
}

func TestClosedAndBrokenPipeReturnSinkFailure(t *testing.T) {
	if got := report([]string{"uwsgi", "config"}, -1, time.Second); got != sinkFailure {
		t.Fatalf("invalid descriptor: %d", got)
	}
	r, w := pipe(t)
	r.Close()
	if got := report([]string{"uwsgi", "config"}, int(w.Fd()), time.Second); got != sinkFailure {
		t.Fatalf("broken pipe: %d", got)
	}
}

func TestRegularFileRejectedWithoutWriting(t *testing.T) {
	f, err := os.CreateTemp(t.TempDir(), "sink")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if got := report([]string{"uwsgi", "config"}, int(f.Fd()), time.Second); got != sinkFailure {
		t.Fatalf("regular file: %d", got)
	}
	stat, err := f.Stat()
	if err != nil || stat.Size() != 0 {
		t.Fatalf("unexpected file write: %v", err)
	}
}

func TestUnixSocketCanDeliverFixedRecord(t *testing.T) {
	fds, err := syscall.Socketpair(syscall.AF_UNIX, syscall.SOCK_STREAM, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer syscall.Close(fds[0])
	defer syscall.Close(fds[1])
	if code := report([]string{"nginx", "preflight"}, fds[0], time.Second); code != startupFailure {
		t.Fatalf("socket exit %d", code)
	}
	buffer := make([]byte, 256)
	n, err := syscall.Read(fds[1], buffer)
	if err != nil || !json.Valid(bytes.TrimSpace(buffer[:n])) || !bytes.Contains(buffer[:n], []byte(`"phase":"preflight"`)) {
		t.Fatalf("socket record %q: %v", buffer[:n], err)
	}
}

func TestFullPipeDeadlineAndFlagRestoration(t *testing.T) {
	_, w := pipe(t)
	fd := int(w.Fd())
	original := flags(t, fd)
	if err := syscall.SetNonblock(fd, true); err != nil {
		t.Fatal(err)
	}
	chunk := bytes.Repeat([]byte("x"), 4096)
	filled := false
	for total := 0; total < 16*1024*1024; {
		n, err := syscall.Write(fd, chunk)
		if err == syscall.EAGAIN {
			filled = true
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		total += n
	}
	if !filled {
		t.Fatal("did not fill pipe")
	}
	// Fill any remainder smaller than the atomic chunk before testing timeout.
	for {
		_, err := syscall.Write(fd, []byte("x"))
		if err == syscall.EAGAIN {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
	}
	_, _, errno := syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_SETFL, original)
	if errno != 0 {
		t.Fatal(errno)
	}
	// Filling the pipe itself can change kernel-maintained status bits.
	original = flags(t, fd)
	start := time.Now()
	got := report([]string{"nginx", "preflight"}, fd, 40*time.Millisecond)
	elapsed := time.Since(start)
	if got != sinkFailure || elapsed < 20*time.Millisecond || elapsed > 2*time.Second {
		t.Fatalf("deadline: code=%d elapsed=%s", got, elapsed)
	}
	if flags(t, fd) != original {
		t.Fatal("original flags not restored")
	}
}

func TestNonpositiveTimeoutCannotWrite(t *testing.T) {
	_, w := pipe(t)
	for _, timeout := range []time.Duration{0, -time.Second} {
		if code := report([]string{"uwsgi", "config"}, int(w.Fd()), timeout); code != sinkFailure {
			t.Fatalf("exit %d", code)
		}
	}
}

func FuzzParseHasFixedBoundedOutput(f *testing.F) {
	f.Add("uwsgi", "activation")
	f.Add("cron", "execution")
	f.Add("private\nvalue", "private\nphase")
	f.Fuzz(func(t *testing.T, comp, stage string) {
		record, code := parse([]string{comp, stage})
		data, err := encode(record)
		if err != nil || len(data) > 256 || !json.Valid(bytes.TrimSpace(data)) {
			t.Fatal("invalid framing")
		}
		if code != startupFailure && code != usageFailure {
			t.Fatalf("unexpected code %d", code)
		}
		if code == usageFailure && !bytes.Contains(data, []byte(`"phase":"invocation"`)) {
			t.Fatal("invalid input was not replaced")
		}
	})
}
