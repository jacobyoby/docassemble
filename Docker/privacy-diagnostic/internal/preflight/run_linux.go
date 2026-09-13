package preflight

import (
	"io"
	"os"
	"syscall"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/nativeguard"
)

// Run is silent on every path. It is for a dedicated process: core dumps are
// disabled and inherited descriptors beyond stdio are sealed before native exec.
func Run(args []string) int {
	if syscall.Setrlimit(syscall.RLIMIT_CORE, &syscall.Rlimit{}) != nil || nativeguard.SealDescriptors() != nil {
		return Invalid
	}
	if len(args) == 2 && args[0] == "uwsgi" {
		if validateFile(args[1]) == nil {
			return 0
		}
	} else if len(args) == 1 && args[0] == "nginx" {
		data, err := capture([]string{"/usr/sbin/nginx", "-T", "-e", "stderr"}, 10*time.Second)
		defer clear(data)
		if err == nil && ValidateNginx(data) == nil {
			return 0
		}
	}
	return Invalid
}

func validateFile(path string) (result error) {
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		return ErrConfig
	}
	defer func() {
		if file.Close() != nil {
			result = ErrConfig
		}
	}()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return ErrConfig
	}
	data, err := io.ReadAll(io.LimitReader(file, MaxBytes+1))
	defer clear(data)
	if err != nil {
		return ErrConfig
	}
	return ValidateUwsgi(data)
}
