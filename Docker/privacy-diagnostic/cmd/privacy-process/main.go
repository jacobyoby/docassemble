// privacy-process wraps one foreground service with bounded counter capture.
package main

import (
	"os"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/runner"
)

func main() { os.Exit(runner.Run(os.Args[1:])) }
