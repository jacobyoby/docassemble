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

func newAggregate(t *testing.T, component Component) *Aggregator {
	t.Helper()
	a, err := New(component)
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func snapshot(t *testing.T, a *Aggregator) Snapshot {
	t.Helper()
	s, err := a.Snapshot()
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func feed(t *testing.T, a *Aggregator, stream Stream, data []byte) {
	t.Helper()
	if err := a.Feed(stream, data); err != nil {
		t.Fatal(err)
	}
}

func finish(t *testing.T, a *Aggregator, stream Stream) {
	t.Helper()
	if err := a.Finish(stream); err != nil {
		t.Fatal(err)
	}
}

func TestStatusAndLatencyBoundaries(t *testing.T) {
	statuses := []struct {
		text   string
		family int
	}{
		{"100", 0}, {"199", 0}, {"200", 1}, {"299", 1}, {"300", 2},
		{"399", 2}, {"400", 3}, {"499", 3}, {"500", 4}, {"599", 4},
	}
	latencies := []struct {
		millis  string
		seconds string
		bucket  int
	}{
		{"0", "0.000", 0}, {"99", "0.099", 0}, {"100", "0.100", 1},
		{"999", "0.999", 1}, {"1000", "1.000", 2}, {"29999", "29.999", 2},
		{"30000", "30.000", 3}, {"600000", "600.000", 3},
	}
	for _, component := range []Component{Nginx, UWsgi} {
		for _, status := range statuses {
			for _, latency := range latencies {
				formats := []string{"msecs=" + latency.millis}
				if component == Nginx {
					formats = append(formats, "seconds="+latency.seconds)
				}
				for _, timing := range formats {
					t.Run(component.name()+"/"+status.text+"/"+timing, func(t *testing.T) {
						a := newAggregate(t, component)
						line := []byte("PRIVACY_REQUEST status=" + status.text + " " + timing + "\r\n")
						for _, b := range line {
							feed(t, a, Stdout, []byte{b})
						}
						var expected counts
						expected.status[status.family] = 1
						expected.latency[latency.bucket] = 1
						if a.counts != expected {
							t.Fatalf("counts: %#v; want %#v", a.counts, expected)
						}
					})
				}
			}
		}
	}
}

func TestMalformedLinesCannotBecomeRequests(t *testing.T) {
	for _, value := range []string{"0", "99", "600", "0200", "+200", "-200", "2_00", "2000", "２００"} {
		a := newAggregate(t, Nginx)
		feed(t, a, Stdout, []byte("PRIVACY_REQUEST status="+value+" msecs=0\n"))
		if a.counts != (counts{rejected: 1}) {
			t.Fatalf("accepted malformed status %q", value)
		}
	}
	for _, value := range []string{"", "00", "01", "-1", "+0", "1_0", "0x10", "1.0", "600001", strings.Repeat("9", 3000), "١"} {
		a := newAggregate(t, UWsgi)
		feed(t, a, Stdout, []byte("PRIVACY_REQUEST status=200 msecs="+value+"\n"))
		if a.counts != (counts{rejected: 1}) {
			t.Fatalf("accepted malformed milliseconds of length %d", len(value))
		}
	}
	for _, value := range []string{"00.001", "+0.001", "-0.001", "0.1", "0.0000", "1e3", "600.001", "1000.000", "0.000 SYNTHETIC_PRIVATE", "nan", "١.000"} {
		a := newAggregate(t, Nginx)
		feed(t, a, Stderr, []byte("PRIVACY_REQUEST status=200 seconds="+value+"\n"))
		if a.counts != (counts{rejected: 1}) {
			t.Fatalf("accepted malformed seconds %q", value)
		}
	}
	a := newAggregate(t, UWsgi)
	feed(t, a, Stderr, []byte("PRIVACY_REQUEST status=200 seconds=0.000\n"))
	if a.counts != (counts{rejected: 1}) {
		t.Fatal("uWSGI accepted nginx timing")
	}
}

func TestClassificationAndExactSchema(t *testing.T) {
	cases := []struct {
		line     []byte
		rejected bool
	}{
		{[]byte(""), false}, {[]byte("ordinary SYNTHETIC_PRIVATE"), false},
		{[]byte("PRIVACY_REQUESTx status=200 msecs=0"), false},
		{[]byte(" PRIVACY_REQUEST status=200 msecs=0"), false},
		{[]byte("PRIVACY_REQUEST\tstatus=200 msecs=0"), false},
		{[]byte("PRIVACY_REQUEST"), true},
		{[]byte("PRIVACY_REQUEST  status=200 msecs=0"), true},
		{[]byte("PRIVACY_REQUEST status=200 msecs=0 "), true},
		{[]byte("PRIVACY_REQUEST msecs=0 status=200"), true},
		{[]byte("PRIVACY_REQUEST status=200 msecs=0\rhidden"), true},
		{[]byte("ordinary\x00private"), true}, {[]byte{0xff}, true},
	}
	keys := map[string]bool{"schema": true, "component": true, "status_1xx": true, "status_2xx": true, "status_3xx": true, "status_4xx": true, "status_5xx": true, "latency_fast": true, "latency_medium": true, "latency_slow": true, "latency_timeout": true, "unclassified": true, "rejected": true, "dropped": true}
	for index, item := range cases {
		t.Run(strconv.Itoa(index), func(t *testing.T) {
			a := newAggregate(t, Nginx)
			feed(t, a, Stdout, append(bytes.Clone(item.line), '\n'))
			want := counts{unclassified: 1}
			if item.rejected {
				want = counts{rejected: 1}
			}
			if a.counts != want {
				t.Fatalf("classification: %#v", a.counts)
			}
			data, err := json.Marshal(snapshot(t, a))
			if err != nil {
				t.Fatal(err)
			}
			if bytes.Contains(data, []byte("SYNTHETIC_PRIVATE")) {
				t.Fatal("raw marker reached output")
			}
			var record map[string]any
			if err := json.Unmarshal(data, &record); err != nil {
				t.Fatal(err)
			}
			if len(record) != len(keys) {
				t.Fatalf("unexpected fields: %#v", record)
			}
			for key, value := range record {
				if !keys[key] {
					t.Fatalf("unexpected field %q", key)
				}
				if key == "component" {
					if value != "nginx" {
						t.Fatal("component changed")
					}
				} else if number, ok := value.(float64); !ok || number < 0 || number > float64(CounterMax) {
					t.Fatalf("invalid count %q: %v", key, value)
				}
			}
			if record["schema"] != float64(1) {
				t.Fatal("wrong schema")
			}
		})
	}
}

func TestStreamIsolationAndRepeatedEOF(t *testing.T) {
	a := newAggregate(t, Nginx)
	feed(t, a, Stdout, []byte("PRIVACY_REQUEST status=2"))
	feed(t, a, Stderr, []byte("PRIVACY_REQUEST status=503 msecs=30000\n"))
	feed(t, a, Stdout, []byte("04 msecs=50"))
	finish(t, a, Stderr)
	finish(t, a, Stderr)
	if snapshot(t, a).Status2xx != 0 {
		t.Fatal("other stream's EOF consumed a partial line")
	}
	finish(t, a, Stdout)
	finish(t, a, Stdout)
	want := counts{status: [5]uint32{0, 1, 0, 0, 1}, latency: [4]uint32{1, 0, 0, 1}}
	if a.counts != want {
		t.Fatalf("counts: %#v", a.counts)
	}
	feed(t, a, Stdout, []byte("PRIVACY_REQUEST status=201 msecs=0\n"))
	if snapshot(t, a).Status2xx != 2 {
		t.Fatal("stream did not resume after EOF")
	}
}

func TestExactLengthOverflowAndRecovery(t *testing.T) {
	for _, size := range []int{MaxLine - 1, MaxLine, MaxLine + 1, MaxLine * 2} {
		for _, delimited := range []bool{false, true} {
			a := newAggregate(t, Nginx)
			input := bytes.Repeat([]byte("x"), size)
			if delimited {
				input = append(input, '\n')
			}
			feed(t, a, Stdout, input[:17])
			feed(t, a, Stdout, input[17:])
			if size > MaxLine && snapshot(t, a).Dropped != 1 {
				t.Fatal("overflow not counted immediately")
			}
			finish(t, a, Stdout)
			finish(t, a, Stdout)
			if size <= MaxLine && a.counts != (counts{unclassified: 1}) {
				t.Fatalf("valid length %d was dropped", size)
			}
			if size > MaxLine && a.counts != (counts{dropped: 1}) {
				t.Fatalf("overflow counted incorrectly: %#v", a.counts)
			}
			feed(t, a, Stdout, []byte("PRIVACY_REQUEST status=200 msecs=0\n"))
			if snapshot(t, a).Status2xx != 1 {
				t.Fatal("stream did not recover")
			}
		}
	}
}

func TestInputsCopiedAndConsumedBufferErased(t *testing.T) {
	a := newAggregate(t, Nginx)
	input := []byte("PRIVACY_REQUEST status=200 msecs=0")
	feed(t, a, Stdout, input)
	clear(input)
	finish(t, a, Stdout)
	if snapshot(t, a).Status2xx != 1 {
		t.Fatal("partial input was borrowed after Feed returned")
	}
	feed(t, a, Stderr, []byte("SYNTHETIC_PRIVATE"))
	feed(t, a, Stderr, bytes.Repeat([]byte("x"), MaxLine+1))
	for _, stream := range a.streams {
		if stream.used != 0 || stream.buffer != ([MaxLine]byte{}) {
			t.Fatal("consumed bytes remain in owned buffer")
		}
	}
}

func TestFixedStorageAndNoPerChunkAllocation(t *testing.T) {
	a := newAggregate(t, Nginx)
	if size := reflect.TypeOf(*a).Size(); size > 8500 {
		t.Fatalf("unbounded state size: %d", size)
	}
	input := bytes.Repeat([]byte("x"), 1024*1024)
	allocations := testing.AllocsPerRun(20, func() {
		if err := a.Feed(Stdout, input); err != nil {
			panic(err)
		}
		if err := a.Finish(Stdout); err != nil {
			panic(err)
		}
	})
	if allocations != 0 {
		t.Fatalf("allocated %v times per oversized chunk", allocations)
	}
}

func TestInvalidInputsDoNotMutateState(t *testing.T) {
	for _, value := range []Component{0, 3, 255} {
		if a, err := New(value); a != nil || !errors.Is(err, ErrComponent) {
			t.Fatal("invalid component accepted")
		}
	}
	for _, text := range []string{"", "NGINX", "uwsgilog", "SYNTHETIC_PRIVATE"} {
		if _, err := ParseComponent(text); !errors.Is(err, ErrComponent) || strings.Contains(err.Error(), text) && text != "" {
			t.Fatal("invalid component message leaked input")
		}
	}
	for _, a := range []*Aggregator{nil, {}} {
		if err := a.Feed(Stdout, nil); !errors.Is(err, ErrComponent) {
			t.Fatal("invalid state accepted")
		}
		if err := a.Finish(Stdout); !errors.Is(err, ErrComponent) {
			t.Fatal("invalid state accepted")
		}
		if _, err := a.Snapshot(); !errors.Is(err, ErrComponent) {
			t.Fatal("invalid state accepted")
		}
	}
	a := newAggregate(t, Nginx)
	feed(t, a, Stdout, []byte("retained partial"))
	before := *a
	for _, stream := range []Stream{0, 3, 255} {
		if err := a.Feed(stream, []byte("private")); !errors.Is(err, ErrStream) {
			t.Fatal("invalid stream accepted")
		}
		if err := a.Finish(stream); !errors.Is(err, ErrStream) {
			t.Fatal("invalid stream accepted")
		}
		if *a != before {
			t.Fatal("invalid operation mutated state")
		}
	}
}
