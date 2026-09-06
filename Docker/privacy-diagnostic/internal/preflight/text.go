// Package preflight validates the maintained native privacy configuration.
// Rejections carry no input, path, command output, or exception details.
package preflight

import (
	"errors"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	MaxBytes    = 1024 * 1024
	Invalid     = 70
	UwsgiFormat = "PRIVACY_REQUEST status=%(status) msecs=%(msecs)"
	NginxFormat = "PRIVACY_REQUEST status=$status seconds=$request_time"
)

var ErrConfig = errors.New("native configuration rejected")

func text(data []byte) (string, error) {
	if len(data) > MaxBytes || !utf8.Valid(data) {
		return "", ErrConfig
	}
	for _, b := range data {
		if b < 32 && b != '\n' && b != '\r' && b != '\t' {
			return "", ErrConfig
		}
	}
	return string(data), nil
}

// Preserve the reviewed reference's Unicode line separators and CRLF handling.
// Other Python splitlines control separators were already rejected by text.
func lines(value string) []string {
	var result []string
	start, previousCR := 0, false
	for i, r := range value {
		if r == '\n' && previousCR {
			result[len(result)-1] = value[start-len(result[len(result)-1]) : i+1]
			start, previousCR = i+1, false
			continue
		}
		previousCR = r == '\r'
		if r == '\n' || r == '\r' || r == '\u0085' || r == '\u2028' || r == '\u2029' {
			end := i + utf8.RuneLen(r)
			result = append(result, value[start:end])
			start = end
		}
	}
	if start < len(value) {
		result = append(result, value[start:])
	}
	return result
}

func space(r rune) bool { return unicode.IsSpace(r) }

func absolute(value string) bool {
	if len(value) < 2 || value[0] != '/' {
		return false
	}
	for _, r := range value[1:] {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || strings.ContainsRune("_./-", r)) {
			return false
		}
	}
	for _, part := range strings.Split(value, "/") {
		if part == ".." {
			return false
		}
	}
	return true
}
