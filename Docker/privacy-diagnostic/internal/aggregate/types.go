// Package aggregate reduces captured output to fixed, bounded counters.
// Callers must serialize Feed, Finish and Snapshot calls. No file or network I/O
// occurs here; the process runner remains responsible for capture and delivery.
package aggregate

import (
	"encoding/json"
	"errors"
)

const (
	MaxLine           = 4096
	CounterMax uint32 = 1<<31 - 1
)

type Component uint8

const (
	Nginx Component = iota + 1
	UWsgi
)

// Application profiles have no native request-count interpretation. Keep the
// original native value range separate, including its invalid sentinels.
const (
	Celery Component = 16 + iota
	CelerySingle
	Websockets
	Mail
)

type Stream uint8

const (
	Stdout Stream = iota + 1
	Stderr
)

var (
	ErrComponent = errors.New("invalid aggregate component")
	ErrStream    = errors.New("invalid aggregate stream")
	ErrSnapshot  = errors.New("invalid aggregate snapshot")
)

func ParseComponent(name string) (Component, error) {
	switch name {
	case "nginx":
		return Nginx, nil
	case "uwsgi":
		return UWsgi, nil
	case "celery":
		return Celery, nil
	case "celerysingle":
		return CelerySingle, nil
	case "websockets":
		return Websockets, nil
	case "mail":
		return Mail, nil
	default:
		return 0, ErrComponent
	}
}

func (c Component) application() bool { return c >= Celery && c <= Mail }

func (c Component) valid() bool { return c == Nginx || c == UWsgi || c.application() }

func (c Component) name() string {
	if c == Nginx {
		return "nginx"
	}
	if c == UWsgi {
		return "uwsgi"
	}
	switch c {
	case Celery:
		return "celery"
	case CelerySingle:
		return "celerysingle"
	case Websockets:
		return "websockets"
	case Mail:
		return "mail"
	}
	return ""
}

// Snapshot is a value copy. MarshalJSON rejects forged fields before encoding.
type Snapshot struct {
	Schema         uint8  `json:"schema"`
	Component      string `json:"component"`
	Status1xx      uint32 `json:"status_1xx"`
	Status2xx      uint32 `json:"status_2xx"`
	Status3xx      uint32 `json:"status_3xx"`
	Status4xx      uint32 `json:"status_4xx"`
	Status5xx      uint32 `json:"status_5xx"`
	LatencyFast    uint32 `json:"latency_fast"`
	LatencyMedium  uint32 `json:"latency_medium"`
	LatencySlow    uint32 `json:"latency_slow"`
	LatencyTimeout uint32 `json:"latency_timeout"`
	Unclassified   uint32 `json:"unclassified"`
	Rejected       uint32 `json:"rejected"`
	Dropped        uint32 `json:"dropped"`
}

func (s Snapshot) MarshalJSON() ([]byte, error) {
	component, err := ParseComponent(s.Component)
	if s.Schema != 1 || err != nil {
		return nil, ErrSnapshot
	}
	counts := [...]uint32{s.Status1xx, s.Status2xx, s.Status3xx, s.Status4xx,
		s.Status5xx, s.LatencyFast, s.LatencyMedium, s.LatencySlow,
		s.LatencyTimeout, s.Unclassified, s.Rejected, s.Dropped}
	for _, count := range counts {
		if count > CounterMax {
			return nil, ErrSnapshot
		}
	}
	if component.application() {
		for _, count := range counts[:9] {
			if count != 0 {
				return nil, ErrSnapshot
			}
		}
	}
	type wire Snapshot
	return json.Marshal(wire(s))
}

type streamState struct {
	buffer   [MaxLine]byte
	used     int
	dropping bool
}

func (s *streamState) erase() {
	clear(s.buffer[:s.used])
	s.used = 0
}

type counts struct {
	status       [5]uint32
	latency      [4]uint32
	unclassified uint32
	rejected     uint32
	dropped      uint32
}

// Aggregator owns exactly two fixed input buffers and bounded numeric state.
// Its zero value and nil pointers reject operations; construct it with New.
type Aggregator struct {
	component Component
	streams   [2]streamState
	counts    counts
}

func New(component Component) (*Aggregator, error) {
	if !component.valid() {
		return nil, ErrComponent
	}
	return &Aggregator{component: component}, nil
}

func (a *Aggregator) state(stream Stream) (*streamState, error) {
	if a == nil || !a.component.valid() {
		return nil, ErrComponent
	}
	if stream != Stdout && stream != Stderr {
		return nil, ErrStream
	}
	return &a.streams[stream-1], nil
}

func (a *Aggregator) Snapshot() (Snapshot, error) {
	if a == nil || !a.component.valid() {
		return Snapshot{}, ErrComponent
	}
	c := a.counts
	return Snapshot{Schema: 1, Component: a.component.name(),
		Status1xx: c.status[0], Status2xx: c.status[1], Status3xx: c.status[2],
		Status4xx: c.status[3], Status5xx: c.status[4],
		LatencyFast: c.latency[0], LatencyMedium: c.latency[1],
		LatencySlow: c.latency[2], LatencyTimeout: c.latency[3],
		Unclassified: c.unclassified, Rejected: c.rejected, Dropped: c.dropped}, nil
}

func increment(value *uint32) {
	if *value < CounterMax {
		*value++
	}
}
