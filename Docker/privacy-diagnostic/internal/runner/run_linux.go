package runner

import (
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/nativeguard"
)

type execution struct {
	opts          options
	cmd           *exec.Cmd
	counts        *aggregate.Aggregator
	output        *sink
	readers       [2]*os.File
	events        chan outputEvent
	cancelReaders chan struct{}
	readersDone   chan struct{}
	wait          <-chan int
	writes        chan error
	exited        bool
	exitCode      int
	ended         [2]bool
	failure       int
	dirty         bool
	writing       bool
	writeCanceled bool
	nextWrite     time.Time
	stopping      time.Time
	groupStopped  bool
	killed        bool
	forced        bool
}

func run(opts options) (result int) {
	if opts.interval <= 0 || opts.sinkWait <= 0 || opts.stopWait <= 0 || opts.killWait <= 0 {
		return UsageFailure
	}
	counts, err := aggregate.New(opts.component)
	if err != nil || len(opts.command) == 0 {
		return UsageFailure
	}
	if !nativeguard.OrdinaryExecutable(opts.command[0]) {
		return RunnerFailure
	}
	// PDEATHSIG is tied to the creating thread. Keep that thread alive and
	// locked until the child has exited or bounded teardown has failed.
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	if syscall.Setrlimit(syscall.RLIMIT_CORE, &syscall.Rlimit{}) != nil || nativeguard.SealDescriptors() != nil {
		return RunnerFailure
	}
	output, err := openSink(opts.sinkFD)
	if err != nil {
		return SinkFailure
	}
	defer func() {
		if output.close() != nil {
			result = SinkFailure
		}
	}()
	x := execution{opts: opts, counts: counts, output: output, dirty: true,
		events: make(chan outputEvent, 2), cancelReaders: make(chan struct{}),
		readersDone: make(chan struct{}, 2), writes: make(chan error, 1)}
	var writers [2]*os.File
	defer func() {
		for _, file := range append(x.readers[:], writers[:]...) {
			if file != nil {
				file.Close() // Already-returning failure, or closed by lifecycle cleanup.
			}
		}
	}()
	for i := range x.readers {
		x.readers[i], writers[i], err = os.Pipe()
		if err != nil {
			return RunnerFailure
		}
	}
	stops, hup, reopen := make(chan os.Signal, 2), make(chan os.Signal, 1), make(chan os.Signal, 1)
	signal.Notify(stops, syscall.SIGINT, syscall.SIGTERM)
	signal.Notify(hup, syscall.SIGHUP)
	signal.Notify(reopen, syscall.SIGUSR1)
	defer signal.Stop(stops)
	defer signal.Stop(hup)
	defer signal.Stop(reopen)
	x.cmd = exec.Command(opts.command[0], opts.command[1:]...)
	if opts.component == aggregate.Mail {
		// Exim already supplies the message on stdin. Preserve that stream
		// without a second retained message file or an intermediate reader.
		x.cmd.Stdin = os.Stdin
	}
	x.cmd.Stdout, x.cmd.Stderr = writers[0], writers[1]
	x.cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true, Pdeathsig: graceful(opts.component)}
	if x.cmd.Start() != nil {
		return RunnerFailure
	}
	for i, writer := range writers {
		if writer.Close() != nil {
			x.fail(RunnerFailure)
		}
		writers[i] = nil
	}
	wait := make(chan int, 1)
	x.wait = wait
	go func() { wait <- childExit(x.cmd.Wait()) }()
	for i, reader := range x.readers {
		go readOutput(reader, aggregate.Stream(i+1), x.events, x.cancelReaders, x.readersDone)
	}
	result = x.loop(stops, hup, reopen)
	close(x.cancelReaders)
	for i, reader := range x.readers {
		if reader.Close() != nil && result == 0 {
			result = RunnerFailure
		}
		x.readers[i] = nil
	}
	for range 2 {
		<-x.readersDone
	}
	for len(x.events) > 0 {
		event := <-x.events
		clear(event.data[:])
	}
	for _, stream := range []aggregate.Stream{aggregate.Stdout, aggregate.Stderr} {
		if counts.Finish(stream) != nil && result == 0 {
			result = RunnerFailure
		}
	}
	return result
}

