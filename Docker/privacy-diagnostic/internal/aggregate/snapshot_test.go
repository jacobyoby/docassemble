package aggregate

import (
	"bytes"
	"encoding/json"
	"errors"
	"reflect"
	"strconv"
	"strings"
	"testing"
)

func TestEveryCounterSaturatesThroughFeed(t *testing.T) {
	a := newAggregate(t, Nginx)
	for i := range a.counts.status {
		a.counts.status[i] = CounterMax - 1
	}
	for i := range a.counts.latency {
		a.counts.latency[i] = CounterMax - 1
	}
	a.counts.rejected = CounterMax - 1
	a.counts.unclassified = CounterMax - 1
	a.counts.dropped = CounterMax - 1
	for repeat := 0; repeat < 3; repeat++ {
		for _, status := range []int{100, 200, 300, 400, 500} {
			for _, latency := range []int{0, 100, 1000, 30000} {
				feed(t, a, Stdout, []byte("PRIVACY_REQUEST status="+strconv.Itoa(status)+" msecs="+strconv.Itoa(latency)+"\n"))
			}
		}
		feed(t, a, Stderr, []byte("PRIVACY_REQUEST\nordinary\n"))
		feed(t, a, Stderr, bytes.Repeat([]byte("x"), MaxLine+1))
		finish(t, a, Stderr)
	}
	s := snapshot(t, a)
	data, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]any
	if err := json.Unmarshal(data, &fields); err != nil {
		t.Fatal(err)
	}
	for name, value := range fields {
		if name != "schema" && name != "component" && value != float64(CounterMax) {
			t.Fatalf("counter %s did not saturate: %v", name, value)
		}
	}
	s.Status2xx = 0
	s.Component = "SYNTHETIC_PRIVATE"
	if next := snapshot(t, a); next.Status2xx != CounterMax || next.Component != "nginx" {
		t.Fatal("snapshot aliases mutable state")
	}
}

func TestForgedSnapshotsCannotSerializePrivateOrOutOfRangeFields(t *testing.T) {
	valid := Snapshot{Schema: 1, Component: "uwsgi"}
	bad := []Snapshot{{}, {Schema: 2, Component: "uwsgi"}, {Schema: 1, Component: "SYNTHETIC_PRIVATE"}}
	for _, field := range []string{"Status1xx", "Status2xx", "Status3xx", "Status4xx", "Status5xx", "LatencyFast", "LatencyMedium", "LatencySlow", "LatencyTimeout", "Unclassified", "Rejected", "Dropped"} {
		copy := valid
		reflect.ValueOf(&copy).Elem().FieldByName(field).SetUint(uint64(CounterMax) + 1)
		bad = append(bad, copy)
	}
	for _, value := range bad {
		data, err := json.Marshal(value)
		if !errors.Is(err, ErrSnapshot) || len(data) != 0 {
			t.Fatalf("invalid snapshot accepted: %s %v", data, err)
		}
		if strings.Contains(err.Error(), "SYNTHETIC_PRIVATE") {
			t.Fatal("private field leaked into error")
		}
	}
	if _, err := json.Marshal(valid); err != nil {
		t.Fatal("valid control rejected", err)
	}
}

func FuzzFragmentationPreservesCounters(f *testing.F) {
	f.Add([]byte("PRIVACY_REQUEST status=200 msecs=0\n"), uint16(1), uint8(0))
	f.Add(append(bytes.Repeat([]byte("x"), MaxLine+1), []byte("\nPRIVACY_REQUEST status=503 seconds=30.000")...), uint16(4096), uint8(0))
	f.Add([]byte{0xff, '\n', '\r', '\n'}, uint16(2), uint8(1))
	f.Fuzz(func(t *testing.T, data []byte, split uint16, rawComponent uint8) {
		// Limit fuzz-case resource use; ordinary unit tests separately cover 1 MiB.
		if len(data) > 64*1024 {
			data = data[:64*1024]
		}
		components := [...]Component{Nginx, UWsgi, Celery, CelerySingle, Websockets, Mail, Cron}
		component := components[int(rawComponent)%len(components)]
		whole, parts := newAggregate(t, component), newAggregate(t, component)
		feed(t, whole, Stdout, data)
		finish(t, whole, Stdout)
		step := 1 + int(split)%8192
		for start := 0; start < len(data); start += step {
			end := min(start+step, len(data))
			// Avoid testing.Helper stack bookkeeping for each one-byte fragment.
			if err := parts.Feed(Stdout, data[start:end]); err != nil {
				t.Fatal(err)
			}
		}
		finish(t, parts, Stdout)
		if snapshot(t, whole) != snapshot(t, parts) {
			t.Fatal("fragmentation changed counters")
		}
		if _, err := json.Marshal(snapshot(t, parts)); err != nil {
			t.Fatal(err)
		}
		for _, stream := range parts.streams {
			if stream.used != 0 || stream.dropping || stream.buffer != ([MaxLine]byte{}) {
				t.Fatal("EOF retained bytes or drop state")
			}
		}
	})
}

func BenchmarkFragmentedOversizedLine(b *testing.B) {
	input := bytes.Repeat([]byte("x"), 64*1024)
	for _, step := range []int{1, 4096} {
		b.Run(strconv.Itoa(step), func(b *testing.B) {
			a, err := New(Nginx)
			if err != nil {
				b.Fatal(err)
			}
			b.SetBytes(int64(len(input)))
			b.ReportAllocs()
			b.ResetTimer()
			for b.Loop() {
				for start := 0; start < len(input); start += step {
					if err := a.Feed(Stdout, input[start:min(start+step, len(input))]); err != nil {
						b.Fatal(err)
					}
				}
				if err := a.Finish(Stdout); err != nil {
					b.Fatal(err)
				}
			}
			if a.counts != (counts{dropped: uint32(min(b.N, int(CounterMax)))}) {
				b.Fatal("oversized lines counted incorrectly")
			}
		})
	}
}
