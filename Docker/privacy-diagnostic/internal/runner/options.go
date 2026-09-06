// Package runner captures one foreground service and emits counters only.
// Production execution requires Linux parent-death protection. Run is intended
// for a dedicated process: it disables core dumps and subscribes to signals.
package runner

import (
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
)

const (
	UsageFailure     = 64
	RunnerFailure    = 70
	SinkFailure      = 74
	TemporaryFailure = 75
)

type options struct {
	component aggregate.Component
	command   []string
	sinkFD    int
	interval  time.Duration
	sinkWait  time.Duration
	stopWait  time.Duration
	killWait  time.Duration
}

func (o options) groupDelay() time.Duration {
	switch o.component {
	case aggregate.Celery, aggregate.CelerySingle, aggregate.Websockets, aggregate.Mail:
		return o.stopWait // Allow the service master its full worker-drain window.
	default:
		return o.stopWait / 2
	}
}

func parse(args []string) (options, bool) {
	if len(args) < 4 || args[0] != "--component" || args[2] != "--" {
		return options{}, false
	}
	component, err := aggregate.ParseComponent(args[1])
	if err != nil || !filepath.IsAbs(args[3]) {
		return options{}, false
	}
	for _, arg := range args[3:] {
		if strings.ContainsRune(arg, 0) {
			return options{}, false
		}
	}
	if component == aggregate.UWsgi && !slices.Contains(args[4:], "--die-on-term") {
		return options{}, false
	}
	stopWait := 2 * time.Second
	switch component {
	case aggregate.Celery, aggregate.CelerySingle:
		stopWait = 60 * time.Second
	case aggregate.Websockets, aggregate.Mail:
		stopWait = 20 * time.Second
	}
	return options{component: component, command: slices.Clone(args[3:]), sinkFD: 1,
		interval: time.Second, sinkWait: 5 * time.Second,
		stopWait: stopWait, killWait: time.Second}, true
}

// Run accepts --component nginx|uwsgi|celery|celerysingle|websockets|mail -- /absolute/executable [arguments...].
// It never prints arguments, paths, errors, or captured native output.
// Mail alone passes stdin to the child, emits only a final snapshot, and maps
// every failure or interrupted delivery to EX_TEMPFAIL.
func Run(args []string) int {
	opts, ok := parse(args)
	if !ok {
		if len(args) >= 2 && args[0] == "--component" && args[1] == "mail" {
			return TemporaryFailure
		}
		return UsageFailure
	}
	code := run(opts)
	if opts.component == aggregate.Mail && code != 0 {
		return TemporaryFailure
	}
	return code
}