func (x *execution) fail(code int) {
	if x.failure == 0 {
		x.failure = code
	}
}

func (x *execution) send(sig syscall.Signal, group bool) {
	if signalProcess(x.cmd.Process.Pid, sig, group) != nil {
		x.fail(RunnerFailure)
	}
}

func (x *execution) stop(now time.Time) {
	if x.stopping.IsZero() {
		x.stopping = now
		x.send(graceful(x.opts.component), x.exited)
	}
}

func (x *execution) advanceStop(now time.Time, alive bool) {
	if x.stopping.IsZero() {
		return
	}
	elapsed := now.Sub(x.stopping)
	if !x.groupStopped && (x.exited || elapsed >= x.opts.groupDelay()) {
		x.send(graceful(x.opts.component), true)
		x.groupStopped = true
	}
	if !x.killed && elapsed >= x.opts.stopWait {
		x.send(syscall.SIGKILL, true)
		x.killed = true
	}
	if elapsed >= x.opts.stopWait+x.opts.killWait {
		if !x.exited || alive || !x.ended[0] || !x.ended[1] {
			x.fail(RunnerFailure)
		}
		x.forced = true
	}
}

func (x *execution) consume(event outputEvent) {
	defer clear(event.data[:])
	if event.failed {
		x.fail(RunnerFailure)
	}
	if event.n > 0 && x.counts.Feed(event.stream, event.data[:event.n]) != nil {
		x.fail(RunnerFailure)
	}
	if event.end {
		x.ended[event.stream-1] = true
		if x.counts.Finish(event.stream) != nil {
			x.fail(RunnerFailure)
		}
	}
	x.dirty = true
}

func (x *execution) write(now time.Time) {
	value, err := x.counts.Snapshot()
	if err != nil {
		x.fail(RunnerFailure)
		return
	}
	x.writing, x.dirty = true, false
	x.nextWrite = now.Add(x.opts.interval)
	go func() { x.writes <- x.output.write(value, x.opts.sinkWait) }()
}

func (x *execution) loop(stops, hup, reopen <-chan os.Signal) int {
	tick := time.NewTicker(20 * time.Millisecond)
	defer tick.Stop()
	for {
		now := time.Now()
		select {
		case <-stops:
			if x.opts.component == aggregate.Mail {
				// A clean child shutdown does not prove that an interrupted
				// delivery completed. Preserve retry semantics for the caller.
				x.fail(RunnerFailure)
			}
			x.stop(now)
		default:
		}
		for _, item := range []struct {
			channel <-chan os.Signal
			signal  syscall.Signal
		}{{hup, syscall.SIGHUP}, {reopen, syscall.SIGUSR1}} {
			select {
			case <-item.channel:
				if !x.exited && x.stopping.IsZero() {
					x.send(item.signal, false)
				}
			default:
			}
		}
		alive, err := groupAlive(x.cmd.Process.Pid)
		if err != nil {
			x.fail(RunnerFailure)
		}
		if x.failure != 0 || x.exited && (alive || !x.ended[0] || !x.ended[1]) {
			x.stop(now)
		}
		x.advanceStop(now, alive)
		final := x.forced || x.exited && !alive && x.ended[0] && x.ended[1]
		// Exim limits total command output. Mail emits at most one final
		// record; service profiles retain their periodic progress counters.
		report := final || x.opts.component != aggregate.Mail && !now.Before(x.nextWrite)
		if x.failure == 0 && !x.writing && x.dirty && report {
			x.write(now)
		}
		if x.failure != 0 && x.writing && !x.writeCanceled {
			if x.output.file.SetWriteDeadline(now) != nil {
				x.fail(SinkFailure)
			}
			x.writeCanceled = true
		}
		if final && !x.writing && (x.failure != 0 || !x.dirty) {
			if x.failure != 0 {
				return x.failure
			}
			return x.exitCode
		}
		select {
		case event := <-x.events:
			x.consume(event)
			clear(event.data[:])
		case code := <-x.wait:
			x.exited, x.exitCode, x.wait = true, code, nil
		case err := <-x.writes:
			x.writing = false
			if err != nil {
				x.fail(SinkFailure)
			}
		case <-tick.C:
		}
	}
}
