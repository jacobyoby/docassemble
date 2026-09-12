//go:build !linux

package monitor

// Run rejects non-Linux platforms; no output is produced.
func Run(args []string) int {
	if len(args) != 0 {
		return 64
	}
	return 70
}
