//go:build !linux

package runner

func run(options) int { return RunnerFailure }
