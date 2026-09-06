package runner

import (
	"encoding/json"
	"errors"
	"os"
	"syscall"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
)

var errSink = errors.New("counter sink unavailable")

type sink struct {
	file  *os.File
	flags uintptr
}

// openSink rejects regular files and duplicates only a pipe/socket. Like the
// startup diagnostic, it restores shared descriptor flags when finished.
func openSink(source int) (*sink, error) {
	fd, err := syscall.Dup(source)
	if err != nil {
		return nil, errSink
	}
	syscall.CloseOnExec(fd)
	var st syscall.Stat_t
	if syscall.Fstat(fd, &st) != nil || (st.Mode&syscall.S_IFMT != syscall.S_IFIFO && st.Mode&syscall.S_IFMT != syscall.S_IFSOCK) {
		syscall.Close(fd)
		return nil, errSink
	}
	flags, _, errno := syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_GETFL, 0)
	if errno != 0 {
		syscall.Close(fd)
		return nil, errSink
	}
	_, _, errno = syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_SETFL, flags|syscall.O_NONBLOCK)
	if errno != 0 {
		syscall.Close(fd)
		return nil, errSink
	}
	s := &sink{file: os.NewFile(uintptr(fd), "counter-sink"), flags: flags}
	if s.file == nil {
		// NewFile accepts this nonnegative descriptor; retain a fail-closed guard.
		syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_SETFL, flags)
		syscall.Close(fd)
		return nil, errSink
	}
	return s, nil
}

func (s *sink) write(value aggregate.Snapshot, timeout time.Duration) error {
	data, err := json.Marshal(value)
	if err != nil || len(data) >= 8191 {
		return errSink
	}
	data = append(data, '\n')
	if s.file.SetWriteDeadline(time.Now().Add(timeout)) != nil {
		return errSink
	}
	n, err := s.file.Write(data)
	if err != nil || n != len(data) {
		return errSink
	}
	return nil
}

func (s *sink) close() error {
	_, _, errno := syscall.Syscall(syscall.SYS_FCNTL, s.file.Fd(), syscall.F_SETFL, s.flags)
	err := s.file.Close()
	if errno != 0 || err != nil {
		return errSink
	}
	return nil
}
