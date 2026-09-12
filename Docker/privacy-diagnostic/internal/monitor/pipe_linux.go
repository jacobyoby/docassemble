package monitor

import (
	"os"
	"syscall"
	"time"
)

type pipe struct {
	file  *os.File
	flags uintptr
}

func openPipe(source int) (*pipe, error) {
	fd, err := syscall.Dup(source)
	if err != nil {
		return nil, errProtocol
	}
	syscall.CloseOnExec(fd)
	var stat syscall.Stat_t
	if syscall.Fstat(fd, &stat) != nil || stat.Mode&syscall.S_IFMT != syscall.S_IFIFO && stat.Mode&syscall.S_IFMT != syscall.S_IFSOCK {
		syscall.Close(fd)
		return nil, errProtocol
	}
	flags, _, errno := syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_GETFL, 0)
	if errno != 0 {
		syscall.Close(fd)
		return nil, errProtocol
	}
	_, _, errno = syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_SETFL, flags|syscall.O_NONBLOCK)
	if errno != 0 {
		syscall.Close(fd)
		return nil, errProtocol
	}
	file := os.NewFile(uintptr(fd), "monitor-pipe")
	if file == nil {
		syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_SETFL, flags)
		syscall.Close(fd)
		return nil, errProtocol
	}
	return &pipe{file, flags}, nil
}

func (p *pipe) close() error {
	_, _, errno := syscall.Syscall(syscall.SYS_FCNTL, p.file.Fd(), syscall.F_SETFL, p.flags)
	err := p.file.Close()
	if errno != 0 || err != nil {
		return errProtocol
	}
	return nil
}

func (p *pipe) write(data []byte, timeout time.Duration) error {
	if timeout <= 0 || p.file.SetWriteDeadline(time.Now().Add(timeout)) != nil {
		return errProtocol
	}
	n, err := p.file.Write(data)
	if err != nil || n != len(data) {
		return errProtocol
	}
	return nil
}
