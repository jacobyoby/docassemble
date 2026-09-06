// Package monitor consumes Supervisor state events without retaining process
// output, arguments, identifiers, or arbitrary event fields in its records.
package monitor

import (
	"encoding/json"
	"errors"
	"strconv"
	"strings"
)

const MaxFrame = 1024

var errProtocol = errors.New("monitor protocol unavailable")

type header struct {
	event string
	size  int
}

func fields(data []byte) (map[string]string, error) {
	if len(data) == 0 || len(data) > MaxFrame {
		return nil, errProtocol
	}
	for _, value := range data {
		if value < 32 || value > 126 {
			return nil, errProtocol
		}
	}
	result := map[string]string{}
	for _, field := range strings.Split(string(data), " ") {
		key, value, found := strings.Cut(field, ":")
		if !found || key == "" || value == "" || result[key] != "" || len(result) >= 16 {
			return nil, errProtocol
		}
		result[key] = value
	}
	return result, nil
}

func number(value string) (int, bool) {
	if value == "" || len(value) > 10 || len(value) > 1 && value[0] == '0' {
		return 0, false
	}
	for _, digit := range value {
		if digit < '0' || digit > '9' {
			return 0, false
		}
	}
	n, err := strconv.ParseUint(value, 10, 31)
	return int(n), err == nil
}

func parseHeader(data []byte) (header, error) {
	values, err := fields(data)
	if err != nil || values["ver"] != "3.0" || values["server"] == "" || values["pool"] == "" || values["eventname"] == "" {
		return header{}, errProtocol
	}
	for _, key := range []string{"serial", "poolserial"} {
		if _, ok := number(values[key]); !ok {
			return header{}, errProtocol
		}
	}
	size, ok := number(values["len"])
	if !ok || size > MaxFrame {
		return header{}, errProtocol
	}
	return header{values["eventname"], size}, nil
}

type record struct {
	Schema    int    `json:"schema"`
	Component string `json:"component"`
	Event     string `json:"event"`
	State     string `json:"state"`
}

func fixed(component, event, state string) []byte {
	data, _ := json.Marshal(record{1, component, event, state}) // Fixed string/integer fields cannot fail.
	return append(data, '\n')
}

func eventRecord(event string, payload []byte) ([]byte, error) {
	switch event {
	case "PROCESS_STATE_EXITED", "PROCESS_STATE_BACKOFF", "PROCESS_STATE_FATAL", "TICK_60":
	default:
		return nil, nil // Unsubscribed events are acknowledged without inspecting their body.
	}
	values, err := fields(payload)
	if err != nil {
		return nil, err
	}
	if event == "TICK_60" {
		if _, ok := number(values["when"]); !ok {
			return nil, errProtocol
		}
		return fixed("monitor", "monitor_alive", "ready"), nil
	}
	component := ""
	switch values["processname"] {
	case "nginx":
		component = "nginx"
	case "uwsgi":
		component = "uwsgi"
	case "uwsgilog":
		component = "uwsgilog"
	case "celery":
		component = "celery"
	case "celerysingle":
		component = "celerysingle"
	case "websockets":
		component = "websockets"
	default:
		return nil, nil // Other services and the listener itself are outside this subscription's report scope.
	}
	if values["groupname"] != component || values["from_state"] == "" {
		return nil, errProtocol
	}
	switch event {
	case "PROCESS_STATE_EXITED":
		pid, ok := number(values["pid"])
		if !ok || pid == 0 || values["from_state"] != "RUNNING" || values["expected"] != "0" && values["expected"] != "1" {
			return nil, errProtocol
		}
		if values["expected"] == "1" {
			return nil, nil
		}
		return fixed(component, "process_failed", "exited"), nil
	case "PROCESS_STATE_BACKOFF":
		if _, ok := number(values["tries"]); !ok {
			return nil, errProtocol
		}
		return fixed(component, "process_failed", "backoff"), nil
	default:
		return fixed(component, "process_failed", "fatal"), nil
	}
}
