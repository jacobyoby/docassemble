package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
)

const testMarker = "SYNTHETIC_PRIVATE_NATIVE"

func fixtureCommand(t *testing.T, role, mode string) *exec.Cmd {
	t.Helper()
	path, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	t.Cleanup(cancel)
	cmd := exec.CommandContext(ctx, path, "-test.run=^TestRunnerFixture$", "--", role, mode)
	cmd.Env = append(os.Environ(), "PRIVACY_RUNNER_FIXTURE=1")
	cmd.WaitDelay = time.Second
	return cmd
}

func records(t *testing.T, output []byte) []aggregate.Snapshot {
	t.Helper()
	if bytes.Contains(output, []byte(testMarker)) {
		t.Fatal("raw output leaked")
	}
	var all []aggregate.Snapshot
	decoder := json.NewDecoder(bytes.NewReader(output))
	for {
		var fields map[string]json.RawMessage
		if err := decoder.Decode(&fields); err != nil {
			if err == io.EOF {
				break
			}
			t.Fatal("non-JSON output", err)
		}
		if len(fields) != 14 {
			t.Fatalf("unexpected field count: %d", len(fields))
		}
		data, err := json.Marshal(fields)
		if err != nil {
			t.Fatal(err)
		}
		var value aggregate.Snapshot
		if err := json.Unmarshal(data, &value); err != nil {
			t.Fatal(err)
		}
		if _, err := json.Marshal(value); err != nil {
			t.Fatal(err)
		}
		all = append(all, value)
	}
	if len(all) == 0 {
		t.Fatal("missing final counters")
	}
	return all
}

func TestCapturedStreamsFinalCountersAndExit(t *testing.T) {
	cmd := fixtureCommand(t, "runner", "output")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if childExit(err) != 17 || stderr.Len() != 0 {
		t.Fatalf("exit/output changed: %v stderr=%q", err, stderr.String())
	}
	all := records(t, out)
	last := all[len(all)-1]
	if last.Status2xx != 1 || last.Status5xx != 1 || last.LatencyFast != 1 || last.LatencyTimeout != 1 || last.Unclassified != 2 || last.Rejected != 1 || last.Dropped != 1 {
		t.Fatalf("wrong final counts: %#v", last)
	}
}

func TestInvalidSinkAndMissingExecutableDoNotStartChild(t *testing.T) {
	for _, mode := range []string{"file-sink", "missing", "setid", "directory"} {
		t.Run(mode, func(t *testing.T) {
			cmd := fixtureCommand(t, "runner", mode)
			output, err := cmd.CombinedOutput()
			want := RunnerFailure
			if mode == "file-sink" {
				want = SinkFailure
			}
			if childExit(err) != want || len(output) != 0 {
				t.Fatalf("invalid setup: exit=%d output=%q", childExit(err), output)
			}
		})
	}
}

func TestBrokenAndFullSinksFailWithinDeadline(t *testing.T) {
	for _, mode := range []string{"broken", "full"} {
		t.Run(mode, func(t *testing.T) {
			cmd := fixtureCommand(t, "runner", mode)
			start := time.Now()
			output, err := cmd.CombinedOutput()
			if childExit(err) != SinkFailure || len(output) != 0 || time.Since(start) > 3*time.Second {
				t.Fatalf("sink failure not bounded: exit=%d duration=%s output=%q", childExit(err), time.Since(start), output)
			}
		})
	}
}

func TestSignalExitCodeIsPreserved(t *testing.T) {
	cmd := fixtureCommand(t, "runner", "signal-exit")
	out, err := cmd.Output()
	if childExit(err) != 128+int(syscall.SIGKILL) {
		t.Fatal("native signal exit changed", err)
	}
	records(t, out)
}

