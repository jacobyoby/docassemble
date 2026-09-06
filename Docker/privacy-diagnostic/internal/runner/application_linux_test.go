package runner

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func TestApplicationWorkersFinishInsideMasterGraceWindow(t *testing.T) {
	for _, profile := range []string{"celery", "celerysingle", "websockets", "mail"} {
		for _, parentDeath := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/parent-death-%v", profile, parentDeath), func(t *testing.T) {
				self, err := os.Executable()
				if err != nil {
					t.Fatal(err)
				}
				path := filepath.Join(t.TempDir(), "ready")
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				cmd := exec.CommandContext(ctx, self, "-test.run=^TestApplicationProcessFixture$", "--", "runner", profile)
				cmd.Env = append(os.Environ(), "PRIVACY_APPLICATION_FIXTURE=1", "PRIVACY_APPLICATION_READY="+path)
				var output bytes.Buffer
				cmd.Stdout, cmd.Stderr = &output, &output
				cmd.WaitDelay = time.Second
				if cmd.Start() != nil {
					t.Fatal("cannot start application fixture")
				}
				t.Cleanup(func() {
					if cmd.ProcessState == nil {
						cmd.Process.Kill()
						cmd.Wait()
					}
				})
				pids := ready(t, path)
				if parentDeath {
					if cmd.Process.Kill() != nil {
						t.Fatal("cannot terminate runner control")
					}
					if childExit(cmd.Wait()) != 137 {
						t.Fatal("runner kill control failed")
					}
				} else {
					if cmd.Process.Signal(syscall.SIGTERM) != nil {
						t.Fatal("cannot request application shutdown")
					}
					code := childExit(cmd.Wait())
					if profile == "mail" {
						if code != RunnerFailure || output.Len() != 0 {
							t.Fatalf("interrupted mail reported success: %d %q", code, output.Bytes())
						}
					} else {
						if code != 0 {
							t.Fatalf("worker interrupted before its drain window ended: %d %q", code, output.Bytes())
						}
						records(t, output.Bytes())
					}
				}
				ready(t, path+".completed")
				for _, pid := range pids {
					gone(t, pid)
				}
			})
		}
	}
}

func TestApplicationProcessFixture(t *testing.T) {
	if os.Getenv("PRIVACY_APPLICATION_FIXTURE") != "1" {
		return
	}
	role, profile := os.Args[len(os.Args)-2], os.Args[len(os.Args)-1]
	path := os.Getenv("PRIVACY_APPLICATION_READY")
	self, err := os.Executable()
	if err != nil {
		os.Exit(98)
	}
	if role == "runner" {
		opts, ok := parse([]string{"--component", profile, "--", self, "-test.run=^TestApplicationProcessFixture$", "--", "master", profile})
		if !ok {
			os.Exit(98)
		}
		opts.stopWait, opts.killWait, opts.sinkWait = time.Second, 200*time.Millisecond, 200*time.Millisecond
		os.Exit(run(opts))
	}
	stops := make(chan os.Signal, 2)
	signal.Notify(stops, syscall.SIGTERM)
	if role == "worker" {
		writeReady(path+".worker", os.Getpid())
		select {
		case <-stops:
			os.Exit(93) // Group TERM before normal work finishes is the regression.
		case <-time.After(750 * time.Millisecond):
			os.Exit(0)
		}
	}
	worker := exec.Command(self, "-test.run=^TestApplicationProcessFixture$", "--", "worker", profile)
	worker.Stdout, worker.Stderr = os.Stdout, os.Stderr
	worker.Env = os.Environ()
	if worker.Start() != nil {
		os.Exit(98)
	}
	for i := 0; i < 200; i++ {
		if _, err := os.Stat(path + ".worker"); err == nil {
			writeReady(path, os.Getpid(), worker.Process.Pid)
			<-stops
			if err := worker.Wait(); err != nil {
				os.Exit(childExit(err))
			}
			writeReady(path+".completed", os.Getpid())
			os.Exit(0)
		}
		time.Sleep(5 * time.Millisecond)
	}
	os.Exit(98)
}
