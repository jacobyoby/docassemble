package aggregate

import (
	"bytes"
	"context"
	"encoding/json"
	"math/rand"
	"os/exec"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

type operation struct {
	Stream string `json:"stream"`
	Data   []byte `json:"data"`
	Finish bool   `json:"finish"`
}

type scenario struct {
	Component  string      `json:"component"`
	Operations []operation `json:"operations"`
}

func referenceScenarios() []scenario {
	rng := rand.New(rand.NewSource(81))
	lines := [][]byte{
		[]byte("PRIVACY_REQUEST status=200 msecs=99\n"),
		[]byte("PRIVACY_REQUEST status=503 seconds=30.000\n"),
		[]byte("ordinary SYNTHETIC_PRIVATE\r\n"),
		[]byte("PRIVACY_REQUEST status=200 msecs=01\n"),
		[]byte("PRIVACY_REQUEST status=099 msecs=0\n"),
		[]byte("PRIVACY_REQUEST status=599 seconds=600.001\n"),
		[]byte("PRIVACY_REQUEST  status=200 msecs=0\n"),
		{0xff, 0, '\n'}, []byte("\n\r\n"),
		append(bytes.Repeat([]byte("x"), MaxLine), '\n'),
		append(bytes.Repeat([]byte("x"), MaxLine+1), '\n'),
		bytes.Repeat([]byte("x"), MaxLine+1),
	}
	cases := make([]scenario, 0, 240)
	for index := 0; index < 240; index++ {
		comp := "nginx"
		if index%2 != 0 {
			comp = "uwsgi"
		}
		item := scenario{Component: comp}
		for count := 0; count < 3; count++ {
			stream := "stdout"
			if rng.Intn(2) == 1 {
				stream = "stderr"
			}
			line := lines[rng.Intn(len(lines))]
			if index%5 == 0 {
				line = []byte("PRIVACY_REQUEST status=" + strconv.Itoa(80+rng.Intn(550)) + " msecs=" + strconv.Itoa(rng.Intn(610000)) + "\n")
			}
			for start := 0; start < len(line); {
				end := min(len(line), start+1+rng.Intn(1500))
				item.Operations = append(item.Operations, operation{Stream: stream, Data: bytes.Clone(line[start:end])})
				start = end
				if rng.Intn(5) == 0 {
					item.Operations = append(item.Operations, operation{Stream: stream, Finish: true})
				}
			}
			item.Operations = append(item.Operations, operation{Stream: stream, Data: nil})
		}
		item.Operations = append(item.Operations, operation{Stream: "stdout", Finish: true}, operation{Stream: "stderr", Finish: true}, operation{Stream: "stdout", Finish: true})
		cases = append(cases, item)
	}
	return cases
}

func TestSnapshotsMatchFrozenPythonReference(t *testing.T) {
	cases := referenceScenarios()
	input, err := json.Marshal(cases)
	if err != nil || len(input) > 8*1024*1024 {
		t.Fatal("invalid synthetic corpus", err)
	}
	script, err := filepath.Abs("../../../../tests/privacy_native/aggregate_reference.py")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, "python3.14", script)
	command.Stdin = bytes.NewReader(input)
	output, err := command.Output()
	if err != nil {
		if failure, ok := err.(*exec.ExitError); ok {
			t.Fatalf("reference failed: %v\n%s", err, failure.Stderr)
		}
		t.Fatal(err)
	}
	var result struct {
		SourceSHA256 string       `json:"source_sha256"`
		Snapshots    [][]Snapshot `json:"snapshots"`
	}
	if err := json.Unmarshal(output, &result); err != nil {
		t.Fatal(err)
	}
	const reviewedReference = "582582eacbb29d486e1a9b8205577664d5eb239f85493441970197b53f31951f"
	if result.SourceSHA256 != reviewedReference {
		t.Fatal("reference source changed; review semantic differences before updating the pinned hash")
	}
	if len(result.Snapshots) != len(cases) {
		t.Fatal("missing reference cases")
	}
	for index, item := range cases {
		comp, err := ParseComponent(item.Component)
		if err != nil {
			t.Fatal(err)
		}
		a := newAggregate(t, comp)
		expected := result.Snapshots[index]
		if len(expected) != len(item.Operations)+1 {
			t.Fatal("missing reference steps")
		}
		if snapshot(t, a) != expected[0] {
			t.Fatal("initial snapshot differs")
		}
		for step, op := range item.Operations {
			stream := Stdout
			if op.Stream == "stderr" {
				stream = Stderr
			}
			if op.Finish {
				finish(t, a, stream)
			} else {
				feed(t, a, stream, op.Data)
			}
			if got := snapshot(t, a); got != expected[step+1] {
				t.Fatalf("case %d step %d: Go=%#v Python=%#v", index, step, got, expected[step+1])
			}
		}
	}
	t.Logf("matched %d synthetic scenarios (%d input bytes), including intermediate snapshots", len(cases), len(input))
}
