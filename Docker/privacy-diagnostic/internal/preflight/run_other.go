//go:build !linux

package preflight

// Run requires the same Linux exec protections as the native service runner.
func Run([]string) int { return Invalid }
