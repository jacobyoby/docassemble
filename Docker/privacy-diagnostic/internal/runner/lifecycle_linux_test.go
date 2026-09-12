package runner

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func ready(t *testing.T, path string) []int {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		data, err := os.ReadFile(path)
		var pids []int
		if err == nil && json.Unmarshal(data, &pids) == nil && len(pids) > 0 {
			return pids
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("native readiness deadline exceeded")
	return nil
}

func gone(t *testing.T, pid int) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if syscall.Kill(pid, 0) == syscall.ESRCH {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("process %d survived cleanup", pid)
}

func startLifecycle(t *testing.T, mode string) (*exec.Cmd, *bytes.Buffer, []int, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "ready")
	cmd := fixtureCommand(t, "runner", mode)
	cmd.Env = append(cmd.Env, "PRIVACY_RUNNER_READY="+path)
	out := &bytes.Buffer{}
	cmd.Stdout, cmd.Stderr = out, out
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if cmd.ProcessState == nil {
			cmd.Process.Kill()
			cmd.Wait()
		}
	})
	return cmd, out, ready(t, path), path
}

func TestGracefulStopAndForwarding(t *testing.T) {
	for _, mode := range []string{"signals-nginx", "signals-uwsgi"} {
		t.Run(mode, func(t *testing.T) {
			cmd, out, pids, path := startLifecycle(t, mode)
			for _, step := range []struct {
				sig  syscall.Signal
				file string
			}{{syscall.SIGHUP, ".hup"}, {syscall.SIGUSR1, ".reopen"}} {
				if err := cmd.Process.Signal(step.sig); err != nil {
					t.Fatal(err)
				}
				ready(t, path+step.file)
			}
			if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
				t.Fatal(err)
			}
			if err := cmd.Wait(); err != nil {
				t.Fatalf("graceful shutdown: %v output=%q", err, out.Bytes())
			}
			all := records(t, out.Bytes())
			last := all[len(all)-1]
			if last.Status2xx != 3 {
				t.Fatalf("forwarded or final signal counters missing: %#v", last)
			}
			ready(t, path+".stopped")
			gone(t, pids[0])
		})
	}
}

func TestParentDeathDeliversNativeGracefulSignal(t *testing.T) {
	for _, mode := range []string{"signals-nginx", "signals-uwsgi"} {
		t.Run(mode, func(t *testing.T) {
			cmd, _, pids, path := startLifecycle(t, mode)
			if err := cmd.Process.Kill(); err != nil {
				t.Fatal(err)
			}
			if childExit(cmd.Wait()) != 137 {
				t.Fatal("control did not kill runner")
			}
			ready(t, path+".stopped")
			gone(t, pids[0])
		})
	}
}

func TestStubbornMasterAndOrphanDescendantAreKilled(t *testing.T) {
	for _, mode := range []string{"stubborn", "orphan"} {
		t.Run(mode, func(t *testing.T) {
			cmd, out, pids, _ := startLifecycle(t, mode)
			start := time.Now()
			want := 0
			if mode == "stubborn" {
				want = 137
				if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
					t.Fatal(err)
				}
			}
			if code := childExit(cmd.Wait()); code != want || time.Since(start) > 2*time.Second {
				t.Fatalf("bounded teardown: exit=%d duration=%s output=%q", code, time.Since(start), out.Bytes())
			}
			for _, pid := range pids {
				gone(t, pid)
			}
			records(t, out.Bytes())
		})
	}
}

func TestCoreDumpsDisabledAndInheritedDescriptorsClosed(t *testing.T) {
	path := filepath.Join(t.TempDir(), "private-descriptor")
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	cmd := fixtureCommand(t, "runner", "isolation")
	cmd.ExtraFiles = []*os.File{file}
	cmd.Env = append(cmd.Env, "PRIVACY_RUNNER_FD_PATH="+path)
	out, err := cmd.Output()
	if err != nil {
		t.Fatal("native isolation failed", err)
	}
	records(t, out)
}

func writeReady(path string, pids ...int) {
	data, err := json.Marshal(pids)
	if err != nil || os.WriteFile(path, data, 0600) != nil {
		os.Exit(98)
	}
}

func lifecycleFixture(mode string) bool {
	path := os.Getenv("PRIVACY_RUNNER_READY")
	switch mode {
	case "signals-nginx", "signals-uwsgi":
		ch := make(chan os.Signal, 4)
		signal.Notify(ch, syscall.SIGHUP, syscall.SIGUSR1, syscall.SIGTERM, syscall.SIGQUIT)
		writeReady(path, os.Getpid())
		for sig := range ch {
			switch sig {
			case syscall.SIGHUP:
				fmt.Fprintln(os.Stdout, "PRIVACY_REQUEST status=201 msecs=0")
				writeReady(path+".hup", os.Getpid())
			case syscall.SIGUSR1:
				fmt.Fprintln(os.Stderr, "PRIVACY_REQUEST status=202 msecs=0")
				writeReady(path+".reopen", os.Getpid())
			default:
				if mode == "signals-nginx" && sig != syscall.SIGQUIT || mode == "signals-uwsgi" && sig != syscall.SIGTERM {
					os.Exit(97)
				}
				writeReady(path+".stopped", os.Getpid())
				// The sink may already be gone after an uncatchable parent death.
				signal.Ignore(syscall.SIGPIPE)
				fmt.Fprintln(os.Stdout, "PRIVACY_REQUEST status=203 msecs=0")
				os.Exit(0)
			}
		}
	case "stubborn", "leaf":
		signal.Ignore(syscall.SIGQUIT, syscall.SIGTERM)
		writeReady(path, os.Getpid())
		for {
			time.Sleep(time.Second)
		}
	case "orphan":
		self, _ := os.Executable()
		leaf := exec.Command(self, "-test.run=^TestRunnerFixture$", "--", "native", "leaf")
		leaf.Stdout, leaf.Stderr = os.Stdout, os.Stderr
		leaf.Env = append(os.Environ(), "PRIVACY_RUNNER_READY="+path+".leaf")
		if leaf.Start() != nil {
			os.Exit(98)
		}
		for i := 0; i < 100; i++ {
			if _, err := os.Stat(path + ".leaf"); err == nil {
				writeReady(path, os.Getpid(), leaf.Process.Pid)
				os.Exit(0)
			}
			time.Sleep(5 * time.Millisecond)
		}
		os.Exit(98)
	case "isolation":
		var limits syscall.Rlimit
		if syscall.Getrlimit(syscall.RLIMIT_CORE, &limits) != nil || limits.Cur != 0 || limits.Max != 0 {
			os.Exit(96)
		}
		entries, err := os.ReadDir("/proc/self/fd")
		if err != nil {
			os.Exit(98)
		}
		for _, entry := range entries {
			link, _ := os.Readlink("/proc/self/fd/" + entry.Name())
			if link == os.Getenv("PRIVACY_RUNNER_FD_PATH") {
				os.Exit(95)
			}
		}
		os.Exit(0)
	default:
		return false
	}
	return true
}
