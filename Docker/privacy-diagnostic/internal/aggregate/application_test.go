package aggregate

import (
	"bytes"
	"encoding/json"
	"errors"
	"reflect"
	"testing"
)

func TestApplicationOutputCannotBecomeRequestMetrics(t *testing.T) {
	for _, name := range []string{"celery", "celerysingle", "websockets", "mail", "cron"} {
		component, err := ParseComponent(name)
		if err != nil {
			t.Fatalf("application profile %s unavailable: %v", name, err)
		}
		a := newAggregate(t, component)
		feed(t, a, Stdout, []byte("SYNTHETIC_PRIVATE\nPRIVACY_REQUEST status=200 msecs=0\n"))
		feed(t, a, Stderr, []byte("PRIVACY_REQUEST status=500 seconds=0.001\n\xff\n"))
		feed(t, a, Stderr, bytes.Repeat([]byte{'x'}, MaxLine+1))
		finish(t, a, Stderr)
		s := snapshot(t, a)
		if s.Component != name || s.Unclassified != 3 || s.Rejected != 1 || s.Dropped != 1 || s.Status2xx != 0 || s.Status5xx != 0 || s.LatencyFast != 0 {
			t.Fatalf("application stream misclassified: %#v", s)
		}
		encoded, err := json.Marshal(s)
		if err != nil || bytes.Contains(encoded, []byte("SYNTHETIC_PRIVATE")) {
			t.Fatalf("invalid application serialization: %s %v", encoded, err)
		}
		for _, field := range []string{"Status1xx", "Status2xx", "Status3xx", "Status4xx", "Status5xx", "LatencyFast", "LatencyMedium", "LatencySlow", "LatencyTimeout"} {
			forged := s
			reflect.ValueOf(&forged).Elem().FieldByName(field).SetUint(1)
			if data, err := json.Marshal(forged); !errors.Is(err, ErrSnapshot) || len(data) != 0 {
				t.Fatalf("application request counters accepted: %s", field)
			}
		}
	}
}
