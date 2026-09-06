// privacy-monitor consumes Supervisor state events and emits fixed failure records.
package main

import (
	"os"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/monitor"
)

func main() { os.Exit(monitor.Run(os.Args[1:])) }