func TestPipeFlagsRestored(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	defer w.Close()
	fd := w.Fd()
	before, _, errno := syscall.Syscall(syscall.SYS_FCNTL, fd, syscall.F_GETFL, 0)
	if errno != 0 {
		t.Fatal(errno)
	}
	s, err := openSink(int(fd))
	if err != nil {
		t.Fatal(err)
	}
	if err := s.write(aggregate.Snapshot{Schema: 1, Component: "nginx"}, time.Second); err != nil {
		t.Fatal(err)
	}
	if err := s.close(); err != nil {
		t.Fatal(err)
	}
	// Do not call File.Fd here: it may itself restore blocking mode and mask a bug.
	after, _, errno := syscall.Syscall(syscall.SYS_FCNTL, fd, syscall.F_GETFL, 0)
	if errno != 0 || before != after {
		t.Fatalf("shared pipe flags changed: %d -> %d (%v)", before, after, errno)
	}
}

// This fixture is a real subprocess, so core limits and signal handlers never
// alter the parent test process. No production test bypass is exposed by Run.
func TestRunnerFixture(t *testing.T) {
	if os.Getenv("PRIVACY_RUNNER_FIXTURE") != "1" {
		return
	}
	args := os.Args
	role, mode := args[len(args)-2], args[len(args)-1]
	if role == "native" {
		nativeFixture(mode)
		os.Exit(99)
	}
	self, err := os.Executable()
	if err != nil {
		os.Exit(98)
	}
	opts, ok := parse([]string{"--component", "nginx", "--", self, "-test.run=^TestRunnerFixture$", "--", "native", mode})
	if !ok {
		os.Exit(98)
	}
	opts.interval, opts.sinkWait, opts.stopWait, opts.killWait = 30*time.Millisecond, 150*time.Millisecond, 200*time.Millisecond, 300*time.Millisecond
	if strings.HasSuffix(mode, "uwsgi") {
		opts.component = aggregate.UWsgi
		opts.command = append(opts.command[:len(opts.command)-2], "--die-on-term", "native", mode)
	}
	var sinkWriter *os.File
	if mode == "file-sink" {
		file, err := os.CreateTemp("", "counter-file")
		if err != nil {
			os.Exit(98)
		}
		opts.sinkFD = int(file.Fd())
	} else if mode == "missing" {
		opts.command[0] = "/missing/" + testMarker
	} else if mode == "directory" {
		opts.command[0] = "/tmp"
	} else if mode == "setid" {
		file, err := os.CreateTemp("", "counter-setid")
		if err != nil || file.Chmod(0755|os.ModeSetuid) != nil {
			os.Exit(98)
		}
		opts.command[0] = file.Name()
	} else if mode == "broken" || mode == "full" {
		r, w, err := os.Pipe()
		if err != nil {
			os.Exit(98)
		}
		sinkWriter = w
		opts.sinkFD = int(w.Fd())
		if mode == "broken" {
			r.Close()
		} else {
			if syscall.SetNonblock(opts.sinkFD, true) != nil {
				os.Exit(98)
			}
			for {
				_, err := syscall.Write(opts.sinkFD, bytes.Repeat([]byte("x"), 4096))
				if err == syscall.EAGAIN {
					break
				}
				if err != nil {
					os.Exit(98)
				}
			}
		}
	}
	code := run(opts)
	if sinkWriter != nil {
		sinkWriter.Close()
	}
	os.Exit(code)
}

func nativeFixture(mode string) {
	if lifecycleFixture(mode) {
		return
	}
	switch mode {
	case "output":
		fmt.Fprint(os.Stdout, "PRIVACY_REQUEST status=2")
		fmt.Fprint(os.Stderr, "PRIVACY_REQUEST status=503 seconds=30.000\n"+testMarker+"\n")
		fmt.Fprint(os.Stdout, "00 msecs=99\n"+testMarker+"\x00\n")
		fmt.Fprint(os.Stderr, strings.Repeat("x", 8192)+"\n")
		fmt.Fprint(os.Stdout, testMarker)
		os.Exit(17)
	case "signal-exit":
		syscall.Kill(os.Getpid(), syscall.SIGKILL)
	case "broken", "full":
		for {
			fmt.Fprintln(os.Stdout, testMarker)
			time.Sleep(time.Millisecond)
		}
	default:
		// A forbidden launch would create a detectable non-counter marker.
		fmt.Fprint(os.Stdout, testMarker+filepath.Base(os.Args[0])+strconv.Itoa(os.Getpid()))
	}
}
