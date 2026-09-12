package runner

import (
	"errors"
	"io"
	"os"
	"os/exec"
	"syscall"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
)

func graceful(component aggregate.Component) syscall.Signal {
	if component == aggregate.Nginx {
		return syscall.SIGQUIT
	}
	return syscall.SIGTERM
}

func signalProcess(pid int, sig syscall.Signal, group bool) error {
	if group {
		pid = -pid
	}
	err := syscall.Kill(pid, sig)
	if errors.Is(err, syscall.ESRCH) {
		return nil
	}
	return err
}

func groupAlive(pid int) (bool, error) {
	err := syscall.Kill(-pid, 0)
	if errors.Is(err, syscall.ESRCH) {
		return false, nil
	}
	return err == nil, err
}

type outputEvent struct {
	stream aggregate.Stream
	data   [4096]byte
	n      int
	end    bool
	failed bool
}

// Each reader and the two-slot channel have fixed storage. An acknowledged
// event is copied; buffers are cleared before reuse and on cancellation.
func readOutput(file *os.File, stream aggregate.Stream, events chan<- outputEvent, cancel <-chan struct{}, done chan<- struct{}) {
	defer func() { done <- struct{}{} }()
	event := outputEvent{stream: stream}
	defer clear(event.data[:])
	for {
		n, err := file.Read(event.data[:])
		event.n, event.end = n, err != nil || n == 0
		event.failed = err != nil && !errors.Is(err, io.EOF) && !errors.Is(err, os.ErrClosed)
		select {
		case events <- event:
		case <-cancel:
			return
		}
		clear(event.data[:])
		if event.end {
			return
		}
	}
}

func childExit(err error) int {
	if err == nil {
		return 0
	}
	var failure *exec.ExitError
	if errors.As(err, &failure) {
		if status, ok := failure.Sys().(syscall.WaitStatus); ok {
			if status.Signaled() {
				return 128 + int(status.Signal())
			}
			return status.ExitStatus()
		}
	}
	return RunnerFailure
}
