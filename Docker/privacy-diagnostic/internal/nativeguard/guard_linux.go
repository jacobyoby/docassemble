package nativeguard

import (
	"errors"
	"io"
	"os"
	"strconv"
	"syscall"
)

var errProcess = errors.New("native process unavailable")

// SealDescriptors marks descriptors beyond stdio close-on-exec. Go-created
// descriptors already use CLOEXEC; bounded directory batches also handle any
// inherited launcher descriptors without allocating to the configured FD limit.
func SealDescriptors() (result error) {
	dir, err := os.Open("/proc/self/fd")
	if err != nil {
		return errProcess
	}
	defer func() {
		if dir.Close() != nil {
			result = errProcess
		}
	}()
	for {
		entries, err := dir.ReadDir(64)
		if err != nil && !errors.Is(err, io.EOF) {
			return errProcess
		}
		for _, entry := range entries {
			fd, parseErr := strconv.Atoi(entry.Name())
			if parseErr != nil {
				return errProcess
			}
			if fd < 3 {
				continue
			}
			_, _, errno := syscall.Syscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_SETFD, syscall.FD_CLOEXEC)
			if errno != 0 && errno != syscall.EBADF {
				return errProcess
			}
		}
		if errors.Is(err, io.EOF) {
			return nil
		}
	}
}

// OrdinaryExecutable rejects transitions that can clear PDEATHSIG at exec.
// Binaries/configuration must remain immutable between checking and execution.
func OrdinaryExecutable(path string) bool {
	info, err := os.Stat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode()&(os.ModeSetuid|os.ModeSetgid) != 0 {
		return false
	}
	n, err := syscall.Getxattr(path, "security.capability", nil)
	return err == nil && n == 0 || errors.Is(err, syscall.ENODATA) || errors.Is(err, syscall.ENOTSUP)
}
