package preflight

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"runtime"
	"sync"
	"syscall"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/nativeguard"
)

type captured struct {
	mu       sync.Mutex
	stdout   []byte
	total    int
	overflow bool
	cancel   context.CancelFunc
}

type captureWriter struct {
	state  *captured
	stdout bool
}

func (w captureWriter) Write(data []byte) (int, error) {
	w.state.mu.Lock()
	defer w.state.mu.Unlock()
	if len(data) > MaxBytes-w.state.total {
		w.state.overflow = true
		w.state.cancel()
		return 0, ErrConfig
	}
	w.state.total += len(data)
	if w.stdout {
		w.state.stdout = append(w.state.stdout, data...)
	}
	return len(data), nil
}

func capture(command []string, timeout time.Duration) ([]byte, error) {
	if len(command) == 0 || timeout <= 0 || !nativeguard.OrdinaryExecutable(command[0]) {
		return nil, ErrConfig
	}
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	state := &captured{stdout: make([]byte, 0, MaxBytes), cancel: cancel}
	cmd := exec.CommandContext(ctx, command[0], command[1:]...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true, Pdeathsig: syscall.SIGKILL}
	cmd.Stdout, cmd.Stderr = captureWriter{state, true}, captureWriter{state, false}
	cmd.WaitDelay = time.Second
	cmd.Cancel = func() error {
		err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		if errors.Is(err, syscall.ESRCH) {
			return os.ErrProcessDone
		}
		return err
	}
	if cmd.Start() != nil {
		return nil, ErrConfig
	}
	err := cmd.Wait()
	// A leader can exit while a descendant retains capture pipes. WaitDelay
	// bounds the readers, and group cleanup is required even after leader exit.
	killErr := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	if err != nil || ctx.Err() != nil || state.overflow || killErr != nil && killErr != syscall.ESRCH {
		clear(state.stdout)
		return nil, ErrConfig
	}
	return state.stdout, nil
}
