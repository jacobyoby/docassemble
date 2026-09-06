package monitor

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestStateEventsContainOnlyFixedFields(t *testing.T) {
	for _, component := range []string{"nginx", "uwsgi", "uwsgilog", "celery", "celerysingle", "websockets"} {
		for _, item := range []struct{ event, details, state string }{
			{"PROCESS_STATE_EXITED", "from_state:RUNNING expected:0 pid:42", "exited"},
			{"PROCESS_STATE_BACKOFF", "from_state:STARTING tries:1", "backoff"},
			{"PROCESS_STATE_FATAL", "from_state:BACKOFF", "fatal"},
		} {
			payload := "processname:" + component + " groupname:" + component + " " + item.details + " ignored:SYNTHETIC_PRIVATE"
			data, err := eventRecord(item.event, []byte(payload))
			if err != nil {
				t.Fatal(err)
			}
			assertRecord(t, data, component, "process_failed", item.state)
		}
	}
	data, err := eventRecord("TICK_60", []byte("when:1788654000"))
	if err != nil {
		t.Fatal(err)
	}
	assertRecord(t, data, "monitor", "monitor_alive", "ready")
}

func assertRecord(t *testing.T, data []byte, component, event, state string) {
	t.Helper()
	var value map[string]any
	if len(data) > 256 || !bytes.HasSuffix(data, []byte{'\n'}) || json.Unmarshal(data, &value) != nil || len(value) != 4 || value["schema"] != float64(1) || value["component"] != component || value["event"] != event || value["state"] != state {
		t.Fatalf("invalid fixed record: %q", data)
	}
	if bytes.Contains(data, []byte("SYNTHETIC_PRIVATE")) {
		t.Fatal("private marker retained")
	}
}

func TestExpectedAndUnrelatedEventsProduceNoRecord(t *testing.T) {
	for _, item := range []struct{ event, payload string }{
		{"PROCESS_STATE_EXITED", "processname:nginx groupname:nginx from_state:RUNNING expected:1 pid:42"},
		{"PROCESS_STATE_FATAL", "processname:SYNTHETIC_PRIVATE groupname:SYNTHETIC_PRIVATE from_state:BACKOFF"},
		{"PROCESS_STATE_FATAL", "processname:privacy-monitor groupname:privacy-monitor from_state:BACKOFF"},
		{"PROCESS_LOG_STDOUT", "SYNTHETIC_PRIVATE\n192.0.2.1 /interview?i=synthetic.yml"},
		{"PROCESS_STATE_STOPPED", "processname:uwsgi groupname:uwsgi from_state:STOPPING pid:42"},
	} {
		data, err := eventRecord(item.event, []byte(item.payload))
		if err != nil || len(data) != 0 {
			t.Fatalf("unrelated/expected event was reported: %q %v", data, err)
		}
	}
}

func TestMalformedFramesRejectWithoutInputInErrors(t *testing.T) {
	valid := "ver:3.0 server:SYNTHETIC_PRIVATE serial:12 pool:privacy-monitor poolserial:3 eventname:TICK_60 len:15"
	if value, err := parseHeader([]byte(valid)); err != nil || value.size != 15 || value.event != "TICK_60" {
		t.Fatal("valid Supervisor header rejected")
	}
	for _, input := range []string{
		"", valid + " len:20", strings.Replace(valid, "ver:3.0", "ver:4.0", 1),
		strings.Replace(valid, "len:15", "len:1025", 1), strings.Replace(valid, "len:15", "len:-1", 1),
		strings.Replace(valid, "len:15", "len:01", 1), strings.Replace(valid, "serial:12 ", "", 1),
		valid + "\nSYNTHETIC_PRIVATE", valid + "\x00", valid + "\t", strings.Repeat("a", MaxFrame+1),
	} {
		if _, err := parseHeader([]byte(input)); err != errProtocol {
			t.Fatalf("malformed header accepted or error varied: %v", err)
		}
	}
	for _, payload := range []string{
		"processname:uwsgi groupname:uwsgi from_state:RUNNING expected:maybe pid:42",
		"processname:uwsgi groupname:uwsgi from_state:RUNNING expected:0 pid:0",
		"processname:uwsgi groupname:other from_state:RUNNING expected:0 pid:42",
		"processname:uwsgi groupname:uwsgi from_state:RUNNING expected:0 pid:42 expected:1",
		"processname:uwsgi groupname:uwsgi from_state:SYNTHETIC_PRIVATE expected:0 pid:42",
	} {
		if _, err := eventRecord("PROCESS_STATE_EXITED", []byte(payload)); err != errProtocol {
			t.Fatalf("malformed payload accepted or error varied: %v", err)
		}
	}
}

func FuzzEventRecordsHaveOnlyFixedOutput(f *testing.F) {
	f.Add("PROCESS_STATE_EXITED", []byte("processname:uwsgi groupname:uwsgi from_state:RUNNING expected:0 pid:42"))
	f.Add("TICK_60", []byte("when:1788654000"))
	f.Add("PROCESS_STATE_FATAL", []byte("SYNTHETIC_PRIVATE"))
	f.Fuzz(func(t *testing.T, event string, payload []byte) {
		if len(payload) > MaxFrame+1 || len(event) > MaxFrame+1 {
			return
		}
		_, err := parseHeader(payload)
		if err != nil && err != errProtocol {
			t.Fatal("header error contains nonconstant data")
		}
		data, err := eventRecord(event, payload)
		if err != nil && err != errProtocol {
			t.Fatal("event error contains nonconstant data")
		}
		if len(data) == 0 {
			return
		}
		allowed := false
		for _, component := range []string{"nginx", "uwsgi", "uwsgilog", "celery", "celerysingle", "websockets"} {
			for _, state := range []string{"exited", "backoff", "fatal"} {
				allowed = allowed || bytes.Equal(data, fixed(component, "process_failed", state))
			}
		}
		allowed = allowed || bytes.Equal(data, fixed("monitor", "monitor_alive", "ready"))
		if !allowed || len(data) > 256 {
			t.Fatalf("unapproved output: %q", data)
		}
	})
}
