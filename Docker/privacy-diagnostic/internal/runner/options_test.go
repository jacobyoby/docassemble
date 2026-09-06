package runner

import (
	"reflect"
	"testing"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/aggregate"
)

func TestArgumentsAreExactAndOwned(t *testing.T) {
	args := []string{"--component", "uwsgi", "--", "/test/uwsgi", "--die-on-term"}
	value, ok := parse(args)
	if !ok || value.component != aggregate.UWsgi || value.sinkFD != 1 {
		t.Fatal("valid profile rejected")
	}
	args[3] = "private"
	if value.command[0] != "/test/uwsgi" {
		t.Fatal("borrowed caller arguments")
	}
	for _, bad := range [][]string{nil, {"nginx"}, {"--component", "private", "--", "/bin/true"},
		{"--component", "NGINX", "--", "/bin/true"}, {"--component", "nginx", "--", "relative"},
		{"--component", "nginx", "wrong", "/bin/true"}, {"--component", "uwsgi", "--", "/bin/true"},
		{"--component", "nginx", "--", "/bin/true", "nul\x00"}} {
		if got, ok := parse(bad); ok || !reflect.DeepEqual(got, options{}) || Run(bad) != UsageFailure {
			t.Fatal("invalid arguments accepted")
		}
	}
}

func TestApplicationProfilesRetainServiceShutdownWindows(t *testing.T) {
	for _, item := range []struct {
		name string
		wait time.Duration
	}{{"celery", 60 * time.Second}, {"celerysingle", 60 * time.Second}, {"websockets", 20 * time.Second}, {"mail", 20 * time.Second}, {"cron", 20 * time.Second}} {
		opts, ok := parse([]string{"--component", item.name, "--", "/synthetic/service"})
		if !ok || opts.stopWait != item.wait || opts.groupDelay() != item.wait || opts.killWait != time.Second || opts.sinkWait != 5*time.Second {
			t.Fatalf("application lifecycle profile unavailable: %s", item.name)
		}
	}
}
