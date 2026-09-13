package main

import (
	"os"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/preflight"
)

func main() { os.Exit(preflight.Run(os.Args[1:])) }
