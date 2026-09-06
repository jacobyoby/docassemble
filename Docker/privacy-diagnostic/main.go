// privacy-diagnostic emits one fixed startup failure record to a bounded pipe.
// It accepts no message text, configuration, paths, or exception details.
package main

import (
	"encoding/json"
	"os"
	"syscall"
	"time"
)

const (
	usageFailure   = 64
	startupFailure = 70
	sinkFailure    = 74
	writeTimeout   = time.Second
)

type component uint8

const (
	launcher component = iota
	nginx
	uwsgi
	uwsgilog
	celery
	celerySingle
	websockets
	mail
)

type phase uint8

const (
	invocation phase = iota
	activation
	config
	configEval
	preflight
	launch
)

type failure struct {
	component component
	phase     phase
}

type wireRecord struct {
	Schema    int    `json:"schema"`
	Component string `json:"component"`
	Event     string `json:"event"`
	Phase     string `json:"phase"`
}

func parse(args []string) (failure, int) {
	invalid := failure{launcher, invocation}
	if len(args) != 2 {
		return invalid, usageFailure
	}
	var f failure
	switch args[0] {
	case "nginx":
		f.component = nginx
	case "uwsgi":
		f.component = uwsgi
	case "uwsgilog":
		f.component = uwsgilog
	case "celery":
		f.component = celery
	case "celerysingle":
		f.component = celerySingle
	case "websockets":
		f.component = websockets
	case "mail":
		f.component = mail
	default:
		return invalid, usageFailure
	}
	switch args[1] {
	case "activation":
		f.phase = activation
	case "config":
		f.phase = config
	case "config_eval":
		f.phase = configEval
	case "preflight":
		f.phase = preflight
	case "launch":
		f.phase = launch
	default:
		return invalid, usageFailure
	}
	return f, startupFailure
}

func encode(f failure) ([]byte, error) {
	// All strings come from these constants, never from CLI values.
	components := [...]string{"launcher", "nginx", "uwsgi", "uwsgilog", "celery", "celerysingle", "websockets", "mail"}
	phases := [...]string{"invocation", "activation", "config", "config_eval", "preflight", "launch"}
	if int(f.component) >= len(components) || int(f.phase) >= len(phases) {
		f = failure{launcher, invocation}
	}
	data, err := json.Marshal(wireRecord{1, components[f.component], "startup_failed", phases[f.phase]})
	return append(data, '\n'), err
}

func report(args []string, sinkFD int, timeout time.Duration) (code int) {
	f, code := parse(args)
	data, err := encode(f)
	if err != nil || len(data) > 256 || timeout <= 0 {
		return sinkFailure
	}

	fd, err := syscall.Dup(sinkFD)
	if err != nil {
		return sinkFailure
	}
	var output *os.File
	var originalFlags uintptr
	restoreFlags := false
	defer func() {
		if restoreFlags {
			_, _, errno := syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_SETFL, originalFlags)
			if errno != 0 {
				code = sinkFailure
			}
		}
		var closeErr error
		if output == nil {
			closeErr = syscall.Close(fd)
		} else {
			closeErr = output.Close()
		}
		if closeErr != nil {
			code = sinkFailure
		}
	}()

	var stat syscall.Stat_t
	if syscall.Fstat(fd, &stat) != nil {
		return sinkFailure
	}
	kind := stat.Mode & syscall.S_IFMT
	if kind != syscall.S_IFIFO && kind != syscall.S_IFSOCK {
		return sinkFailure
	}
	flags, _, errno := syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_GETFL, 0)
	if errno != 0 {
		return sinkFailure
	}
	originalFlags = flags
	_, _, errno = syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_SETFL, flags|syscall.O_NONBLOCK)
	if errno != 0 {
		return sinkFailure
	}
	restoreFlags = true
	// NewFile sees O_NONBLOCK and registers the descriptor with Go's poller.
	// The launcher is waiting for this process; restore its shared flags on exit.
	output = os.NewFile(uintptr(fd), "privacy-diagnostic")
	if output == nil || output.SetWriteDeadline(time.Now().Add(timeout)) != nil {
		return sinkFailure
	}
	written, err := output.Write(data)
	if err != nil || written != len(data) {
		return sinkFailure
	}
	return code
}

func main() {
	os.Exit(report(os.Args[1:], 1, writeTimeout))
}
