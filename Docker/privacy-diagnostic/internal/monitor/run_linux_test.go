package monitor

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"os"
	"strings"
	"syscall"
	"testing"
	"time"
)

type fixture struct {
	input, send, protocol, replies, output, reports *os.File
	descriptors                                     [3]int
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	f := &fixture{}
	for _, pair := range [][2]**os.File{{&f.input, &f.send}, {&f.replies, &f.protocol}, {&f.reports, &f.output}} {
		read, write, err := os.Pipe()
		if err != nil {
			t.Fatal(err)
		}
		*pair[0], *pair[1] = read, write
		t.Cleanup(func() { read.Close(); write.Close() })
	}
	f.descriptors = [3]int{int(f.input.Fd()), int(f.protocol.Fd()), int(f.output.Fd())}
	return f
}

func frame(event, payload string) string {
	return fmt.Sprintf("ver:3.0 server:SYNTHETIC_PRIVATE serial:12 pool:privacy-monitor poolserial:3 eventname:%s len:%d\n%s", event, len(payload), payload)
}

func collect(file *os.File) <-chan []byte {
	result := make(chan []byte, 1)
	go func() { data, _ := io.ReadAll(file); result <- data }()
	return result
}

func TestProtocolAcknowledgesOnlyAfterReportAndPreservesFlags(t *testing.T) {
	f := newFixture(t)
	flags := [3]uintptr{}
	for i, fd := range f.descriptors {
		flags[i], _, _ = syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_GETFL, 0)
	}
	protocol, reports := collect(f.replies), collect(f.reports)
	input := frame("PROCESS_STATE_EXITED", "processname:uwsgi groupname:uwsgi from_state:RUNNING expected:0 pid:42") +
		frame("PROCESS_STATE_EXITED", "processname:nginx groupname:nginx from_state:RUNNING expected:1 pid:43") +
		frame("TICK_60", "when:1788654000")
	if _, err := f.send.WriteString(input); err != nil {
		t.Fatal(err)
	}
	f.send.Close()
	if status := run(f.descriptors, time.Second); status != 0 {
		t.Fatalf("valid event stream failed: %d", status)
	}
	for i, fd := range f.descriptors {
		after, _, errno := syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_GETFL, 0)
		if errno != 0 || after != flags[i] {
			t.Fatal("shared descriptor flags changed")
		}
	}
	f.protocol.Close()
	f.output.Close()
	if got := string(<-protocol); got != "READY\n"+strings.Repeat("RESULT 2\nOKREADY\n", 3) {
		t.Fatalf("wrong Supervisor protocol: %q", got)
	}
	rows := bytes.Split(bytes.TrimSpace(<-reports), []byte{'\n'})
	if len(rows) != 3 {
		t.Fatalf("expected readiness, failure, heartbeat; got %d", len(rows))
	}
	assertRecord(t, append(rows[0], '\n'), "monitor", "monitor_ready", "ready")
	assertRecord(t, append(rows[1], '\n'), "uwsgi", "process_failed", "exited")
	assertRecord(t, append(rows[2], '\n'), "monitor", "monitor_alive", "ready")
}

func TestTruncatedOversizedAndStalledFramesAreNotAcknowledged(t *testing.T) {
	for _, item := range []struct {
		input string
		close bool
	}{
		{"SYNTHETIC_PRIVATE\n", false}, {strings.Repeat("x", MaxFrame+1), false},
		{frame("PROCESS_STATE_EXITED", "processname:uwsgi") + "SYNTHETIC_PRIVATE", false},
		{"ver:3.0 server:test serial:1 pool:test poolserial:1 eventname:TICK_60 len:1025\n", false},
		{"ver:3.0", false}, // A stalled header must hit its deadline.
		{"ver:3.0", true},  // EOF in a header is not a clean shutdown.
		{"ver:3.0 server:test serial:1 pool:test poolserial:1 eventname:TICK_60 len:15\nwhen:1", false},
		{"ver:3.0 server:test serial:1 pool:test poolserial:1 eventname:TICK_60 len:15\nwhen:1", true},
	} {
		f := newFixture(t)
		protocol, reports := collect(f.replies), collect(f.reports)
		if _, err := f.send.WriteString(item.input); err != nil {
			t.Fatal(err)
		}
		if item.close {
			f.send.Close()
		}
		started := time.Now()
		if status := run(f.descriptors, 40*time.Millisecond); status != ProtocolFailure || time.Since(started) > time.Second {
			t.Fatalf("malformed/stalled input did not fail promptly: %d", status)
		}
		f.protocol.Close()
		f.output.Close()
		if string(<-protocol) != "READY\n" {
			t.Fatal("invalid input was acknowledged")
		}
		data := <-reports
		if bytes.Contains(data, []byte("SYNTHETIC_PRIVATE")) || !bytes.Contains(data, []byte(`"event":"protocol_failed"`)) {
			t.Fatalf("unsafe or missing failure signal: %q", data)
		}
	}
}

func TestFailedRecordSinkLeavesEventUnacknowledged(t *testing.T) {
	f := newFixture(t)
	protocol := collect(f.replies)
	done := make(chan int, 1)
	go func() { done <- run(f.descriptors, time.Second) }()
	ready, err := bufio.NewReader(f.reports).ReadBytes('\n')
	if err != nil {
		t.Fatal(err)
	}
	assertRecord(t, ready, "monitor", "monitor_ready", "ready")
	f.reports.Close()
	f.send.WriteString(frame("PROCESS_STATE_FATAL", "processname:uwsgi groupname:uwsgi from_state:BACKOFF"))
	select {
	case code := <-done:
		if code != SinkFailure {
			t.Fatalf("broken sink returned %d", code)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("broken sink blocked")
	}
	f.protocol.Close()
	if got := string(<-protocol); got != "READY\n" {
		t.Fatalf("undelivered event was acknowledged: %q", got)
	}
}

func TestRegularAndFullSinksFail(t *testing.T) {
	for _, kind := range []string{"regular", "full", "protocol-full"} {
		f := newFixture(t)
		if kind == "regular" {
			file, err := os.CreateTemp(t.TempDir(), "synthetic")
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { file.Close() })
			f.descriptors[2] = int(file.Fd())
		} else {
			fd := f.descriptors[2]
			if kind == "protocol-full" {
				fd = f.descriptors[1]
			}
			if syscall.SetNonblock(fd, true) != nil {
				t.Fatal("cannot prepare full pipe")
			}
			var buffer [4096]byte
			for {
				_, err := syscall.Write(fd, buffer[:])
				if err == syscall.EAGAIN {
					break
				}
				if err != nil {
					t.Fatal(err)
				}
			}
		}
		started := time.Now()
		if code := run(f.descriptors, 40*time.Millisecond); code != SinkFailure || time.Since(started) > time.Second {
			t.Fatalf("%s sink did not fail promptly: %d", kind, code)
		}
	}
}
