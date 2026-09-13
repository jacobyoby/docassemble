package aggregate

import (
	"bytes"
	"unicode/utf8"
)

// Feed borrows chunk only for this call. Partial input is copied into a fixed
// buffer; oversized lines are discarded and counted exactly once, immediately.
func (a *Aggregator) Feed(stream Stream, chunk []byte) error {
	s, err := a.state(stream)
	if err != nil {
		return err
	}
	for len(chunk) > 0 {
		newline := bytes.IndexByte(chunk, '\n')
		if s.dropping {
			if newline < 0 {
				return nil
			}
			s.dropping = false
			chunk = chunk[newline+1:]
			continue
		}
		if newline < 0 {
			if len(chunk) > MaxLine-s.used {
				s.erase()
				s.dropping = true
				increment(&a.counts.dropped)
			} else {
				s.used += copy(s.buffer[s.used:], chunk)
			}
			return nil
		}
		if newline > MaxLine-s.used {
			s.erase()
			increment(&a.counts.dropped)
		} else if s.used == 0 {
			a.line(chunk[:newline])
		} else {
			s.used += copy(s.buffer[s.used:], chunk[:newline])
			a.line(s.buffer[:s.used])
			s.erase()
		}
		chunk = chunk[newline+1:]
	}
	return nil
}

// Finish processes one unterminated tail and resets only the requested stream.
// Repeated calls are harmless. Overflow was already counted by Feed.
func (a *Aggregator) Finish(stream Stream) error {
	s, err := a.state(stream)
	if err != nil {
		return err
	}
	if !s.dropping && s.used > 0 {
		a.line(s.buffer[:s.used])
	}
	s.erase()
	s.dropping = false
	return nil
}

func (a *Aggregator) line(line []byte) {
	if len(line) > 0 && line[len(line)-1] == '\r' {
		line = line[:len(line)-1]
	}
	if !utf8.Valid(line) || bytes.IndexByte(line, 0) >= 0 || bytes.IndexByte(line, '\r') >= 0 {
		increment(&a.counts.rejected)
		return
	}
	if a.component.application() {
		increment(&a.counts.unclassified)
		return
	}
	first := bytes.IndexByte(line, ' ')
	prefix := line
	if first >= 0 {
		prefix = line[:first]
	}
	if !bytes.Equal(prefix, []byte("PRIVACY_REQUEST")) {
		increment(&a.counts.unclassified)
		return
	}
	if first < 0 {
		increment(&a.counts.rejected)
		return
	}
	rest := line[first+1:]
	second := bytes.IndexByte(rest, ' ')
	if second < 0 || bytes.IndexByte(rest[second+1:], ' ') >= 0 {
		increment(&a.counts.rejected)
		return
	}
	status, goodStatus := requestStatus(rest[:second])
	milliseconds, goodLatency := requestLatency(rest[second+1:], a.component)
	if !goodStatus || !goodLatency {
		increment(&a.counts.rejected)
		return
	}
	increment(&a.counts.status[status/100-1])
	bucket := 3
	switch {
	case milliseconds < 100:
		bucket = 0
	case milliseconds < 1000:
		bucket = 1
	case milliseconds < 30000:
		bucket = 2
	}
	increment(&a.counts.latency[bucket])
}

func requestStatus(token []byte) (uint32, bool) {
	data, ok := bytes.CutPrefix(token, []byte("status="))
	if !ok || len(data) != 3 || data[0] < '1' || data[0] > '5' {
		return 0, false
	}
	return digits(data)
}

func requestLatency(token []byte, component Component) (uint32, bool) {
	if data, ok := bytes.CutPrefix(token, []byte("msecs=")); ok {
		value, valid := canonicalNumber(data, 6)
		return value, valid && value <= 600000
	}
	data, ok := bytes.CutPrefix(token, []byte("seconds="))
	if !ok || component != Nginx {
		return 0, false
	}
	dot := bytes.IndexByte(data, '.')
	if dot < 0 || len(data)-dot-1 != 3 {
		return 0, false
	}
	seconds, validSeconds := canonicalNumber(data[:dot], 3)
	fraction, validFraction := digits(data[dot+1:])
	value := seconds*1000 + fraction
	return value, validSeconds && validFraction && value <= 600000
}

func canonicalNumber(data []byte, maxDigits int) (uint32, bool) {
	if len(data) == 0 || len(data) > maxDigits || (len(data) > 1 && data[0] == '0') {
		return 0, false
	}
	return digits(data)
}

func digits(data []byte) (uint32, bool) {
	var value uint32
	for _, digit := range data {
		if digit < '0' || digit > '9' {
			return 0, false
		}
		value = value*10 + uint32(digit-'0')
	}
	return value, true
}
