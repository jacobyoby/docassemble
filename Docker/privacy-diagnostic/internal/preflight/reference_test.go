package preflight

import (
	"context"
	"encoding/json"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestDecisionsMatchFrozenReferenceAndExistingAssertions(t *testing.T) {
	script, err := filepath.Abs("../../../../tests/privacy_native/reference/preflight_reference.py")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, "python3.14", "-B", script)
	output, err := command.Output()
	if err != nil {
		if failure, ok := err.(*exec.ExitError); ok {
			t.Fatalf("reference tests failed: %v\n%s", err, failure.Stderr)
		}
		t.Fatal(err)
	}
	if len(output) > 16*1024*1024 {
		t.Fatal("oversized synthetic oracle output")
	}
	var reference struct {
		SourceSHA256 string `json:"source_sha256"`
		LegacyTests  int    `json:"legacy_tests"`
		Cases        []struct {
			Kind     string `json:"kind"`
			Data     []byte `json:"data"`
			Accepted bool   `json:"accepted"`
		} `json:"cases"`
		Globs []struct {
			Pattern  string `json:"pattern"`
			Name     string `json:"name"`
			Accepted bool   `json:"accepted"`
		} `json:"globs"`
	}
	if err := json.Unmarshal(output, &reference); err != nil {
		t.Fatal(err)
	}
	if reference.SourceSHA256 != "694f6a7bb916882234969544f994ba396efe16d2936631c94d5947762821f9ac" {
		t.Fatal("reference changed; review semantic differences before updating its pin")
	}
	if reference.LegacyTests < 20 || len(reference.Cases) < 100 || len(reference.Globs) != 10000 {
		t.Fatal("reference assertions or cases missing")
	}
	for i, item := range reference.Cases {
		var err error
		switch item.Kind {
		case "nginx":
			err = ValidateNginx(item.Data)
		case "uwsgi":
			err = ValidateUwsgi(item.Data)
		default:
			t.Fatal("unknown oracle case")
		}
		if (err == nil) != item.Accepted {
			t.Errorf("case %d (%s, %d bytes) accepted=%v want=%v: %.300q", i, item.Kind, len(item.Data), err == nil, item.Accepted, item.Data)
		}
	}
	for _, item := range reference.Globs {
		compiled, err := componentGlob(item.Pattern)
		if err != nil || compiled.MatchString(item.Name) != item.Accepted {
			t.Fatalf("glob %q matching %q differs from reference (want %v, error %v)", item.Pattern, item.Name, item.Accepted, err)
		}
	}
	t.Logf("matched %d parser decisions from %d existing tests and %d glob cases", len(reference.Cases), reference.LegacyTests, len(reference.Globs))
}
